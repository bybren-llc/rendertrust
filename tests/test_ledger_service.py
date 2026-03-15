# Copyright 2025 ByBren, LLC
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

"""Tests for the credit ledger service (deduct_credits and get_history)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from core.ledger.service import (
    InsufficientCreditsError,
    allocate_credits,
    deduct_credits,
    get_history,
)
from core.models.base import TransactionDirection, TransactionSource

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.models.base import User


# ---------------------------------------------------------------------------
# deduct_credits tests
# ---------------------------------------------------------------------------


async def test_deduct_credits_basic(db_session: AsyncSession, test_user: User) -> None:
    """Allocate 100, deduct 30, verify balance_after=70."""
    await allocate_credits(
        session=db_session,
        user_id=test_user.id,
        amount=Decimal("100.0000"),
        source=TransactionSource.STRIPE,
        reference_id="alloc-basic-100",
        description="Initial allocation",
    )

    entry = await deduct_credits(
        session=db_session,
        user_id=test_user.id,
        amount=Decimal("30.0000"),
        source=TransactionSource.USAGE,
        reference_id="deduct-basic-30",
        description="Render usage",
    )

    assert entry.direction == TransactionDirection.DEBIT
    assert entry.amount == Decimal("30.0000")
    assert entry.balance_after == Decimal("70.0000")
    assert entry.user_id == test_user.id
    assert entry.source == TransactionSource.USAGE
    assert entry.reference_id == "deduct-basic-30"


async def test_deduct_credits_idempotent(db_session: AsyncSession, test_user: User) -> None:
    """Same reference_id returns existing entry without creating a duplicate."""
    await allocate_credits(
        session=db_session,
        user_id=test_user.id,
        amount=Decimal("100.0000"),
        source=TransactionSource.STRIPE,
        reference_id="alloc-idemp-100",
    )

    first = await deduct_credits(
        session=db_session,
        user_id=test_user.id,
        amount=Decimal("25.0000"),
        source=TransactionSource.USAGE,
        reference_id="deduct-idemp-25",
    )

    second = await deduct_credits(
        session=db_session,
        user_id=test_user.id,
        amount=Decimal("25.0000"),
        source=TransactionSource.USAGE,
        reference_id="deduct-idemp-25",
    )

    assert first.id == second.id
    assert second.balance_after == Decimal("75.0000")


async def test_deduct_credits_insufficient(db_session: AsyncSession, test_user: User) -> None:
    """Raises InsufficientCreditsError when balance would go negative."""
    await allocate_credits(
        session=db_session,
        user_id=test_user.id,
        amount=Decimal("10.0000"),
        source=TransactionSource.STRIPE,
        reference_id="alloc-insuff-10",
    )

    with pytest.raises(InsufficientCreditsError) as exc_info:
        await deduct_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("50.0000"),
            source=TransactionSource.USAGE,
            reference_id="deduct-insuff-50",
        )

    assert exc_info.value.requested == Decimal("50.0000")
    assert exc_info.value.available == Decimal("10.0000")
    assert exc_info.value.user_id == test_user.id


async def test_deduct_credits_zero_or_negative(db_session: AsyncSession, test_user: User) -> None:
    """Raises ValueError for zero or negative amounts."""
    with pytest.raises(ValueError, match="Debit amount must be positive"):
        await deduct_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("0"),
            source=TransactionSource.USAGE,
            reference_id="deduct-zero",
        )

    with pytest.raises(ValueError, match="Debit amount must be positive"):
        await deduct_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("-5.0000"),
            source=TransactionSource.USAGE,
            reference_id="deduct-neg",
        )


# ---------------------------------------------------------------------------
# get_history tests
# ---------------------------------------------------------------------------


async def test_get_history_default(db_session: AsyncSession, test_user: User) -> None:
    """Returns entries in created_at DESC order."""
    await allocate_credits(
        session=db_session,
        user_id=test_user.id,
        amount=Decimal("200.0000"),
        source=TransactionSource.STRIPE,
        reference_id="alloc-hist-200",
    )
    await deduct_credits(
        session=db_session,
        user_id=test_user.id,
        amount=Decimal("50.0000"),
        source=TransactionSource.USAGE,
        reference_id="deduct-hist-50",
    )
    await allocate_credits(
        session=db_session,
        user_id=test_user.id,
        amount=Decimal("25.0000"),
        source=TransactionSource.ADJUSTMENT,
        reference_id="alloc-hist-25",
    )

    history = await get_history(session=db_session, user_id=test_user.id)

    assert len(history) == 3
    # Newest first
    assert history[0].reference_id == "alloc-hist-25"
    assert history[1].reference_id == "deduct-hist-50"
    assert history[2].reference_id == "alloc-hist-200"
    # Verify ordering by created_at
    for i in range(len(history) - 1):
        assert history[i].created_at >= history[i + 1].created_at


async def test_get_history_pagination(db_session: AsyncSession, test_user: User) -> None:
    """Limit and offset work correctly for pagination."""
    # Create 5 entries
    for i in range(5):
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("10.0000"),
            source=TransactionSource.STRIPE,
            reference_id=f"alloc-page-{i}",
        )

    # First page: limit=2, offset=0
    page1 = await get_history(session=db_session, user_id=test_user.id, limit=2, offset=0)
    assert len(page1) == 2

    # Second page: limit=2, offset=2
    page2 = await get_history(session=db_session, user_id=test_user.id, limit=2, offset=2)
    assert len(page2) == 2

    # Verify no overlap
    page1_ids = {e.id for e in page1}
    page2_ids = {e.id for e in page2}
    assert page1_ids.isdisjoint(page2_ids)

    # Third page: limit=2, offset=4 -- only 1 remaining
    page3 = await get_history(session=db_session, user_id=test_user.id, limit=2, offset=4)
    assert len(page3) == 1


async def test_get_history_empty(db_session: AsyncSession, test_user: User) -> None:
    """Returns empty list for user with no entries."""
    history = await get_history(session=db_session, user_id=test_user.id)
    assert history == []
