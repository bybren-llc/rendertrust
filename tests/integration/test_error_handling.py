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

"""Integration tests for error handling, retry, and circuit breaker interactions.

Covers the interaction between the retry service, circuit breaker, usage
tracking, and payout services:

1.  Retry -> DLQ flow: Job fails 3 times, then moves to DLQ
2.  Retry -> success flow: Job fails once, retries, succeeds on 2nd attempt
3.  Circuit breaker -> retry interaction: 3 failures trip node UNHEALTHY,
    retry dispatches to a different node
4.  Circuit breaker -> redistribute: Node goes UNHEALTHY, queued jobs
    are redistributed
5.  Circuit breaker recovery: UNHEALTHY -> half-open -> success -> HEALTHY
6.  Usage deduction on completion: Credits deducted via usage service
7.  Usage deduction on retry success: Only ONE deduction (not per attempt)
8.  Insufficient credits blocks dispatch pre-flight
9.  DLQ entry contains full error history
10. Backoff values are correct (exponential: 1s, 2s, 4s)
11. Payout includes only successful jobs
12. Circuit breaker reset on success: Failure counter resets

[REN-109]
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from core.billing.payout import OPERATOR_SHARE, PayoutSummary, calculate_earnings
from core.billing.usage import (
    DEFAULT_PRICING,
    check_sufficient_credits,
    deduct_on_completion,
    get_job_price,
)
from core.ledger.service import allocate_credits
from core.models.base import TransactionSource
from core.scheduler.circuit_breaker import (
    FAILURE_THRESHOLD,
    RECOVERY_TIMEOUT,
    CircuitBreaker,
)
from core.scheduler.job_service import update_job_status
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

    from core.models.base import User


# ---------------------------------------------------------------------------
# Autouse: mock Redis queue push for all tests (no Redis server in tests).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_redis_queue():
    with patch("core.scheduler.dispatch.push_to_queue", new_callable=AsyncMock) as mock_push:
        mock_push.return_value = True
        yield mock_push


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(
    *,
    name: str = "err-test-node",
    status: NodeStatus = NodeStatus.HEALTHY,
    capabilities: list[str] | None = None,
    current_load: float = 0.0,
    public_key: str = "ed25519-err-test-key",
) -> EdgeNode:
    """Create an EdgeNode instance (not yet persisted)."""
    return EdgeNode(
        public_key=public_key,
        name=name,
        capabilities=capabilities or ["render"],
        status=status,
        current_load=current_load,
        last_heartbeat=datetime.datetime.now(tz=datetime.UTC),
    )


def _make_job(
    *,
    node: EdgeNode,
    job_type: str = "render",
    payload_ref: str = "s3://bucket/scene.blend",
    status: JobStatus = JobStatus.RUNNING,
    error_message: str | None = None,
    retry_count: int = 0,
) -> JobDispatch:
    """Create a JobDispatch instance (not yet persisted)."""
    now = datetime.datetime.now(tz=datetime.UTC)
    return JobDispatch(
        node_id=node.id,
        job_type=job_type,
        payload_ref=payload_ref,
        status=status,
        queued_at=now,
        dispatched_at=now if status != JobStatus.QUEUED else None,
        error_message=error_message,
        retry_count=retry_count,
    )


# =========================================================================
# 1. Retry -> DLQ flow
# =========================================================================


class TestRetryToDlqFlow:
    """Job fails (1 initial + MAX_RETRIES retries), then moves to DLQ."""

    async def test_job_exhausts_retries_and_moves_to_dlq(
        self,
        db_session: AsyncSession,
    ) -> None:
        """After initial failure + MAX_RETRIES retry failures, job goes to DLQ.

        The job lifecycle is: initial run fails -> schedule_retry (retry 1)
        -> fails again -> schedule_retry (retry 2) -> fails again ->
        schedule_retry (retry 3) -> fails again -> schedule_retry sees
        retry_count=3 == MAX_RETRIES -> moves to DLQ.
        """
        node = _make_node(name="dlq-node", public_key="key-dlq-flow")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.RUNNING, retry_count=0)
        db_session.add(job)
        await db_session.flush()

        errors = [
            "GPU OOM",
            "GPU driver crash",
            "Node unreachable",
            "Final failure",
        ]

        # --- Failure 1 (initial run): RUNNING -> FAILED, schedule_retry re-queues ---
        await update_job_status(
            session=db_session,
            job_id=job.id,
            new_status=JobStatus.FAILED,
            error_message=errors[0],
        )
        await db_session.refresh(job)
        result1 = await schedule_retry(db_session, job, errors[0])
        assert isinstance(result1, JobDispatch)
        assert result1.retry_count == 1
        assert result1.status == JobStatus.QUEUED

        # --- Failure 2 (retry 1): QUEUED -> DISPATCHED -> RUNNING -> FAILED ---
        await update_job_status(session=db_session, job_id=job.id, new_status=JobStatus.DISPATCHED)
        await update_job_status(session=db_session, job_id=job.id, new_status=JobStatus.RUNNING)
        await update_job_status(
            session=db_session,
            job_id=job.id,
            new_status=JobStatus.FAILED,
            error_message=errors[1],
        )
        await db_session.refresh(job)
        result2 = await schedule_retry(db_session, job, errors[1])
        assert isinstance(result2, JobDispatch)
        assert result2.retry_count == 2

        # --- Failure 3 (retry 2): QUEUED -> DISPATCHED -> RUNNING -> FAILED ---
        await update_job_status(session=db_session, job_id=job.id, new_status=JobStatus.DISPATCHED)
        await update_job_status(session=db_session, job_id=job.id, new_status=JobStatus.RUNNING)
        await update_job_status(
            session=db_session,
            job_id=job.id,
            new_status=JobStatus.FAILED,
            error_message=errors[2],
        )
        await db_session.refresh(job)
        result3 = await schedule_retry(db_session, job, errors[2])
        assert isinstance(result3, JobDispatch)
        assert result3.retry_count == 3

        # --- Failure 4 (retry 3): QUEUED -> DISPATCHED -> RUNNING -> FAILED ---
        await update_job_status(session=db_session, job_id=job.id, new_status=JobStatus.DISPATCHED)
        await update_job_status(session=db_session, job_id=job.id, new_status=JobStatus.RUNNING)
        await update_job_status(
            session=db_session,
            job_id=job.id,
            new_status=JobStatus.FAILED,
            error_message=errors[3],
        )
        # Refresh to pick up retry_count=3 from DB
        await db_session.refresh(job)
        # retry_count is now 3 (== MAX_RETRIES), should_retry returns False
        assert job.retry_count == MAX_RETRIES
        assert not should_retry(job)
        result4 = await schedule_retry(db_session, job, errors[3])

        # Should now be a DLQ entry
        assert isinstance(result4, DeadLetterEntry)
        assert result4.job_id == job.id
        assert result4.retry_count == MAX_RETRIES


# =========================================================================
# 2. Retry -> success flow
# =========================================================================


class TestRetrySuccessFlow:
    """Job fails once, retries, and succeeds on the 2nd attempt."""

    async def test_job_fails_once_then_succeeds_on_retry(
        self,
        db_session: AsyncSession,
    ) -> None:
        """After one failure and retry, job can complete successfully."""
        node = _make_node(name="retry-ok", public_key="key-retry-ok")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.RUNNING)
        db_session.add(job)
        await db_session.flush()

        # First attempt fails
        await update_job_status(
            session=db_session,
            job_id=job.id,
            new_status=JobStatus.FAILED,
            error_message="Temporary GPU error",
        )
        retried = await schedule_retry(db_session, job, "Temporary GPU error")
        assert isinstance(retried, JobDispatch)
        assert retried.retry_count == 1
        assert retried.status == JobStatus.QUEUED

        # Second attempt succeeds
        await update_job_status(session=db_session, job_id=job.id, new_status=JobStatus.DISPATCHED)
        await update_job_status(session=db_session, job_id=job.id, new_status=JobStatus.RUNNING)
        completed = await update_job_status(
            session=db_session,
            job_id=job.id,
            new_status=JobStatus.COMPLETED,
            result_ref="s3://bucket/result.zip",
        )

        assert completed.status == JobStatus.COMPLETED
        assert completed.retry_count == 1
        assert completed.result_ref == "s3://bucket/result.zip"


# =========================================================================
# 3. Circuit breaker -> retry interaction
# =========================================================================


class TestCircuitBreakerRetryInteraction:
    """3 failures on same node trip UNHEALTHY; retry dispatches elsewhere."""

    async def test_failures_trip_breaker_and_retry_uses_different_node(
        self,
        db_session: AsyncSession,
    ) -> None:
        """After FAILURE_THRESHOLD failures, node is UNHEALTHY and
        schedule_retry attempts to find a different node."""
        cb = CircuitBreaker()

        node_a = _make_node(name="node-a-bad", public_key="key-cb-a")
        node_b = _make_node(name="node-b-good", public_key="key-cb-b", current_load=0.1)
        db_session.add_all([node_a, node_b])
        await db_session.flush()

        # Record FAILURE_THRESHOLD failures on node_a
        for _ in range(FAILURE_THRESHOLD):
            status = await cb.record_failure(db_session, node_a.id)

        assert status == NodeStatus.UNHEALTHY

        # Refresh node_a from session to see the DB update
        await db_session.refresh(node_a)
        assert node_a.status == NodeStatus.UNHEALTHY

        # Now create a job that was on node_a and needs retry
        job = _make_job(node=node_a, status=JobStatus.RUNNING)
        db_session.add(job)
        await db_session.flush()

        await update_job_status(
            session=db_session,
            job_id=job.id,
            new_status=JobStatus.FAILED,
            error_message="Node A is down",
        )

        # schedule_retry should find node_b (node_a is UNHEALTHY)
        retried = await schedule_retry(db_session, job, "Node A is down")
        assert isinstance(retried, JobDispatch)
        assert retried.status == JobStatus.QUEUED
        # The retry should have been reassigned to node_b
        assert retried.node_id == node_b.id


# =========================================================================
# 4. Circuit breaker -> redistribute
# =========================================================================


class TestCircuitBreakerRedistribute:
    """When a node goes UNHEALTHY, queued jobs are redistributed."""

    async def test_queued_jobs_redistributed_on_trip(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Queued and dispatched jobs on an unhealthy node are re-queued."""
        cb = CircuitBreaker()

        node = _make_node(name="redistribute-node", public_key="key-redist")
        db_session.add(node)
        await db_session.flush()

        # Create jobs in QUEUED and DISPATCHED states on the node
        job_queued = _make_job(node=node, status=JobStatus.QUEUED, payload_ref="s3://q1")
        job_dispatched = _make_job(node=node, status=JobStatus.DISPATCHED, payload_ref="s3://d1")
        # A running job should NOT be redistributed
        job_running = _make_job(node=node, status=JobStatus.RUNNING, payload_ref="s3://r1")
        db_session.add_all([job_queued, job_dispatched, job_running])
        await db_session.flush()

        # Trip the breaker
        for _ in range(FAILURE_THRESHOLD):
            await cb.record_failure(db_session, node.id)

        # Refresh jobs to see redistributed state
        await db_session.refresh(job_queued)
        await db_session.refresh(job_dispatched)
        await db_session.refresh(job_running)

        # Both queued and dispatched should now be QUEUED
        assert job_queued.status == JobStatus.QUEUED
        assert job_dispatched.status == JobStatus.QUEUED
        assert job_dispatched.dispatched_at is None

        # Running job should be untouched
        assert job_running.status == JobStatus.RUNNING


