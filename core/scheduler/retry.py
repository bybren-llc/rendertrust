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

"""Job retry service with exponential backoff and dead letter queue.

Provides retry logic for failed jobs:
- Exponential backoff: 2^retry_count seconds (1s, 2s, 4s)
- Maximum 3 retry attempts before moving to dead letter queue
- Attempts to dispatch retries to a different node when possible
- Permanently failed jobs are archived in the dead_letter_queue table

Usage:
    from core.scheduler.retry import schedule_retry

    # Called when a job fails -- automatically retries or moves to DLQ
    result = await schedule_retry(session, failed_job, "GPU out of memory")
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import structlog

from core.scheduler.dispatch import find_best_node, push_to_queue
from core.scheduler.job_service import update_job_status
from core.scheduler.models import DeadLetterEntry, JobDispatch, JobStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RETRIES: int = 3
BACKOFF_BASE: float = 2.0


# ---------------------------------------------------------------------------
# Retry Logic
# ---------------------------------------------------------------------------


def should_retry(job: JobDispatch) -> bool:
    """Determine whether a job is eligible for retry.

    A job can be retried if its current retry_count is less than MAX_RETRIES.

    Args:
        job: The failed JobDispatch record.

    Returns:
        True if the job has retries remaining, False otherwise.
    """
    return job.retry_count < MAX_RETRIES


def calculate_backoff(retry_count: int) -> float:
    """Calculate exponential backoff delay in seconds.

    Uses ``BACKOFF_BASE ** retry_count`` to produce delays of 1s, 2s, 4s
    for retry counts 0, 1, 2 respectively.

    Args:
        retry_count: The current retry attempt number (0-based).

    Returns:
        Backoff delay in seconds.
    """
    return BACKOFF_BASE**retry_count


# ---------------------------------------------------------------------------
# Retry Scheduling
# ---------------------------------------------------------------------------


async def schedule_retry(
    session: AsyncSession,
    job: JobDispatch,
    error_message: str,
) -> JobDispatch | DeadLetterEntry:
    """Schedule a retry for a failed job, or move it to the dead letter queue.

    If the job has retries remaining (retry_count < MAX_RETRIES):
    1. Transition the job to FAILED (records the error_message)
    2. Transition the job to QUEUED (increments retry_count)
    3. Attempt to find a different node and re-dispatch

    If the job has exhausted all retries:
    1. Move the job to the dead letter queue via move_to_dlq

    Args:
        session: Async database session.
        job: The JobDispatch record that failed.
        error_message: Description of the failure.

    Returns:
        The updated JobDispatch (if retried) or DeadLetterEntry (if moved to DLQ).
    """
    if should_retry(job):
        backoff = calculate_backoff(job.retry_count)

        logger.info(
            "job_retry_scheduled",
            job_id=str(job.id),
            retry_count=job.retry_count,
            backoff_seconds=backoff,
            error_message=error_message,
        )

        # Transition FAILED -> QUEUED (update_job_status handles retry_count increment)
        # First ensure job is in FAILED state if not already
        if job.status != JobStatus.FAILED:
            job = await update_job_status(
                session=session,
                job_id=job.id,
                new_status=JobStatus.FAILED,
                error_message=error_message,
            )

        # Now transition FAILED -> QUEUED (this increments retry_count)
        job = await update_job_status(
            session=session,
            job_id=job.id,
            new_status=JobStatus.QUEUED,
        )

        # Attempt to find a different node for the retry
        original_node_id = job.node_id
        best_node = await find_best_node(session, job.job_type)

        if best_node is not None:
            # Update the job to point to the new node
            job.node_id = best_node.id
            session.add(job)
            await session.flush()

            # Push to Redis queue (fail-open)
            await push_to_queue(
                node_id=str(best_node.id),
                job_id=str(job.id),
                job_type=job.job_type,
                payload_ref=job.payload_ref,
            )

            logger.info(
                "job_redispatched",
                job_id=str(job.id),
                original_node_id=str(original_node_id),
                new_node_id=str(best_node.id),
                retry_count=job.retry_count,
            )
        else:
            logger.warning(
                "job_retry_no_node_available",
                job_id=str(job.id),
                retry_count=job.retry_count,
            )

        return job

    # Max retries exceeded -- move to dead letter queue
    return await move_to_dlq(session, job, error_message)


# ---------------------------------------------------------------------------
# Dead Letter Queue
# ---------------------------------------------------------------------------


async def move_to_dlq(
    session: AsyncSession,
    job: JobDispatch,
    error_message: str,
) -> DeadLetterEntry:
    """Move a permanently failed job to the dead letter queue.

    Creates a DeadLetterEntry record with the full error history and
    marks the job as permanently FAILED.

    Args:
        session: Async database session.
        job: The JobDispatch record that has exhausted retries.
        error_message: The final error message.

    Returns:
        The created DeadLetterEntry record.
    """
    # Build error history from existing error_message and the new one
    error_history: list[str] = []
    if job.error_message and job.error_message != error_message:
        error_history.append(job.error_message)
    error_history.append(error_message)

    # Ensure job is in FAILED state
    if job.status != JobStatus.FAILED:
        job = await update_job_status(
            session=session,
            job_id=job.id,
            new_status=JobStatus.FAILED,
            error_message=error_message,
        )
    else:
        # Update the error_message on the job even if already FAILED
        job.error_message = error_message
        session.add(job)
        await session.flush()

    now = datetime.datetime.now(tz=datetime.UTC)

    dlq_entry = DeadLetterEntry(
        job_id=job.id,
        original_payload=job.payload_ref,
        error_history=error_history,
        failed_at=now,
        retry_count=job.retry_count,
    )
    session.add(dlq_entry)
    await session.flush()

    logger.warning(
        "job_moved_to_dlq",
        job_id=str(job.id),
        retry_count=job.retry_count,
        error_count=len(error_history),
        error_message=error_message,
    )

    return dlq_entry
