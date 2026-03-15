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

"""Tests for the usage tracking service (core.billing.usage).

Covers pricing lookup (DB, default, fallback), credit deduction on job
completion, pre-flight balance checks, and idempotency guarantees.
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
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.billing.models import JobPricing
from core.billing.usage import (
    DEFAULT_PRICING,
    check_sufficient_credits,
    deduct_on_completion,
    get_job_price,
)
from core.ledger.service import InsufficientCreditsError
from core.models.base import CreditLedgerEntry, TransactionDirection, TransactionSource

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(*, job_id: uuid.UUID | None = None, job_type: str = "render") -> MagicMock:
    """Create a mock JobDispatch with the given attributes."""
    job = MagicMock()
    job.id = job_id or uuid.uuid4()
    job.job_type = job_type
    return job


def _make_ledger_entry(
    *,
    user_id: uuid.UUID,
    amount: Decimal,
    reference_id: str,
    balance_after: Decimal = Decimal("90.0000"),
) -> MagicMock:
    """Create a mock CreditLedgerEntry."""
    entry = MagicMock(spec=CreditLedgerEntry)
    entry.user_id = user_id
    entry.amount = amount
    entry.direction = TransactionDirection.DEBIT
    entry.source = TransactionSource.USAGE
    entry.reference_id = reference_id
    entry.balance_after = balance_after
    return entry


def _mock_scalar_result(value):
    """Create an AsyncMock that mimics session.execute() returning a scalar result."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ---------------------------------------------------------------------------
# get_job_price tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_job_price_from_db():
    """get_job_price returns pricing from DB when an active row is present."""
    session = AsyncMock()
    pricing_row = MagicMock(spec=JobPricing)
    pricing_row.credits_per_unit = Decimal("15.0000")
    pricing_row.is_active = True

    session.execute.return_value = _mock_scalar_result(pricing_row)

    price = await get_job_price(session, "render")
    assert price == Decimal("15.0000")
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_job_price_fallback_to_default():
    """get_job_price falls back to DEFAULT_PRICING when no DB row exists."""
    session = AsyncMock()
    session.execute.return_value = _mock_scalar_result(None)

    price = await get_job_price(session, "render")
    assert price == DEFAULT_PRICING["render"]
    assert price == Decimal("10.0")


@pytest.mark.asyncio
async def test_get_job_price_fallback_to_one():
    """get_job_price falls back to 1.0 for unknown job types not in DB or defaults."""
    session = AsyncMock()
    session.execute.return_value = _mock_scalar_result(None)

    price = await get_job_price(session, "totally_unknown_type")
    assert price == Decimal("1.0")


@pytest.mark.asyncio
async def test_get_job_price_echo_is_free():
    """get_job_price returns 0.0 for echo jobs (from DEFAULT_PRICING)."""
    session = AsyncMock()
    session.execute.return_value = _mock_scalar_result(None)

    price = await get_job_price(session, "echo")
    assert price == Decimal("0.0")


@pytest.mark.asyncio
async def test_get_job_price_cpu_benchmark():
    """get_job_price returns 1.0 for cpu_benchmark (from DEFAULT_PRICING)."""
    session = AsyncMock()
    session.execute.return_value = _mock_scalar_result(None)

    price = await get_job_price(session, "cpu_benchmark")
    assert price == Decimal("1.0")


# ---------------------------------------------------------------------------
# deduct_on_completion tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deduct_on_completion_creates_ledger_entry():
    """deduct_on_completion creates a ledger entry with USAGE source."""
    user_id = uuid.uuid4()
    job = _make_job(job_type="render")
    expected_entry = _make_ledger_entry(
        user_id=user_id,
        amount=Decimal("10.0"),
        reference_id=f"job-{job.id}",
    )

    with (
        patch("core.billing.usage.get_job_price", new_callable=AsyncMock) as mock_price,
        patch("core.billing.usage.deduct_credits", new_callable=AsyncMock) as mock_deduct,
    ):
        mock_price.return_value = Decimal("10.0")
        mock_deduct.return_value = expected_entry

        session = AsyncMock()
        entry = await deduct_on_completion(session, job, user_id)

        assert entry.source == TransactionSource.USAGE
        mock_deduct.assert_awaited_once_with(
            session=session,
            user_id=user_id,
            amount=Decimal("10.0"),
            source=TransactionSource.USAGE,
            reference_id=f"job-{job.id}",
            description=f"Usage charge for render job {job.id}",
        )


@pytest.mark.asyncio
async def test_deduct_on_completion_correct_reference_id():
    """deduct_on_completion uses reference_id format 'job-{job.id}'."""
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    job = _make_job(job_id=job_id, job_type="inference")
    expected_ref = f"job-{job_id}"
    expected_entry = _make_ledger_entry(
        user_id=user_id,
        amount=Decimal("5.0"),
        reference_id=expected_ref,
    )

    with (
        patch("core.billing.usage.get_job_price", new_callable=AsyncMock) as mock_price,
        patch("core.billing.usage.deduct_credits", new_callable=AsyncMock) as mock_deduct,
    ):
        mock_price.return_value = Decimal("5.0")
        mock_deduct.return_value = expected_entry

        session = AsyncMock()
        entry = await deduct_on_completion(session, job, user_id)

        assert entry.reference_id == expected_ref