# =========================================================================
# 5. Circuit breaker recovery
# =========================================================================


class TestCircuitBreakerRecovery:
    """Node transitions: UNHEALTHY -> half-open -> HEALTHY on success."""

    async def test_unhealthy_node_recovers_after_timeout_and_success(
        self,
        db_session: AsyncSession,
    ) -> None:
        """After RECOVERY_TIMEOUT, check_node_health returns HEALTHY
        (half-open). A subsequent record_success restores the node."""
        cb = CircuitBreaker()

        node = _make_node(name="recovery-node", public_key="key-recovery")
        db_session.add(node)
        await db_session.flush()

        # Trip the breaker
        for _ in range(FAILURE_THRESHOLD):
            await cb.record_failure(db_session, node.id)

        await db_session.refresh(node)
        assert node.status == NodeStatus.UNHEALTHY

        # Simulate RECOVERY_TIMEOUT elapsed by backdating the last failure
        cb._last_failure_time[node.id] = datetime.datetime.now(
            tz=datetime.UTC
        ) - datetime.timedelta(seconds=RECOVERY_TIMEOUT + 1)

        # check_node_health should now return HEALTHY (half-open probe)
        effective = await cb.check_node_health(db_session, node.id)
        assert effective == NodeStatus.HEALTHY
        assert node.id in cb._half_open

        # Simulate a successful probe
        await cb.record_success(db_session, node.id)

        # Node should be back to HEALTHY
        await db_session.refresh(node)
        assert node.status == NodeStatus.HEALTHY
        assert node.id not in cb._half_open
        assert cb._failure_counts.get(node.id) is None


