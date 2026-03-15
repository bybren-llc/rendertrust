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

"""Tests for the job retry service and dead letter queue.

Covers:
- should_retry logic for retry counts 0-3+
- calculate_backoff exponential values
- schedule_retry transitions and retry count increment
- schedule_retry calls move_to_dlq when max retries exceeded
- schedule_retry attempts different node on retry
- move_to_dlq creates DeadLetterEntry with error history
- move_to_dlq marks job as permanently FAILED
- DeadLetterEntry model field validation
- Error history JSON accumulation across failures
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_fake")

from typing import TYPE_CHECKING

import pytest

from core.scheduler.models import (
    DeadLetterEntry,
    EdgeNode,
    JobDispatch,
    JobStatus,
    NodeStatus,
)
from core.scheduler.retry import (
    BACKOFF_BASE,
    MAX_RETRIES,
    calculate_backoff,
    move_to_dlq,
    schedule_retry,
    should_retry,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def edge_node(db_session: AsyncSession) -> EdgeNode:
    """Create a healthy edge node for retry tests."""
    node = EdgeNode(
        name="retry-node-01",
        public_key="test-public-key-for-retry-service",
        capabilities=["render", "inference"],
        status=NodeStatus.HEALTHY,
        current_load=0.1,
    )
    db_session.add(node)
    await db_session.flush()
    return node


@pytest.fixture
async def second_node(db_session: AsyncSession) -> EdgeNode:
    """Create a second healthy node for testing node switching on retry."""
    node = EdgeNode(
        name="retry-node-02",
        public_key="test-public-key-for-retry-service-2",
        capabilities=["render", "inference"],
        status=NodeStatus.HEALTHY,
        current_load=0.05,
    )
    db_session.add(node)
    await db_session.flush()
    return node


@pytest.fixture
async def failed_job(db_session: AsyncSession, edge_node: EdgeNode) -> JobDispatch:
    """Create a job in FAILED status with retry_count=0."""
    job = JobDispatch(
        node_id=edge_node.id,
        job_type="render",
        payload_ref="s3://bucket/payload-retry-001.zip",
        status=JobStatus.FAILED,
        error_message="Initial failure",
        retry_count=0,
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.fixture
async def failed_job_max_retries(db_session: AsyncSession, edge_node: EdgeNode) -> JobDispatch:
    """Create a job in FAILED status that has exhausted retries."""
    job = JobDispatch(
        node_id=edge_node.id,
        job_type="render",
        payload_ref="s3://bucket/payload-retry-max.zip",
        status=JobStatus.FAILED,
        error_message="Previous error",
        retry_count=MAX_RETRIES,
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.fixture
async def running_job(db_session: AsyncSession, edge_node: EdgeNode) -> JobDispatch:
    """Create a job in RUNNING status for testing non-FAILED schedule_retry."""
    job = JobDispatch(
        node_id=edge_node.id,
        job_type="render",
        payload_ref="s3://bucket/payload-running.zip",
        status=JobStatus.RUNNING,
        retry_count=0,
    )
    db_session.add(job)
    await db_session.flush()
    return job


# ---------------------------------------------------------------------------
# should_retry tests
# ---------------------------------------------------------------------------


async def test_should_retry_count_zero(db_session: AsyncSession, edge_node: EdgeNode) -> None:
    """should_retry returns True when retry_count is 0."""
    job = JobDispatch(
        node_id=edge_node.id,
        job_type="render",
        payload_ref="s3://test",
        status=JobStatus.FAILED,
        retry_count=0,
    )
    assert should_retry(job) is True


async def test_should_retry_count_one(db_session: AsyncSession, edge_node: EdgeNode) -> None:
    """should_retry returns True when retry_count is 1."""
    job = JobDispatch(
        node_id=edge_node.id,
        job_type="render",
        payload_ref="s3://test",
        status=JobStatus.FAILED,
        retry_count=1,
    )
    assert should_retry(job) is True


async def test_should_retry_count_two(db_session: AsyncSession, edge_node: EdgeNode) -> None:
    """should_retry returns True when retry_count is 2."""
    job = JobDispatch(
        node_id=edge_node.id,
        job_type="render",
        payload_ref="s3://test",
        status=JobStatus.FAILED,
        retry_count=2,
    )
    assert should_retry(job) is True


async def test_should_retry_count_at_max(db_session: AsyncSession, edge_node: EdgeNode) -> None:
    """should_retry returns False when retry_count equals MAX_RETRIES."""
    job = JobDispatch(
        node_id=edge_node.id,
        job_type="render",
        payload_ref="s3://test",
        status=JobStatus.FAILED,
        retry_count=MAX_RETRIES,
    )
    assert should_retry(job) is False


async def test_should_retry_count_above_max(db_session: AsyncSession, edge_node: EdgeNode) -> None:
    """should_retry returns False when retry_count exceeds MAX_RETRIES."""
    job = JobDispatch(
        node_id=edge_node.id,
        job_type="render",
        payload_ref="s3://test",
        status=JobStatus.FAILED,
        retry_count=MAX_RETRIES + 1,
    )
    assert should_retry(job) is False


# ---------------------------------------------------------------------------
# calculate_backoff tests
# ---------------------------------------------------------------------------


async def test_backoff_retry_zero() -> None:
    """Backoff for retry 0 is 2^0 = 1 second."""
    assert calculate_backoff(0) == pytest.approx(1.0)


async def test_backoff_retry_one() -> None:
    """Backoff for retry 1 is 2^1 = 2 seconds."""
    assert calculate_backoff(1) == pytest.approx(2.0)


async def test_backoff_retry_two() -> None:
    """Backoff for retry 2 is 2^2 = 4 seconds."""
    assert calculate_backoff(2) == pytest.approx(4.0)


async def test_backoff_uses_base() -> None:
    """Backoff uses BACKOFF_BASE constant."""
    for i in range(5):
        expected = BACKOFF_BASE**i
        assert calculate_backoff(i) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# schedule_retry tests
# ---------------------------------------------------------------------------


async def test_schedule_retry_increments_retry_count(
    db_session: AsyncSession, failed_job: JobDispatch
) -> None:
    """schedule_retry increments retry_count when retrying."""
    original_count = failed_job.retry_count
    result = await schedule_retry(db_session, failed_job, "Retry error")

    assert isinstance(result, JobDispatch)
    assert result.retry_count == original_count + 1


async def test_schedule_retry_transitions_to_queued(
    db_session: AsyncSession, failed_job: JobDispatch
) -> None:
    """schedule_retry transitions job to QUEUED status."""
    result = await schedule_retry(db_session, failed_job, "Retry error")

    assert isinstance(result, JobDispatch)
    assert result.status == JobStatus.QUEUED


async def test_schedule_retry_calls_move_to_dlq_at_max(
    db_session: AsyncSession, failed_job_max_retries: JobDispatch
) -> None:
    """schedule_retry moves job to DLQ when max retries exceeded."""
    result = await schedule_retry(db_session, failed_job_max_retries, "Final failure")

    assert isinstance(result, DeadLetterEntry)
    assert result.job_id == failed_job_max_retries.id


async def test_schedule_retry_attempts_different_node(
    db_session: AsyncSession,
    edge_node: EdgeNode,
    second_node: EdgeNode,
    failed_job: JobDispatch,
) -> None:
    """schedule_retry attempts to dispatch to a different (least-loaded) node."""
    # second_node has lower load (0.05) than edge_node (0.1),
    # so find_best_node should pick second_node
    result = await schedule_retry(db_session, failed_job, "Node failure")

    assert isinstance(result, JobDispatch)
    # The job should be reassigned to second_node (lower load)
    assert result.node_id == second_node.id


async def test_schedule_retry_from_running_state(
    db_session: AsyncSession, running_job: JobDispatch
) -> None:
    """schedule_retry handles jobs that are in RUNNING state (transitions through FAILED)."""
    result = await schedule_retry(db_session, running_job, "Crash during execution")

    assert isinstance(result, JobDispatch)
    assert result.status == JobStatus.QUEUED
    assert result.retry_count == 1


# ---------------------------------------------------------------------------
# move_to_dlq tests
# ---------------------------------------------------------------------------


async def test_move_to_dlq_creates_entry(
    db_session: AsyncSession, failed_job_max_retries: JobDispatch
) -> None:
    """move_to_dlq creates a DeadLetterEntry record."""
    entry = await move_to_dlq(db_session, failed_job_max_retries, "Permanent failure")

    assert isinstance(entry, DeadLetterEntry)
    assert entry.id is not None
    assert entry.job_id == failed_job_max_retries.id


async def test_move_to_dlq_records_original_payload(
    db_session: AsyncSession, failed_job_max_retries: JobDispatch
) -> None:
    """move_to_dlq preserves the original payload reference."""
    entry = await move_to_dlq(db_session, failed_job_max_retries, "Permanent failure")

    assert entry.original_payload == failed_job_max_retries.payload_ref


async def test_move_to_dlq_error_history_contains_messages(
    db_session: AsyncSession, failed_job_max_retries: JobDispatch
) -> None:
    """move_to_dlq creates error_history with failure messages."""
    entry = await move_to_dlq(db_session, failed_job_max_retries, "Final OOM error")

    assert isinstance(entry.error_history, list)
    assert len(entry.error_history) > 0
    assert "Final OOM error" in entry.error_history


async def test_move_to_dlq_includes_previous_error(
    db_session: AsyncSession, failed_job_max_retries: JobDispatch
) -> None:
    """move_to_dlq includes previous error_message in error_history."""
    # failed_job_max_retries has error_message="Previous error"
    entry = await move_to_dlq(db_session, failed_job_max_retries, "Final error")

    assert "Previous error" in entry.error_history
    assert "Final error" in entry.error_history


async def test_move_to_dlq_sets_job_permanently_failed(
    db_session: AsyncSession, failed_job_max_retries: JobDispatch
) -> None:
    """move_to_dlq ensures the job remains in FAILED status."""
    await move_to_dlq(db_session, failed_job_max_retries, "Permanent failure")

    assert failed_job_max_retries.status == JobStatus.FAILED


async def test_move_to_dlq_records_retry_count(
    db_session: AsyncSession, failed_job_max_retries: JobDispatch
) -> None:
    """move_to_dlq records the final retry_count."""
    entry = await move_to_dlq(db_session, failed_job_max_retries, "Permanent failure")

    assert entry.retry_count == MAX_RETRIES


async def test_move_to_dlq_sets_failed_at(
    db_session: AsyncSession, failed_job_max_retries: JobDispatch
) -> None:
    """move_to_dlq sets a valid failed_at timestamp."""
    entry = await move_to_dlq(db_session, failed_job_max_retries, "Permanent failure")

    assert entry.failed_at is not None


# ---------------------------------------------------------------------------
# DeadLetterEntry model tests
# ---------------------------------------------------------------------------


async def test_dlq_entry_model_repr(
    db_session: AsyncSession, failed_job_max_retries: JobDispatch
) -> None:
    """DeadLetterEntry __repr__ returns a useful string."""
    entry = await move_to_dlq(db_session, failed_job_max_retries, "Test repr")

    repr_str = repr(entry)
    assert "DeadLetterEntry" in repr_str
    assert str(entry.job_id) in repr_str


# ---------------------------------------------------------------------------
# MAX_RETRIES constant test
# ---------------------------------------------------------------------------


async def test_max_retries_is_three() -> None:
    """MAX_RETRIES constant is set to 3."""
    assert MAX_RETRIES == 3