@pytest.mark.asyncio
async def test_deduct_on_completion_insufficient_credits():
    """deduct_on_completion raises InsufficientCreditsError when balance too low."""
    user_id = uuid.uuid4()
    job = _make_job(job_type="render")

    with (
        patch("core.billing.usage.get_job_price", new_callable=AsyncMock) as mock_price,
        patch("core.billing.usage.deduct_credits", new_callable=AsyncMock) as mock_deduct,
    ):
        mock_price.return_value = Decimal("10.0")
        mock_deduct.side_effect = InsufficientCreditsError(
            user_id=user_id,
            requested=Decimal("10.0"),
            available=Decimal("3.0"),
        )

        session = AsyncMock()
        with pytest.raises(InsufficientCreditsError) as exc_info:
            await deduct_on_completion(session, job, user_id)

        assert exc_info.value.requested == Decimal("10.0")
        assert exc_info.value.available == Decimal("3.0")


@pytest.mark.asyncio
async def test_deduct_on_completion_idempotent():
    """Calling deduct_on_completion twice with the same job returns existing entry."""
    user_id = uuid.uuid4()
    job = _make_job(job_type="render")
    entry_id = uuid.uuid4()

    first_entry = _make_ledger_entry(
        user_id=user_id,
        amount=Decimal("10.0"),
        reference_id=f"job-{job.id}",
    )
    first_entry.id = entry_id

    second_entry = _make_ledger_entry(
        user_id=user_id,
        amount=Decimal("10.0"),
        reference_id=f"job-{job.id}",
    )
    second_entry.id = entry_id  # Same ID = same entry returned by idempotent deduct_credits

    with (
        patch("core.billing.usage.get_job_price", new_callable=AsyncMock) as mock_price,
        patch("core.billing.usage.deduct_credits", new_callable=AsyncMock) as mock_deduct,
    ):
        mock_price.return_value = Decimal("10.0")
        mock_deduct.side_effect = [first_entry, second_entry]

        session = AsyncMock()
        result1 = await deduct_on_completion(session, job, user_id)
        result2 = await deduct_on_completion(session, job, user_id)

        # Both calls produce the same ledger entry ID (idempotent)
        assert result1.id == result2.id
        assert mock_deduct.await_count == 2
        # Both calls used the same reference_id
        for call in mock_deduct.call_args_list:
            assert call.kwargs["reference_id"] == f"job-{job.id}"


# ---------------------------------------------------------------------------
# check_sufficient_credits tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_sufficient_credits_enough():
    """check_sufficient_credits returns True when user has enough balance."""
    user_id = uuid.uuid4()

    with (
        patch("core.billing.usage.get_job_price", new_callable=AsyncMock) as mock_price,
        patch("core.billing.usage.get_balance", new_callable=AsyncMock) as mock_balance,
    ):
        mock_price.return_value = Decimal("10.0")
        mock_balance.return_value = Decimal("50.0000")

        session = AsyncMock()
        result = await check_sufficient_credits(session, user_id, "render")
        assert result is True


@pytest.mark.asyncio
async def test_check_sufficient_credits_insufficient():
    """check_sufficient_credits returns False when balance is too low."""
    user_id = uuid.uuid4()

    with (
        patch("core.billing.usage.get_job_price", new_callable=AsyncMock) as mock_price,
        patch("core.billing.usage.get_balance", new_callable=AsyncMock) as mock_balance,
    ):
        mock_price.return_value = Decimal("10.0")
        mock_balance.return_value = Decimal("5.0000")

        session = AsyncMock()
        result = await check_sufficient_credits(session, user_id, "render")
        assert result is False


@pytest.mark.asyncio
async def test_check_sufficient_credits_free_job():
    """check_sufficient_credits returns True for free job types (echo) even with zero balance."""
    user_id = uuid.uuid4()

    with (
        patch("core.billing.usage.get_job_price", new_callable=AsyncMock) as mock_price,
        patch("core.billing.usage.get_balance", new_callable=AsyncMock) as mock_balance,
    ):
        mock_price.return_value = Decimal("0.0")
        # get_balance should not even be called for free jobs
        mock_balance.return_value = Decimal("0.0000")

        session = AsyncMock()
        result = await check_sufficient_credits(session, user_id, "echo")
        assert result is True
        # Balance should NOT be checked for free jobs
        mock_balance.assert_not_awaited()


# ---------------------------------------------------------------------------
# JobPricing model tests
# ---------------------------------------------------------------------------


def test_job_pricing_model_fields():
    """JobPricing model has expected fields and defaults."""
    pricing = JobPricing(
        job_type="render",
        credits_per_unit=Decimal("10.0000"),
        unit_type="per_job",
        is_active=True,
    )
    assert pricing.job_type == "render"
    assert pricing.credits_per_unit == Decimal("10.0000")
    assert pricing.unit_type == "per_job"
    assert pricing.is_active is True


def test_job_pricing_column_defaults():
    """JobPricing model has correct column-level defaults for INSERT."""
    # Column defaults are applied at INSERT time, not instantiation.
    # Verify the column metadata has the expected defaults configured.
    table = JobPricing.__table__
    assert table.c.unit_type.default.arg == "per_job"
    assert table.c.is_active.default.arg is True


def test_job_pricing_model_repr():
    """JobPricing __repr__ contains key info."""
    pricing = JobPricing(
        job_type="inference",
        credits_per_unit=Decimal("5.0000"),
    )
    repr_str = repr(pricing)
    assert "JobPricing" in repr_str
    assert "inference" in repr_str
    assert "5.0000" in repr_str