# =========================================================================
# 6. Usage deduction on completion
# =========================================================================


class TestUsageDeductionOnCompletion:
    """Job completes and credits are deducted via usage service."""

    async def test_credits_deducted_on_job_completion(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Completing a job triggers a credit deduction equal to the job price."""
        # Seed user with credits
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("100.0"),
            source=TransactionSource.STRIPE,
            reference_id="seed-usage-test",
            description="Seed credits for test",
        )

        node = _make_node(name="usage-node", public_key="key-usage")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.COMPLETED, job_type="render")
        db_session.add(job)
        await db_session.flush()

        # Deduct on completion
        entry = await deduct_on_completion(db_session, job, test_user.id)

        # Render jobs cost 10.0 credits by default
        expected_cost = DEFAULT_PRICING["render"]
        assert entry.amount == expected_cost
        assert entry.balance_after == Decimal("100.0") - expected_cost


# =========================================================================
# 7. Usage deduction on retry success (single deduction)
# =========================================================================


class TestUsageDeductionOnRetrySuccess:
    """Job fails once, retries, succeeds -- only ONE deduction occurs."""

    async def test_only_one_deduction_after_retry_success(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Even after a retry, deduct_on_completion is idempotent per job_id."""
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("100.0"),
            source=TransactionSource.STRIPE,
            reference_id="seed-retry-deduct",
        )

        node = _make_node(name="retry-deduct", public_key="key-retry-deduct")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.RUNNING, retry_count=0)
        db_session.add(job)
        await db_session.flush()

        # First attempt fails
        await update_job_status(
            session=db_session,
            job_id=job.id,
            new_status=JobStatus.FAILED,
            error_message="Temporary error",
        )
        await schedule_retry(db_session, job, "Temporary error")

        # Second attempt succeeds
        await update_job_status(session=db_session, job_id=job.id, new_status=JobStatus.DISPATCHED)
        await update_job_status(session=db_session, job_id=job.id, new_status=JobStatus.RUNNING)
        await update_job_status(
            session=db_session,
            job_id=job.id,
            new_status=JobStatus.COMPLETED,
            result_ref="s3://bucket/result.zip",
        )

        # First deduction
        entry1 = await deduct_on_completion(db_session, job, test_user.id)
        expected_cost = DEFAULT_PRICING["render"]
        assert entry1.amount == expected_cost

        # Second call should be idempotent (same reference_id = "job-{job.id}")
        entry2 = await deduct_on_completion(db_session, job, test_user.id)
        assert entry2.id == entry1.id  # Same entry returned
        assert entry2.balance_after == entry1.balance_after


