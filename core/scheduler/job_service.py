# Copyright 2026 ByBren, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Job status transition service with state machine validation.

Enforces a strict state machine for job lifecycle transitions:

    QUEUED -> DISPATCHED | FAILED
    DISPATCHED -> RUNNING | FAILED | QUEUED (retry)
    RUNNING -> COMPLETED | FAILED
    COMPLETED -> (terminal)
    FAILED -> QUEUED (retry)

Auto-sets timestamps on transitions:
- dispatched_at when entering DISPATCHED
- completed_at when entering COMPLETED or FAILED
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.scheduler.models import JobDispatch, JobStatus

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# State Machine
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.DISPATCHED, JobStatus.FAILED},
    JobStatus.DISPATCHED: {JobStatus.RUNNING, JobStatus.FAILED, JobStatus.QUEUED},  # QUEUED=retry
    JobStatus.RUNNING: {JobStatus.COMPLETED, JobStatus.FAILED},
    JobStatus.COMPLETED: set(),  # terminal
    JobStatus.FAILED: {JobStatus.QUEUED},  # retry
}


# ---------------------------------------------------------------------------
# Service Functions
# ---------------------------------------------------------------------------


async def update_job_status(
    session: AsyncSession,
    job_id: uuid.UUID,
    new_status: JobStatus,
    result_ref: str | None = None,
    error_message: str | None = None,
) -> JobDispatch:
    """Update job status with state machine validation.

    Validates that the transition is allowed by the state machine, then
    updates the job record with the new status and any associated metadata.

    Auto-set timestamps:
    - ``dispatched_at`` is set when transitioning to DISPATCHED
    - ``completed_at`` is set when transitioning to COMPLETED or FAILED

    Auto-set fields:
    - ``result_ref`` is set when transitioning to COMPLETED
    - ``error_message`` is set when transitioning to FAILED
    - ``retry_count`` is incremented when retrying (FAILED/DISPATCHED -> QUEUED)

    Args:
        session: Async database session.
        job_id: UUID of the job to update.
        new_status: The target status.
        result_ref: Reference to the job result (set on COMPLETED).
        error_message: Error description (set on FAILED).

    Returns:
        The updated JobDispatch record.

    Raises:
        ValueError: If the job is not found or the transition is invalid.
    """
    result = await session.execute(
        select(JobDispatch)
        .options(selectinload(JobDispatch.node))
        .where(JobDispatch.id == job_id)
    )
    job = result.scalar_one_or_none()

    if job is None:
        raise ValueError(f"Job not found: {job_id}")

    old_status = job.status
    allowed = VALID_TRANSITIONS.get(old_status, set())

    if new_status not in allowed:
        raise ValueError(
            f"Invalid transition: {old_status.value} -> {new_status.value}. "
            f"Allowed targets: {sorted(s.value for s in allowed) if allowed else '(terminal)'}"
        )

    now = datetime.datetime.now(tz=datetime.UTC)

    # Auto-set timestamps based on target status
    if new_status == JobStatus.DISPATCHED:
        job.dispatched_at = now

    if new_status in (JobStatus.COMPLETED, JobStatus.FAILED):
        job.completed_at = now

    # Auto-set result/error fields
    if new_status == JobStatus.COMPLETED and result_ref is not None:
        job.result_ref = result_ref

    if new_status == JobStatus.FAILED and error_message is not None:
        job.error_message = error_message

    # Increment retry count when re-queuing
    if new_status == JobStatus.QUEUED and old_status in (JobStatus.FAILED, JobStatus.DISPATCHED):
        job.retry_count += 1

    job.status = new_status
    session.add(job)
    await session.flush()

    logger.info(
        "job_status_updated",
        job_id=str(job_id),
        old_status=old_status.value,
        new_status=new_status.value,
        retry_count=job.retry_count,
    )

    return job


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> JobDispatch | None:
    """Get a job by ID with eager-loaded node relationship.

    Args:
        session: Async database session.
        job_id: UUID of the job to retrieve.

    Returns:
        The JobDispatch record, or None if not found.
    """
    result = await session.execute(
        select(JobDispatch)
        .options(selectinload(JobDispatch.node))
        .where(JobDispatch.id == job_id)
    )
    return result.scalar_one_or_none()


async def list_jobs(
    session: AsyncSession,
    user_id: uuid.UUID | None = None,  # noqa: ARG001
    status: JobStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[JobDispatch]:
    """List jobs with optional filters.

    Args:
        session: Async database session.
        user_id: Filter by user ID (reserved for future multi-tenant support).
        status: Filter by job status.
        limit: Maximum number of results (default 50).
        offset: Number of results to skip (default 0).

    Returns:
        List of JobDispatch records matching the filters.
    """
    query = select(JobDispatch).order_by(JobDispatch.created_at.desc())

    if status is not None:
        query = query.where(JobDispatch.status == status)

    # user_id filter reserved for future multi-tenant support
    # When a user_id column is added to JobDispatch, uncomment:
    # if user_id is not None:
    #     query = query.where(JobDispatch.user_id == user_id)

    query = query.limit(limit).offset(offset)

    result = await session.execute(query)
    return list(result.scalars().all())


async def cancel_job(session: AsyncSession, job_id: uuid.UUID) -> JobDispatch:
    """Cancel a QUEUED or DISPATCHED job by transitioning it to FAILED.

    Only jobs in QUEUED or DISPATCHED status can be cancelled. Jobs that
    are already RUNNING, COMPLETED, or FAILED cannot be cancelled.

    Args:
        session: Async database session.
        job_id: UUID of the job to cancel.

    Returns:
        The updated JobDispatch record.

    Raises:
        ValueError: If the job is not found or is not in a cancellable state.
    """
    result = await session.execute(
        select(JobDispatch)
        .options(selectinload(JobDispatch.node))
        .where(JobDispatch.id == job_id)
    )
    job = result.scalar_one_or_none()

    if job is None:
        raise ValueError(f"Job not found: {job_id}")

    cancellable = {JobStatus.QUEUED, JobStatus.DISPATCHED}
    if job.status not in cancellable:
        raise ValueError(
            f"Cannot cancel job in {job.status.value} state. "
            f"Only QUEUED or DISPATCHED jobs can be cancelled."
        )

    now = datetime.datetime.now(tz=datetime.UTC)
    old_status = job.status
    job.status = JobStatus.FAILED
    job.completed_at = now
    job.error_message = "Cancelled by user"
    session.add(job)
    await session.flush()

    logger.info(
        "job_cancelled",
        job_id=str(job_id),
        old_status=old_status.value,
    )

    return job
