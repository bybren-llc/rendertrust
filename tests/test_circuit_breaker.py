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

"""Tests for the circuit breaker node failure detection service.

Covers:
- record_failure increments failure count
- record_failure trips to UNHEALTHY at threshold
- record_failure below threshold keeps HEALTHY
- record_success resets counter
- record_success after trip restores HEALTHY
- check_node_health returns HEALTHY for healthy node
- check_node_health returns UNHEALTHY within recovery timeout
- check_node_health returns half-open (HEALTHY) after recovery timeout
- redistribute_jobs moves QUEUED jobs
- redistribute_jobs moves DISPATCHED jobs
- redistribute_jobs returns correct count
- redistribute_jobs skips RUNNING/COMPLETED/FAILED jobs
- reset clears failure state
- Logging on state transitions
- Integration: failure -> trip -> redistribute -> recovery flow
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from core.scheduler.circuit_breaker import (
    FAILURE_THRESHOLD,
    RECOVERY_TIMEOUT,
    CircuitBreaker,
)
from core.scheduler.models import EdgeNode, JobDispatch, JobStatus, NodeStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cb() -> CircuitBreaker:
    """Return a fresh CircuitBreaker instance for each test."""
    return CircuitBreaker()


@pytest.fixture
async def healthy_node(db_session: AsyncSession) -> EdgeNode:
    """Create a HEALTHY edge node."""
    node = EdgeNode(
        name="cb-test-node-01",
        public_key="cb-test-public-key-01",
        capabilities=["render", "inference"],
        status=NodeStatus.HEALTHY,
        current_load=0.1,
    )
    db_session.add(node)
    await db_session.flush()
    return node


@pytest.fixture
async def unhealthy_node(db_session: AsyncSession) -> EdgeNode:
    """Create an UNHEALTHY edge node."""
    node = EdgeNode(
        name="cb-test-node-02",
        public_key="cb-test-public-key-02",
        capabilities=["render"],
        status=NodeStatus.UNHEALTHY,
        current_load=0.0,
    )
    db_session.add(node)
    await db_session.flush()
    return node


@pytest.fixture
async def queued_job_on_node(
    db_session: AsyncSession, healthy_node: EdgeNode
) -> JobDispatch:
    """Create a QUEUED job assigned to the healthy node."""
    job = JobDispatch(
        node_id=healthy_node.id,
        job_type="render",
        payload_ref="s3://bucket/cb-payload-001.zip",
        status=JobStatus.QUEUED,
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.fixture
async def dispatched_job_on_node(
    db_session: AsyncSession, healthy_node: EdgeNode
) -> JobDispatch:
    """Create a DISPATCHED job assigned to the healthy node."""
    job = JobDispatch(
        node_id=healthy_node.id,
        job_type="render",
        payload_ref="s3://bucket/cb-payload-002.zip",
        status=JobStatus.DISPATCHED,
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.fixture
async def running_job_on_node(
    db_session: AsyncSession, healthy_node: EdgeNode
) -> JobDispatch:
    """Create a RUNNING job assigned to the healthy node."""
    job = JobDispatch(
        node_id=healthy_node.id,
        job_type="inference",
        payload_ref="s3://bucket/cb-payload-003.zip",
        status=JobStatus.RUNNING,
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.fixture
async def completed_job_on_node(
    db_session: AsyncSession, healthy_node: EdgeNode
) -> JobDispatch:
    """Create a COMPLETED job assigned to the healthy node."""
    job = JobDispatch(
        node_id=healthy_node.id,
        job_type="render",
        payload_ref="s3://bucket/cb-payload-004.zip",
        status=JobStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.fixture
async def failed_job_on_node(
    db_session: AsyncSession, healthy_node: EdgeNode
) -> JobDispatch:
    """Create a FAILED job assigned to the healthy node."""
    job = JobDispatch(
        node_id=healthy_node.id,
        job_type="render",
        payload_ref="s3://bucket/cb-payload-005.zip",
        status=JobStatus.FAILED,
    )
    db_session.add(job)
    await db_session.flush()
    return job


# ---------------------------------------------------------------------------
# record_failure tests
# ---------------------------------------------------------------------------


async def test_record_failure_increments_count(
    db_session: AsyncSession, healthy_node: EdgeNode, cb: CircuitBreaker
) -> None:
    """record_failure increments the internal failure counter."""
    await cb.record_failure(db_session, healthy_node.id)
    assert cb._failure_counts[healthy_node.id] == 1

    await cb.record_failure(db_session, healthy_node.id)
    assert cb._failure_counts[healthy_node.id] == 2


async def test_record_failure_below_threshold_returns_healthy(
    db_session: AsyncSession, healthy_node: EdgeNode, cb: CircuitBreaker
) -> None:
    """record_failure below FAILURE_THRESHOLD returns HEALTHY."""
    for _ in range(FAILURE_THRESHOLD - 1):
        status = await cb.record_failure(db_session, healthy_node.id)

    assert status == NodeStatus.HEALTHY
    assert cb._failure_counts[healthy_node.id] == FAILURE_THRESHOLD - 1


async def test_record_failure_trips_to_unhealthy_at_threshold(
    db_session: AsyncSession, healthy_node: EdgeNode, cb: CircuitBreaker
) -> None:
    """record_failure trips circuit to UNHEALTHY when reaching FAILURE_THRESHOLD."""
    for _ in range(FAILURE_THRESHOLD - 1):
        await cb.record_failure(db_session, healthy_node.id)

    # The threshold-reaching failure should trip the breaker
    status = await cb.record_failure(db_session, healthy_node.id)

    assert status == NodeStatus.UNHEALTHY
    assert cb._failure_counts[healthy_node.id] == FAILURE_THRESHOLD

    # Verify node is UNHEALTHY in the database
    await db_session.refresh(healthy_node)
    assert healthy_node.status == NodeStatus.UNHEALTHY


async def test_record_failure_updates_last_failure_time(
    db_session: AsyncSession, healthy_node: EdgeNode, cb: CircuitBreaker
) -> None:
    """record_failure updates the last failure timestamp."""
    await cb.record_failure(db_session, healthy_node.id)

    assert healthy_node.id in cb._last_failure_time
    last_time = cb._last_failure_time[healthy_node.id]
    assert isinstance(last_time, datetime.datetime)
    assert last_time.tzinfo is not None


# ---------------------------------------------------------------------------
# record_success tests
# ---------------------------------------------------------------------------


async def test_record_success_resets_counter(
    db_session: AsyncSession, healthy_node: EdgeNode, cb: CircuitBreaker
) -> None:
    """record_success resets the failure counter to zero."""
    # Accumulate some failures
    await cb.record_failure(db_session, healthy_node.id)
    await cb.record_failure(db_session, healthy_node.id)
    assert cb._failure_counts[healthy_node.id] == 2

    await cb.record_success(db_session, healthy_node.id)

    assert healthy_node.id not in cb._failure_counts
    assert healthy_node.id not in cb._last_failure_time


async def test_record_success_after_trip_restores_healthy(
    db_session: AsyncSession, healthy_node: EdgeNode, cb: CircuitBreaker
) -> None:
    """record_success after tripping restores the node to HEALTHY."""
    # Trip the breaker
    for _ in range(FAILURE_THRESHOLD):
        await cb.record_failure(db_session, healthy_node.id)

    await db_session.refresh(healthy_node)
    assert healthy_node.status == NodeStatus.UNHEALTHY

    # Record a success (simulating a half-open probe succeeding)
    await cb.record_success(db_session, healthy_node.id)

    await db_session.refresh(healthy_node)
    assert healthy_node.status == NodeStatus.HEALTHY
    assert healthy_node.id not in cb._failure_counts


async def test_record_success_clears_half_open(
    db_session: AsyncSession, healthy_node: EdgeNode, cb: CircuitBreaker
) -> None:
    """record_success clears the half-open flag."""
    cb._half_open.add(healthy_node.id)
    await cb.record_success(db_session, healthy_node.id)

    assert healthy_node.id not in cb._half_open


# ---------------------------------------------------------------------------
# check_node_health tests
# ---------------------------------------------------------------------------


async def test_check_node_health_returns_healthy_for_healthy_node(
    db_session: AsyncSession, healthy_node: EdgeNode, cb: CircuitBreaker
) -> None:
    """check_node_health returns HEALTHY for a node in HEALTHY status."""
    status = await cb.check_node_health(db_session, healthy_node.id)
    assert status == NodeStatus.HEALTHY


async def test_check_node_health_returns_unhealthy_within_timeout(
    db_session: AsyncSession, unhealthy_node: EdgeNode, cb: CircuitBreaker
) -> None:
    """check_node_health returns UNHEALTHY when within recovery timeout."""
    # Set a recent failure time
    cb._last_failure_time[unhealthy_node.id] = datetime.datetime.now(tz=datetime.UTC)

    status = await cb.check_node_health(db_session, unhealthy_node.id)
    assert status == NodeStatus.UNHEALTHY


async def test_check_node_health_returns_healthy_after_recovery_timeout(
    db_session: AsyncSession, unhealthy_node: EdgeNode, cb: CircuitBreaker
) -> None:
    """check_node_health returns HEALTHY (half-open) after recovery timeout."""
    # Set a failure time far enough in the past
    past = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(
        seconds=RECOVERY_TIMEOUT + 10
    )
    cb._last_failure_time[unhealthy_node.id] = past

    status = await cb.check_node_health(db_session, unhealthy_node.id)
    assert status == NodeStatus.HEALTHY
    assert unhealthy_node.id in cb._half_open


async def test_check_node_health_unhealthy_no_tracked_failure(
    db_session: AsyncSession, unhealthy_node: EdgeNode, cb: CircuitBreaker
) -> None:
    """check_node_health returns UNHEALTHY when no failure time is tracked."""
    # No entry in _last_failure_time (e.g., server restart)
    status = await cb.check_node_health(db_session, unhealthy_node.id)
    assert status == NodeStatus.UNHEALTHY


# ---------------------------------------------------------------------------
# redistribute_jobs tests
# ---------------------------------------------------------------------------


async def test_redistribute_moves_queued_jobs(
    db_session: AsyncSession,
    healthy_node: EdgeNode,
    queued_job_on_node: JobDispatch,
    cb: CircuitBreaker,
) -> None:
    """redistribute_jobs transitions QUEUED jobs back to QUEUED (resetting dispatched_at)."""
    count = await cb.redistribute_jobs(db_session, healthy_node.id)

    assert count == 1
    await db_session.refresh(queued_job_on_node)
    assert queued_job_on_node.status == JobStatus.QUEUED
    assert queued_job_on_node.dispatched_at is None


async def test_redistribute_moves_dispatched_jobs(
    db_session: AsyncSession,
    healthy_node: EdgeNode,
    dispatched_job_on_node: JobDispatch,
    cb: CircuitBreaker,
) -> None:
    """redistribute_jobs transitions DISPATCHED jobs to QUEUED."""
    count = await cb.redistribute_jobs(db_session, healthy_node.id)

    assert count == 1
    await db_session.refresh(dispatched_job_on_node)
    assert dispatched_job_on_node.status == JobStatus.QUEUED
    assert dispatched_job_on_node.dispatched_at is None


async def test_redistribute_returns_correct_count(
    db_session: AsyncSession,
    healthy_node: EdgeNode,
    queued_job_on_node: JobDispatch,
    dispatched_job_on_node: JobDispatch,
    cb: CircuitBreaker,
) -> None:
    """redistribute_jobs returns the total count of redistributed jobs."""
    count = await cb.redistribute_jobs(db_session, healthy_node.id)
    assert count == 2


async def test_redistribute_skips_running_completed_failed(
    db_session: AsyncSession,
    healthy_node: EdgeNode,
    running_job_on_node: JobDispatch,
    completed_job_on_node: JobDispatch,
    failed_job_on_node: JobDispatch,
    cb: CircuitBreaker,
) -> None:
    """redistribute_jobs does NOT touch RUNNING, COMPLETED, or FAILED jobs."""
    count = await cb.redistribute_jobs(db_session, healthy_node.id)

    assert count == 0

    await db_session.refresh(running_job_on_node)
    await db_session.refresh(completed_job_on_node)
    await db_session.refresh(failed_job_on_node)

    assert running_job_on_node.status == JobStatus.RUNNING
    assert completed_job_on_node.status == JobStatus.COMPLETED
    assert failed_job_on_node.status == JobStatus.FAILED


# ---------------------------------------------------------------------------
# reset tests
# ---------------------------------------------------------------------------


async def test_reset_clears_failure_state(
    db_session: AsyncSession, healthy_node: EdgeNode, cb: CircuitBreaker
) -> None:
    """reset() clears all tracking state for the given node."""
    # Accumulate state
    await cb.record_failure(db_session, healthy_node.id)
    await cb.record_failure(db_session, healthy_node.id)
    cb._half_open.add(healthy_node.id)

    assert healthy_node.id in cb._failure_counts
    assert healthy_node.id in cb._last_failure_time
    assert healthy_node.id in cb._half_open

    cb.reset(healthy_node.id)

    assert healthy_node.id not in cb._failure_counts
    assert healthy_node.id not in cb._last_failure_time
    assert healthy_node.id not in cb._half_open


# ---------------------------------------------------------------------------
# Logging tests
# ---------------------------------------------------------------------------


async def test_logging_on_trip(
    db_session: AsyncSession, healthy_node: EdgeNode, cb: CircuitBreaker
) -> None:
    """Circuit breaker logs a warning when tripping to UNHEALTHY."""
    with patch("core.scheduler.circuit_breaker.logger") as mock_logger:
        for _ in range(FAILURE_THRESHOLD):
            await cb.record_failure(db_session, healthy_node.id)

        # Verify the "tripped" warning was logged
        mock_logger.warning.assert_called()
        call_args = mock_logger.warning.call_args
        assert call_args[0][0] == "circuit_breaker_tripped"


async def test_logging_on_recovery(
    db_session: AsyncSession, healthy_node: EdgeNode, cb: CircuitBreaker
) -> None:
    """Circuit breaker logs info when a node recovers via record_success."""
    # Accumulate a failure first so reset is noteworthy
    await cb.record_failure(db_session, healthy_node.id)

    with patch("core.scheduler.circuit_breaker.logger") as mock_logger:
        await cb.record_success(db_session, healthy_node.id)

        mock_logger.info.assert_called()
        logged_events = [call[0][0] for call in mock_logger.info.call_args_list]
        assert "circuit_breaker_reset" in logged_events


# ---------------------------------------------------------------------------
# Integration: full lifecycle test
# ---------------------------------------------------------------------------


async def test_full_lifecycle_failure_trip_redistribute_recovery(
    db_session: AsyncSession,
    healthy_node: EdgeNode,
    queued_job_on_node: JobDispatch,
    dispatched_job_on_node: JobDispatch,
    running_job_on_node: JobDispatch,
    cb: CircuitBreaker,
) -> None:
    """End-to-end: failures trip the breaker, jobs redistribute, probe recovers."""
    # Phase 1: Accumulate failures up to threshold
    for _i in range(FAILURE_THRESHOLD - 1):
        status = await cb.record_failure(db_session, healthy_node.id)
        assert status == NodeStatus.HEALTHY

    # Phase 2: The threshold failure trips the breaker
    status = await cb.record_failure(db_session, healthy_node.id)
    assert status == NodeStatus.UNHEALTHY

    # Verify node is UNHEALTHY
    await db_session.refresh(healthy_node)
    assert healthy_node.status == NodeStatus.UNHEALTHY

    # Verify QUEUED and DISPATCHED jobs were redistributed
    await db_session.refresh(queued_job_on_node)
    await db_session.refresh(dispatched_job_on_node)
    await db_session.refresh(running_job_on_node)

    assert queued_job_on_node.status == JobStatus.QUEUED
    assert dispatched_job_on_node.status == JobStatus.QUEUED
    assert running_job_on_node.status == JobStatus.RUNNING  # untouched

    # Phase 3: Check health within recovery timeout -- still UNHEALTHY
    health = await cb.check_node_health(db_session, healthy_node.id)
    assert health == NodeStatus.UNHEALTHY

    # Phase 4: Simulate recovery timeout elapsed
    past = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(
        seconds=RECOVERY_TIMEOUT + 1
    )
    cb._last_failure_time[healthy_node.id] = past

    health = await cb.check_node_health(db_session, healthy_node.id)
    assert health == NodeStatus.HEALTHY  # half-open
    assert healthy_node.id in cb._half_open

    # Phase 5: Probe success restores the node
    await cb.record_success(db_session, healthy_node.id)

    await db_session.refresh(healthy_node)
    assert healthy_node.status == NodeStatus.HEALTHY
    assert healthy_node.id not in cb._failure_counts
    assert healthy_node.id not in cb._half_open