# =========================================================================
# 8. Insufficient credits blocks dispatch pre-flight
# =========================================================================


class TestInsufficientCreditsPreFlight:
    """check_sufficient_credits returns False when user cannot afford the job."""

    async def test_insufficient_credits_blocks_dispatch(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """User with 0 credits cannot dispatch a render job (costs 10)."""
        # No credits allocated -- balance is 0
        has_enough = await check_sufficient_credits(db_session, test_user.id, "render")
        assert has_enough is False

    async def test_sufficient_credits_allows_dispatch(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """User with enough credits passes the pre-flight check."""
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("50.0"),
            source=TransactionSource.STRIPE,
            reference_id="seed-preflight-ok",
        )

        has_enough = await check_sufficient_credits(db_session, test_user.id, "render")
        assert has_enough is True

    async def test_free_job_type_always_passes(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Echo jobs are free (0 credits) so pre-flight always passes."""
        has_enough = await check_sufficient_credits(db_session, test_user.id, "echo")
        assert has_enough is True


# =========================================================================
# 9. DLQ entry contains full error history
# =========================================================================


class TestDlqErrorHistory:
    """After max retries, the DLQ entry contains all error messages."""

    async def test_dlq_entry_has_complete_error_history(
        self,
        db_session: AsyncSession,
    ) -> None:
        """The DeadLetterEntry error_history includes all failure messages."""
        node = _make_node(name="dlq-history", public_key="key-dlq-history")
        db_session.add(node)
        await db_session.flush()

        # Create a job that has already exhausted retries
        job = _make_job(
            node=node,
            status=JobStatus.FAILED,
            retry_count=MAX_RETRIES,
            error_message="Error attempt 2",
        )
        db_session.add(job)
        await db_session.flush()

        # move_to_dlq should capture the history
        final_error = "Error attempt 3 (final)"
        dlq_entry = await move_to_dlq(db_session, job, final_error)

        assert isinstance(dlq_entry, DeadLetterEntry)
        assert dlq_entry.job_id == job.id
        assert dlq_entry.retry_count == MAX_RETRIES
        # error_history should contain the existing error and the new one
        assert "Error attempt 2" in dlq_entry.error_history
        assert final_error in dlq_entry.error_history
        assert len(dlq_entry.error_history) >= 2


# =========================================================================
# 10. Backoff values are correct
# =========================================================================


class TestBackoffValues:
    """Verify exponential backoff timing: 1s, 2s, 4s."""

    def test_backoff_at_retry_0_is_1_second(self) -> None:
        """First retry (count=0): 2^0 = 1.0 second."""
        assert calculate_backoff(0) == 1.0

    def test_backoff_at_retry_1_is_2_seconds(self) -> None:
        """Second retry (count=1): 2^1 = 2.0 seconds."""
        assert calculate_backoff(1) == 2.0

    def test_backoff_at_retry_2_is_4_seconds(self) -> None:
        """Third retry (count=2): 2^2 = 4.0 seconds."""
        assert calculate_backoff(2) == 4.0

    def test_backoff_uses_correct_base(self) -> None:
        """Backoff is BACKOFF_BASE ** retry_count."""
        for i in range(5):
            assert calculate_backoff(i) == BACKOFF_BASE**i


# =========================================================================
# 11. Payout includes only successful jobs
# =========================================================================


class TestPayoutOnlySuccessfulJobs:
    """Failed and DLQ'd jobs do not count toward operator earnings."""

    async def test_payout_excludes_failed_and_dlq_jobs(
        self,
        db_session: AsyncSession,
    ) -> None:
        """calculate_earnings only sums COMPLETED jobs for a given month."""
        node = _make_node(name="payout-node", public_key="key-payout")
        db_session.add(node)
        await db_session.flush()

        now = datetime.datetime.now(tz=datetime.UTC)
        today = now.date()

        # Completed job: counts toward payout
        job_ok = _make_job(
            node=node,
            status=JobStatus.COMPLETED,
            job_type="render",
            payload_ref="s3://ok",
        )
        job_ok.completed_at = now
        db_session.add(job_ok)

        # Failed job: should NOT count
        job_fail = _make_job(
            node=node,
            status=JobStatus.FAILED,
            job_type="render",
            payload_ref="s3://fail",
        )
        job_fail.completed_at = now
        db_session.add(job_fail)

        # Another completed job (different type)
        job_ok2 = _make_job(
            node=node,
            status=JobStatus.COMPLETED,
            job_type="inference",
            payload_ref="s3://ok2",
        )
        job_ok2.completed_at = now
        db_session.add(job_ok2)

        await db_session.flush()

        summary = await calculate_earnings(db_session, node.id, today)

        assert isinstance(summary, PayoutSummary)
        # Only 2 completed jobs should be counted
        assert summary.total_jobs == 2
        # Expected gross: render(10.0) + inference(5.0) = 15.0
        expected_gross = DEFAULT_PRICING["render"] + DEFAULT_PRICING["inference"]
        assert summary.gross_revenue == expected_gross
        assert summary.operator_earnings == expected_gross * OPERATOR_SHARE


# =========================================================================
# 12. Circuit breaker reset on success
# =========================================================================


class TestCircuitBreakerResetOnSuccess:
    """After a successful job, the failure counter resets."""

    async def test_success_resets_failure_counter(
        self,
        db_session: AsyncSession,
    ) -> None:
        """record_success clears the failure counter for a node."""
        cb = CircuitBreaker()

        node = _make_node(name="reset-node", public_key="key-reset")
        db_session.add(node)
        await db_session.flush()

        # Accumulate some failures (below threshold)
        await cb.record_failure(db_session, node.id)
        await cb.record_failure(db_session, node.id)
        assert cb._failure_counts[node.id] == 2

        # Record a success -- failure counter should reset
        await cb.record_success(db_session, node.id)
        assert cb._failure_counts.get(node.id) is None
        assert cb._last_failure_time.get(node.id) is None

        # Node should still be HEALTHY
        await db_session.refresh(node)
        assert node.status == NodeStatus.HEALTHY

    async def test_success_after_threshold_resets_completely(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Even after tripping the breaker, record_success brings node
        back to HEALTHY and clears all tracking state."""
        cb = CircuitBreaker()

        node = _make_node(name="reset-tripped", public_key="key-reset-tripped")
        db_session.add(node)
        await db_session.flush()

        # Trip the breaker
        for _ in range(FAILURE_THRESHOLD):
            await cb.record_failure(db_session, node.id)

        await db_session.refresh(node)
        assert node.status == NodeStatus.UNHEALTHY

        # Simulate half-open recovery and success
        await cb.record_success(db_session, node.id)

        await db_session.refresh(node)
        assert node.status == NodeStatus.HEALTHY
        assert cb._failure_counts.get(node.id) is None
        assert node.id not in cb._half_open


# =========================================================================
# 13. should_retry boundary check
# =========================================================================


class TestShouldRetryBoundary:
    """Verify should_retry respects MAX_RETRIES boundary exactly."""

    async def test_should_retry_true_below_max(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Job with retry_count < MAX_RETRIES is eligible for retry."""
        node = _make_node(name="boundary-node", public_key="key-boundary")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.FAILED, retry_count=MAX_RETRIES - 1)
        db_session.add(job)
        await db_session.flush()

        assert should_retry(job) is True

    async def test_should_retry_false_at_max(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Job with retry_count == MAX_RETRIES is NOT eligible for retry."""
        node = _make_node(name="boundary-node-2", public_key="key-boundary-2")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.FAILED, retry_count=MAX_RETRIES)
        db_session.add(job)
        await db_session.flush()

        assert should_retry(job) is False


# =========================================================================
# 14. get_job_price uses default pricing
# =========================================================================


class TestGetJobPriceDefaults:
    """Verify job pricing falls back to DEFAULT_PRICING when no DB row."""

    async def test_render_price_is_default(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Render job uses DEFAULT_PRICING when no job_pricing row exists."""
        price = await get_job_price(db_session, "render")
        assert price == DEFAULT_PRICING["render"]
        assert price == Decimal("10.0")

    async def test_unknown_type_uses_fallback(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Unknown job types fall back to the 1.0 fallback price."""
        price = await get_job_price(db_session, "unknown_job_type_xyz")
        assert price == Decimal("1.0")
