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

"""Tests for the job status transition service (state machine validation).

Covers:
- Valid state transitions (QUEUED->DISPATCHED, DISPATCHED->RUNNING, etc.)
- Invalid transitions raise ValueError
- Auto-set timestamps (dispatched_at, completed_at)
- Auto-set fields (result_ref, error_message, retry_count)
- get_job / list_jobs / cancel_job
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from core.scheduler.job_service import (
    cancel_job,
    get_job,
    list_jobs,
    update_job_status,
)
from core.scheduler.models import EdgeNode, JobDispatch, JobStatus, NodeStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def edge_node(db_session: AsyncSession) -> EdgeNode:
    """Create a healthy edge node for job tests."""
    node = EdgeNode(
        name="test-node-01",
        public_key="test-public-key-for-job-service",
        capabilities=["render", "inference"],
        status=NodeStatus.HEALTHY,
        current_load=0.2,
    )
    db_session.add(node)
    await db_session.flush()
    return node


@pytest.fixture
async def queued_job(db_session: AsyncSession, edge_node: EdgeNode) -> JobDispatch:
    """Create a job in QUEUED status."""
    job = JobDispatch(
        node_id=edge_node.id,
        job_type="render",
        payload_ref="s3://bucket/payload-001.zip",
        status=JobStatus.QUEUED,
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.fixture
async def dispatched_job(db_session: AsyncSession, edge_node: EdgeNode) -> JobDispatch:
    """Create a job in DISPATCHED status."""
    job = JobDispatch(
        node_id=edge_node.id,
        job_type="render",
        payload_ref="s3://bucket/payload-002.zip",
        status=JobStatus.DISPATCHED,
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.fixture
async def running_job(db_session: AsyncSession, edge_node: EdgeNode) -> JobDispatch:
    """Create a job in RUNNING status."""
    job = JobDispatch(
        node_id=edge_node.id,
        job_type="inference",
        payload_ref="s3://bucket/payload-003.zip",
        status=JobStatus.RUNNING,
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.fixture
async def completed_job(db_session: AsyncSession, edge_node: EdgeNode) -> JobDispatch:
    """Create a job in COMPLETED status."""
    job = JobDispatch(
        node_id=edge_node.id,
        job_type="render",
        payload_ref="s3://bucket/payload-004.zip",
        status=JobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.fixture
async def failed_job(db_session: AsyncSession, edge_node: EdgeNode) -> JobDispatch:
    """Create a job in FAILED status."""
    job = JobDispatch(
        node_id=edge_node.id,
        job_type="render",
        payload_ref="s3://bucket/payload-005.zip",
        status=JobStatus.FAILED,
    )
    db_session.add(job)
    await db_session.flush()
    return job


# ---------------------------------------------------------------------------
# Valid transition tests
# ---------------------------------------------------------------------------


async def test_valid_transition_queued_to_dispatched(
    db_session: AsyncSession, queued_job: JobDispatch
) -> None:
    """QUEUED -> DISPATCHED is a valid transition."""
    result = await update_job_status(
        session=db_session,
        job_id=queued_job.id,
        new_status=JobStatus.DISPATCHED,
    )

    assert result.status == JobStatus.DISPATCHED
    assert result.dispatched_at is not None


async def test_valid_transition_dispatched_to_running(
    db_session: AsyncSession, dispatched_job: JobDispatch
) -> None:
    """DISPATCHED -> RUNNING is a valid transition."""
    result = await update_job_status(
        session=db_session,
        job_id=dispatched_job.id,
        new_status=JobStatus.RUNNING,
    )

    assert result.status == JobStatus.RUNNING


async def test_valid_transition_running_to_completed(
    db_session: AsyncSession, running_job: JobDispatch
) -> None:
    """RUNNING -> COMPLETED sets completed_at and result_ref."""
    result = await update_job_status(
        session=db_session,
        job_id=running_job.id,
        new_status=JobStatus.COMPLETED,
        result_ref="s3://bucket/result-003.zip",
    )

    assert result.status == JobStatus.COMPLETED
    assert result.completed_at is not None
    assert result.result_ref == "s3://bucket/result-003.zip"


async def test_valid_transition_running_to_failed(
    db_session: AsyncSession, running_job: JobDispatch
) -> None:
    """RUNNING -> FAILED sets completed_at and error_message."""
    result = await update_job_status(
        session=db_session,
        job_id=running_job.id,
        new_status=JobStatus.FAILED,
        error_message="GPU out of memory",
    )

    assert result.status == JobStatus.FAILED
    assert result.completed_at is not None
    assert result.error_message == "GPU out of memory"


async def test_valid_transition_failed_to_queued_retry(
    db_session: AsyncSession, failed_job: JobDispatch
) -> None:
    """FAILED -> QUEUED increments retry_count."""
    assert failed_job.retry_count == 0

    result = await update_job_status(
        session=db_session,
        job_id=failed_job.id,
        new_status=JobStatus.QUEUED,
    )

    assert result.status == JobStatus.QUEUED
    assert result.retry_count == 1


async def test_valid_transition_dispatched_to_queued_retry(
    db_session: AsyncSession, dispatched_job: JobDispatch
) -> None:
    """DISPATCHED -> QUEUED (retry) increments retry_count."""
    assert dispatched_job.retry_count == 0

    result = await update_job_status(
        session=db_session,
        job_id=dispatched_job.id,
        new_status=JobStatus.QUEUED,
    )

    assert result.status == JobStatus.QUEUED
    assert result.retry_count == 1


# ---------------------------------------------------------------------------
# Invalid transition tests
# ---------------------------------------------------------------------------


async def test_invalid_transition_completed_to_running(
    db_session: AsyncSession, completed_job: JobDispatch
) -> None:
    """COMPLETED -> RUNNING is invalid (terminal state)."""
    with pytest.raises(ValueError, match="Invalid transition"):
        await update_job_status(
            session=db_session,
            job_id=completed_job.id,
            new_status=JobStatus.RUNNING,
        )


async def test_invalid_transition_queued_to_completed(
    db_session: AsyncSession, queued_job: JobDispatch
) -> None:
    """QUEUED -> COMPLETED is invalid (must go through DISPATCHED, RUNNING)."""
    with pytest.raises(ValueError, match="Invalid transition"):
        await update_job_status(
            session=db_session,
            job_id=queued_job.id,
            new_status=JobStatus.COMPLETED,
        )


async def test_invalid_transition_queued_to_running(
    db_session: AsyncSession, queued_job: JobDispatch
) -> None:
    """QUEUED -> RUNNING is invalid (must be dispatched first)."""
    with pytest.raises(ValueError, match="Invalid transition"):
        await update_job_status(
            session=db_session,
            job_id=queued_job.id,
            new_status=JobStatus.RUNNING,
        )


async def test_update_job_not_found(db_session: AsyncSession) -> None:
    """Raises ValueError for a non-existent job ID."""
    fake_id = uuid.uuid4()
    with pytest.raises(ValueError, match="Job not found"):
        await update_job_status(
            session=db_session,
            job_id=fake_id,
            new_status=JobStatus.DISPATCHED,
        )


# ---------------------------------------------------------------------------
# Timestamp auto-set tests
# ---------------------------------------------------------------------------


async def test_dispatched_sets_timestamp(
    db_session: AsyncSession, queued_job: JobDispatch
) -> None:
    """Transitioning to DISPATCHED auto-sets dispatched_at."""
    assert queued_job.dispatched_at is None

    result = await update_job_status(
        session=db_session,
        job_id=queued_job.id,
        new_status=JobStatus.DISPATCHED,
    )

    assert result.dispatched_at is not None


# ---------------------------------------------------------------------------
# get_job tests
# ---------------------------------------------------------------------------


async def test_get_job_returns_job(
    db_session: AsyncSession, queued_job: JobDispatch
) -> None:
    """get_job returns the job with eager-loaded node."""
    result = await get_job(session=db_session, job_id=queued_job.id)

    assert result is not None
    assert result.id == queued_job.id
    assert result.node is not None
    assert result.node.name == "test-node-01"


async def test_get_job_not_found_returns_none(db_session: AsyncSession) -> None:
    """get_job returns None for a non-existent job ID."""
    result = await get_job(session=db_session, job_id=uuid.uuid4())
    assert result is None


# ---------------------------------------------------------------------------
# list_jobs tests
# ---------------------------------------------------------------------------


async def test_list_jobs_with_status_filter(
    db_session: AsyncSession,
    queued_job: JobDispatch,
    dispatched_job: JobDispatch,
    running_job: JobDispatch,
) -> None:
    """list_jobs filters by status correctly."""
    queued_jobs = await list_jobs(session=db_session, status=JobStatus.QUEUED)
    assert len(queued_jobs) >= 1
    assert all(j.status == JobStatus.QUEUED for j in queued_jobs)

    dispatched_jobs = await list_jobs(session=db_session, status=JobStatus.DISPATCHED)
    assert len(dispatched_jobs) >= 1
    assert all(j.status == JobStatus.DISPATCHED for j in dispatched_jobs)


async def test_list_jobs_returns_all_when_no_filter(
    db_session: AsyncSession,
    queued_job: JobDispatch,
    dispatched_job: JobDispatch,
) -> None:
    """list_jobs returns all jobs when no status filter is applied."""
    all_jobs = await list_jobs(session=db_session)
    assert len(all_jobs) >= 2


# ---------------------------------------------------------------------------
# cancel_job tests
# ---------------------------------------------------------------------------


async def test_cancel_queued_job(
    db_session: AsyncSession, queued_job: JobDispatch
) -> None:
    """Cancelling a QUEUED job sets status=FAILED with cancellation message."""
    result = await cancel_job(session=db_session, job_id=queued_job.id)

    assert result.status == JobStatus.FAILED
    assert result.completed_at is not None
    assert result.error_message == "Cancelled by user"


async def test_cancel_dispatched_job(
    db_session: AsyncSession, dispatched_job: JobDispatch
) -> None:
    """Cancelling a DISPATCHED job sets status=FAILED with cancellation message."""
    result = await cancel_job(session=db_session, job_id=dispatched_job.id)

    assert result.status == JobStatus.FAILED
    assert result.completed_at is not None
    assert result.error_message == "Cancelled by user"


async def test_cancel_running_job_raises(
    db_session: AsyncSession, running_job: JobDispatch
) -> None:
    """Cannot cancel a RUNNING job -- raises ValueError."""
    with pytest.raises(ValueError, match="Cannot cancel job in RUNNING state"):
        await cancel_job(session=db_session, job_id=running_job.id)


async def test_cancel_completed_job_raises(
    db_session: AsyncSession, completed_job: JobDispatch
) -> None:
    """Cannot cancel a COMPLETED job -- raises ValueError."""
    with pytest.raises(ValueError, match="Cannot cancel job in COMPLETED state"):
        await cancel_job(session=db_session, job_id=completed_job.id)
