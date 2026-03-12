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

"""Job status API endpoints for listing, querying, and cancelling jobs.

Provides authenticated endpoints for users to list jobs, get job details,
and cancel queued/dispatched jobs. Delegates to job_service for all
business logic.
"""

from __future__ import annotations

import uuid as _uuid
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from core.auth.jwt import get_current_user
from core.database import get_db_session
from core.scheduler.job_service import cancel_job, get_job, list_jobs
from core.scheduler.models import JobStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.models.base import User

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class JobResponse(BaseModel):
    """Single job response schema."""

    id: str
    node_id: str
    job_type: str
    payload_ref: str
    status: str
    result_ref: str | None
    error_message: str | None
    retry_count: int
    queued_at: str
    dispatched_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class JobListResponse(BaseModel):
    """Paginated job list response."""

    jobs: list[JobResponse]
    count: int


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/jobs")


# ---------------------------------------------------------------------------
# GET /jobs
# ---------------------------------------------------------------------------


@router.get("", response_model=JobListResponse)
async def list_jobs_endpoint(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    session: AsyncSession = Depends(get_db_session),
) -> JobListResponse:
    """List jobs with optional status filter and pagination.

    All jobs are returned (no per-user filtering -- JobDispatch has no
    user_id column yet). Authentication is still required.
    """
    # Validate status filter if provided
    job_status: JobStatus | None = None
    if status_filter is not None:
        try:
            job_status = JobStatus(status_filter)
        except ValueError:
            valid = [s.value for s in JobStatus]
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status: {status_filter}. Valid values: {valid}",
            ) from None

    jobs = await list_jobs(
        session=session,
        status=job_status,
        limit=limit,
        offset=offset,
    )

    job_responses = [
        JobResponse(
            id=str(job.id),
            node_id=str(job.node_id),
            job_type=job.job_type,
            payload_ref=job.payload_ref,
            status=job.status.value,
            result_ref=job.result_ref,
            error_message=job.error_message,
            retry_count=job.retry_count,
            queued_at=job.queued_at.isoformat(),
            dispatched_at=job.dispatched_at.isoformat() if job.dispatched_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            created_at=job.created_at.isoformat(),
            updated_at=job.updated_at.isoformat(),
        )
        for job in jobs
    ]

    logger.info(
        "jobs_listed",
        count=len(job_responses),
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )

    return JobListResponse(jobs=job_responses, count=len(job_responses))


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}
# ---------------------------------------------------------------------------


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_endpoint(
    job_id: str,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    session: AsyncSession = Depends(get_db_session),
) -> JobResponse:
    """Get a single job by ID.

    Returns 404 if the job does not exist, 422 if the ID format is invalid.
    """
    try:
        parsed_id = _uuid.UUID(job_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid job ID format",
        ) from None

    job = await get_job(session=session, job_id=parsed_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    logger.info("job_queried", job_id=str(job.id))

    return JobResponse(
        id=str(job.id),
        node_id=str(job.node_id),
        job_type=job.job_type,
        payload_ref=job.payload_ref,
        status=job.status.value,
        result_ref=job.result_ref,
        error_message=job.error_message,
        retry_count=job.retry_count,
        queued_at=job.queued_at.isoformat(),
        dispatched_at=job.dispatched_at.isoformat() if job.dispatched_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# POST /jobs/{job_id}/cancel
# ---------------------------------------------------------------------------


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job_endpoint(
    job_id: str,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    session: AsyncSession = Depends(get_db_session),
) -> JobResponse:
    """Cancel a QUEUED or DISPATCHED job.

    Returns 400 if the job is not in a cancellable state,
    404 if the job does not exist, 422 if the ID format is invalid.
    """
    try:
        parsed_id = _uuid.UUID(job_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid job ID format",
        ) from None

    try:
        job = await cancel_job(session=session, job_id=parsed_id)
    except ValueError as err:
        error_msg = str(err)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found",
            ) from err
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        ) from err

    await session.commit()

    logger.info("job_cancelled_via_api", job_id=str(job.id))

    return JobResponse(
        id=str(job.id),
        node_id=str(job.node_id),
        job_type=job.job_type,
        payload_ref=job.payload_ref,
        status=job.status.value,
        result_ref=job.result_ref,
        error_message=job.error_message,
        retry_count=job.retry_count,
        queued_at=job.queued_at.isoformat(),
        dispatched_at=job.dispatched_at.isoformat() if job.dispatched_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )
