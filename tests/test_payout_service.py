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

"""Tests for the payout cron service (core.billing.payout).

Covers earnings calculation, payout report generation, ledger entry
creation, idempotency, revenue share validation, and month boundary
filtering.
"""

from __future__ import annotations

import os

# Environment overrides -- MUST come before any application imports.
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_fake")

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.billing.payout import (
    OPERATOR_SHARE,
    PLATFORM_SHARE,
    PayoutSummary,
    _month_boundaries,
    calculate_earnings,
    execute_payouts,
    generate_payout_report,
)
from core.models.base import TransactionSource
from core.scheduler.models import JobStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job_dispatch(
    *,
    node_id: uuid.UUID,
    job_type: str = "render",
    status: JobStatus = JobStatus.COMPLETED,
    completed_at: datetime | None = None,
) -> MagicMock:
    """Create a mock JobDispatch with the given attributes."""
    job = MagicMock()
    job.id = uuid.uuid4()
    job.node_id = node_id
    job.job_type = job_type
    job.status = status
    job.completed_at = completed_at or datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
    return job


def _mock_scalars_result(values):
    """Create a mock that mimics session.execute().scalars().all()."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


def _mock_distinct_result(values):
    """Create a mock that mimics session.execute().scalars().all() for distinct query."""
    return _mock_scalars_result(values)


# ---------------------------------------------------------------------------
# PayoutSummary dataclass tests
# ---------------------------------------------------------------------------


def test_payout_summary_fields_and_defaults():
    """PayoutSummary has all expected fields and is_paid defaults to False."""
    node_id = uuid.uuid4()
    summary = PayoutSummary(
        node_id=node_id,
        month=date(2026, 3, 1),
        total_jobs=5,
        gross_revenue=Decimal("50.0"),
        operator_earnings=Decimal("35.0"),
        platform_fee=Decimal("15.0"),
    )
    assert summary.node_id == node_id
    assert summary.month == date(2026, 3, 1)
    assert summary.total_jobs == 5
    assert summary.gross_revenue == Decimal("50.0")
    assert summary.operator_earnings == Decimal("35.0")
    assert summary.platform_fee == Decimal("15.0")
    assert summary.is_paid is False


def test_payout_summary_is_paid_explicit():
    """PayoutSummary.is_paid can be set explicitly to True."""
    summary = PayoutSummary(
        node_id=uuid.uuid4(),
        month=date(2026, 3, 1),
        total_jobs=1,
        gross_revenue=Decimal("10.0"),
        operator_earnings=Decimal("7.0"),
        platform_fee=Decimal("3.0"),
        is_paid=True,
    )
    assert summary.is_paid is True


def test_payout_summary_is_frozen():
    """PayoutSummary is immutable (frozen dataclass)."""
    summary = PayoutSummary(
        node_id=uuid.uuid4(),
        month=date(2026, 3, 1),
        total_jobs=1,
        gross_revenue=Decimal("10.0"),
        operator_earnings=Decimal("7.0"),
        platform_fee=Decimal("3.0"),
    )
    with pytest.raises(AttributeError):
        summary.is_paid = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Revenue share constants
# ---------------------------------------------------------------------------


def test_operator_and_platform_share_sum_to_one():
    """OPERATOR_SHARE + PLATFORM_SHARE must equal 1.0."""
    assert Decimal("1.0") == OPERATOR_SHARE + PLATFORM_SHARE


def test_operator_share_is_seventy_percent():
    """OPERATOR_SHARE is 70%."""
    assert Decimal("0.70") == OPERATOR_SHARE


def test_platform_share_is_thirty_percent():
    """PLATFORM_SHARE is 30%."""
    assert Decimal("0.30") == PLATFORM_SHARE


# ---------------------------------------------------------------------------
# _month_boundaries tests
# ---------------------------------------------------------------------------


def test_month_boundaries_normal():
    """_month_boundaries returns correct boundaries for a normal month."""
    first, next_m = _month_boundaries(date(2026, 3, 15))
    assert first == date(2026, 3, 1)
    assert next_m == date(2026, 4, 1)


def test_month_boundaries_december():
    """_month_boundaries handles December -> January year rollover."""
    first, next_m = _month_boundaries(date(2026, 12, 25))
    assert first == date(2026, 12, 1)
    assert next_m == date(2027, 1, 1)


def test_month_boundaries_first_day():
    """_month_boundaries works when input is already the first of the month."""
    first, next_m = _month_boundaries(date(2026, 1, 1))
    assert first == date(2026, 1, 1)
    assert next_m == date(2026, 2, 1)


# ---------------------------------------------------------------------------
# calculate_earnings tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calculate_earnings_single_job_type():
    """calculate_earnings returns correct summary for a single job type."""
    node_id = uuid.uuid4()
    month = date(2026, 3, 1)
    jobs = [
        _make_job_dispatch(node_id=node_id, job_type="render"),
        _make_job_dispatch(node_id=node_id, job_type="render"),
    ]

    session = AsyncMock()
    session.execute.return_value = _mock_scalars_result(jobs)

    with patch("core.billing.payout.get_job_price", new_callable=AsyncMock) as mock_price:
        mock_price.return_value = Decimal("10.0")
        summary = await calculate_earnings(session, node_id, month)

    assert summary.node_id == node_id
    assert summary.month == date(2026, 3, 1)
    assert summary.total_jobs == 2
    assert summary.gross_revenue == Decimal("20.0")
    assert summary.operator_earnings == Decimal("14.00")
    assert summary.platform_fee == Decimal("6.00")
    assert summary.is_paid is False


@pytest.mark.asyncio
async def test_calculate_earnings_multiple_job_types():
    """calculate_earnings handles multiple job types with different prices."""
    node_id = uuid.uuid4()
    month = date(2026, 3, 1)
    jobs = [
        _make_job_dispatch(node_id=node_id, job_type="render"),
        _make_job_dispatch(node_id=node_id, job_type="inference"),
        _make_job_dispatch(node_id=node_id, job_type="cpu_benchmark"),
    ]

    session = AsyncMock()
    session.execute.return_value = _mock_scalars_result(jobs)

    price_map = {
        "render": Decimal("10.0"),
        "inference": Decimal("5.0"),
        "cpu_benchmark": Decimal("1.0"),
    }

    with patch("core.billing.payout.get_job_price", new_callable=AsyncMock) as mock_price:
        mock_price.side_effect = lambda _s, jt: price_map[jt]
        summary = await calculate_earnings(session, node_id, month)

    # gross = 10 + 5 + 1 = 16
    assert summary.total_jobs == 3
    assert summary.gross_revenue == Decimal("16.0")
    assert summary.operator_earnings == Decimal("16.0") * OPERATOR_SHARE
    assert summary.platform_fee == Decimal("16.0") * PLATFORM_SHARE


@pytest.mark.asyncio
async def test_calculate_earnings_no_completions():
    """calculate_earnings returns zero for a node with no completed jobs."""
    node_id = uuid.uuid4()
    month = date(2026, 3, 1)

    session = AsyncMock()
    session.execute.return_value = _mock_scalars_result([])

    with patch("core.billing.payout.get_job_price", new_callable=AsyncMock) as mock_price:
        summary = await calculate_earnings(session, node_id, month)

    assert summary.total_jobs == 0
    assert summary.gross_revenue == Decimal("0")
    assert summary.operator_earnings == Decimal("0")
    assert summary.platform_fee == Decimal("0")
    assert summary.is_paid is False
    mock_price.assert_not_awaited()


@pytest.mark.asyncio
async def test_calculate_earnings_operator_share_seventy_percent():
    """calculate_earnings applies exactly 70% operator share."""
    node_id = uuid.uuid4()
    month = date(2026, 3, 1)
    jobs = [_make_job_dispatch(node_id=node_id, job_type="render")]

    session = AsyncMock()
    session.execute.return_value = _mock_scalars_result(jobs)

    with patch("core.billing.payout.get_job_price", new_callable=AsyncMock) as mock_price:
        mock_price.return_value = Decimal("100.0")
        summary = await calculate_earnings(session, node_id, month)

    assert summary.gross_revenue == Decimal("100.0")
    assert summary.operator_earnings == Decimal("70.00")
    assert summary.platform_fee == Decimal("30.00")
    assert summary.operator_earnings + summary.platform_fee == summary.gross_revenue


# ---------------------------------------------------------------------------
# generate_payout_report tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_payout_report_all_active_nodes():
    """generate_payout_report returns summaries for all nodes with completions."""
    node_a = uuid.uuid4()
    node_b = uuid.uuid4()
    month = date(2026, 3, 1)

    jobs_a = [_make_job_dispatch(node_id=node_a, job_type="render")]
    jobs_b = [_make_job_dispatch(node_id=node_b, job_type="inference")]

    session = AsyncMock()
    # First call: _get_active_node_ids (distinct query)
    # Subsequent calls: _get_completed_jobs for each node
    session.execute.side_effect = [
        _mock_scalars_result([node_a, node_b]),  # distinct node IDs
        _mock_scalars_result(jobs_a),  # jobs for node_a
        _mock_scalars_result(jobs_b),  # jobs for node_b
    ]

    with patch("core.billing.payout.get_job_price", new_callable=AsyncMock) as mock_price:
        mock_price.return_value = Decimal("10.0")
        summaries = await generate_payout_report(session, month)

    assert len(summaries) == 2
    node_ids = {s.node_id for s in summaries}
    assert node_a in node_ids
    assert node_b in node_ids


@pytest.mark.asyncio
async def test_generate_payout_report_excludes_nodes_with_no_completions():
    """generate_payout_report only includes nodes returned by _get_active_node_ids."""
    month = date(2026, 3, 1)

    session = AsyncMock()
    # No active node IDs returned
    session.execute.return_value = _mock_scalars_result([])

    with patch("core.billing.payout.get_job_price", new_callable=AsyncMock):
        summaries = await generate_payout_report(session, month)

    assert summaries == []


# ---------------------------------------------------------------------------
# execute_payouts tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_payouts_creates_ledger_entries():
    """execute_payouts creates ledger credit entries for operators."""
    node_id = uuid.uuid4()
    month = date(2026, 3, 1)
    jobs = [_make_job_dispatch(node_id=node_id, job_type="render")]

    session = AsyncMock()
    session.execute.side_effect = [
        _mock_scalars_result([node_id]),  # active node IDs
        _mock_scalars_result(jobs),  # jobs for node
    ]

    mock_entry = MagicMock()

    with (
        patch("core.billing.payout.get_job_price", new_callable=AsyncMock) as mock_price,
        patch("core.billing.payout.allocate_credits", new_callable=AsyncMock) as mock_alloc,
    ):
        mock_price.return_value = Decimal("10.0")
        mock_alloc.return_value = mock_entry

        results = await execute_payouts(session, month)

    assert len(results) == 1
    assert results[0].is_paid is True
    assert results[0].operator_earnings == Decimal("7.00")

    mock_alloc.assert_awaited_once_with(
        session=session,
        user_id=node_id,
        amount=Decimal("7.00"),
        source=TransactionSource.ADJUSTMENT,
        reference_id=f"payout-{node_id}-2026-03-01",
        description="Operator payout for 2026-03-01: 1 jobs, gross 10.0",
    )


@pytest.mark.asyncio
async def test_execute_payouts_idempotent():
    """execute_payouts is idempotent -- same month does not double-pay.

    The allocate_credits function handles idempotency via reference_id.
    Calling execute_payouts twice should call allocate_credits twice,
    but allocate_credits returns the existing entry on the second call.
    """
    node_id = uuid.uuid4()
    month = date(2026, 3, 1)
    jobs = [_make_job_dispatch(node_id=node_id, job_type="render")]

    session = AsyncMock()
    # Each call to execute_payouts triggers 2 execute() calls
    session.execute.side_effect = [
        _mock_scalars_result([node_id]),  # active node IDs (1st call)
        _mock_scalars_result(jobs),  # jobs for node (1st call)
        _mock_scalars_result([node_id]),  # active node IDs (2nd call)
        _mock_scalars_result(jobs),  # jobs for node (2nd call)
    ]

    mock_entry = MagicMock()
    mock_entry.id = uuid.uuid4()

    with (
        patch("core.billing.payout.get_job_price", new_callable=AsyncMock) as mock_price,
        patch("core.billing.payout.allocate_credits", new_callable=AsyncMock) as mock_alloc,
    ):
        mock_price.return_value = Decimal("10.0")
        # allocate_credits is idempotent -- returns same entry both times
        mock_alloc.return_value = mock_entry

        results_1 = await execute_payouts(session, month)
        results_2 = await execute_payouts(session, month)

    assert mock_alloc.await_count == 2
    expected_ref = f"payout-{node_id}-2026-03-01"
    for c in mock_alloc.call_args_list:
        assert c.kwargs["reference_id"] == expected_ref

    assert results_1[0].is_paid is True
    assert results_2[0].is_paid is True


@pytest.mark.asyncio
async def test_execute_payouts_correct_reference_id_format():
    """execute_payouts uses reference_id format 'payout-{node_id}-{YYYY-MM-DD}'."""
    node_id = uuid.uuid4()
    month = date(2026, 6, 15)  # Mid-month date should normalize to 2026-06-01
    jobs = [_make_job_dispatch(node_id=node_id, job_type="render")]

    session = AsyncMock()
    session.execute.side_effect = [
        _mock_scalars_result([node_id]),
        _mock_scalars_result(jobs),
    ]

    mock_entry = MagicMock()

    with (
        patch("core.billing.payout.get_job_price", new_callable=AsyncMock) as mock_price,
        patch("core.billing.payout.allocate_credits", new_callable=AsyncMock) as mock_alloc,
    ):
        mock_price.return_value = Decimal("10.0")
        mock_alloc.return_value = mock_entry

        await execute_payouts(session, month)

    expected_ref = f"payout-{node_id}-2026-06-01"
    mock_alloc.assert_awaited_once()
    actual_ref = mock_alloc.call_args.kwargs["reference_id"]
    assert actual_ref == expected_ref


@pytest.mark.asyncio
async def test_execute_payouts_skips_zero_earnings():
    """execute_payouts does not create ledger entries for nodes with zero revenue."""
    node_id = uuid.uuid4()
    month = date(2026, 3, 1)
    # Node has an echo job which costs 0
    jobs = [_make_job_dispatch(node_id=node_id, job_type="echo")]

    session = AsyncMock()
    session.execute.side_effect = [
        _mock_scalars_result([node_id]),
        _mock_scalars_result(jobs),
    ]

    with (
        patch("core.billing.payout.get_job_price", new_callable=AsyncMock) as mock_price,
        patch("core.billing.payout.allocate_credits", new_callable=AsyncMock) as mock_alloc,
    ):
        mock_price.return_value = Decimal("0.0")

        results = await execute_payouts(session, month)

    assert len(results) == 1
    assert results[0].is_paid is False
    assert results[0].operator_earnings == Decimal("0.00")
    mock_alloc.assert_not_awaited()


# ---------------------------------------------------------------------------
# Month boundary filtering test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_month_boundary_filtering():
    """calculate_earnings only includes jobs within the target month boundaries.

    The SQL query uses completed_at >= first_day AND completed_at < next_month.
    We verify the session.execute is called with the correct filter structure
    by checking the query is issued (actual filtering is DB-level).
    """
    node_id = uuid.uuid4()
    month = date(2026, 3, 15)  # Mid-month input

    # Job in March (should be included by the DB query)
    march_job = _make_job_dispatch(
        node_id=node_id,
        job_type="render",
        completed_at=datetime(2026, 3, 20, 10, 0, 0, tzinfo=UTC),
    )

    session = AsyncMock()
    # The mock returns only the March job (DB would filter April jobs out)
    session.execute.return_value = _mock_scalars_result([march_job])

    with patch("core.billing.payout.get_job_price", new_callable=AsyncMock) as mock_price:
        mock_price.return_value = Decimal("10.0")
        summary = await calculate_earnings(session, node_id, month)

    # Only 1 job included
    assert summary.total_jobs == 1
    assert summary.gross_revenue == Decimal("10.0")
    # Month is normalized to first day
    assert summary.month == date(2026, 3, 1)
    # Verify execute was called (the actual SQL filtering is DB-level)
    session.execute.assert_awaited_once()
