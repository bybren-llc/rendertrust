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

"""Idempotency and concurrency validation tests for the credit ledger service.

Validates:
- Duplicate allocations/deductions with the same reference_id are idempotent
- UNIQUE(reference_id, direction) allows same reference_id across directions
- Sequential operations maintain correct running balance
- Edge cases around precision, limits, and multi-user isolation
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from passlib.hash import bcrypt
from sqlalchemy import func, select

from core.ledger.service import (
    InsufficientCreditsError,
    allocate_credits,
    deduct_credits,
    get_balance,
)
from core.models.base import CreditLedgerEntry, TransactionDirection, TransactionSource, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# TestAllocateIdempotency
# ---------------------------------------------------------------------------


class TestAllocateIdempotency:
    """Verify allocate_credits idempotency guarantees."""

    async def test_allocate_same_reference_returns_existing(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Calling allocate_credits twice with the same reference_id must
        return the existing entry and create only one row.
        """
        first = await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("50.0000"),
            source=TransactionSource.STRIPE,
            reference_id="idemp-alloc-dup",
        )

        second = await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("50.0000"),
            source=TransactionSource.STRIPE,
            reference_id="idemp-alloc-dup",
        )

        # Same database row returned
        assert first.id == second.id
        assert second.balance_after == Decimal("50.0000")

        # Exactly one CREDIT entry with this reference_id
        count_result = await db_session.execute(
            select(func.count()).where(
                CreditLedgerEntry.reference_id == "idemp-alloc-dup",
                CreditLedgerEntry.direction == TransactionDirection.CREDIT,
            )
        )
        assert count_result.scalar() == 1

    async def test_allocate_different_references_create_separate(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Two allocations with different reference_ids produce two entries."""
        entry_a = await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("40.0000"),
            source=TransactionSource.STRIPE,
            reference_id="idemp-alloc-a",
        )

        entry_b = await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("60.0000"),
            source=TransactionSource.STRIPE,
            reference_id="idemp-alloc-b",
        )

        assert entry_a.id != entry_b.id
        assert entry_a.balance_after == Decimal("40.0000")
        assert entry_b.balance_after == Decimal("100.0000")

    async def test_allocate_same_reference_different_direction_allowed(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """The UNIQUE constraint is on (reference_id, direction), so the same
        reference_id may appear as both a CREDIT and a DEBIT.
        """
        credit_entry = await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("100.0000"),
            source=TransactionSource.STRIPE,
            reference_id="idemp-cross-dir",
        )

        debit_entry = await deduct_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("25.0000"),
            source=TransactionSource.USAGE,
            reference_id="idemp-cross-dir",
        )

        assert credit_entry.id != debit_entry.id
        assert credit_entry.direction == TransactionDirection.CREDIT
        assert debit_entry.direction == TransactionDirection.DEBIT
        assert debit_entry.balance_after == Decimal("75.0000")


# ---------------------------------------------------------------------------
# TestDeductIdempotency
# ---------------------------------------------------------------------------


class TestDeductIdempotency:
    """Verify deduct_credits idempotency guarantees."""

    async def test_deduct_same_reference_returns_existing(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Calling deduct_credits twice with the same reference_id must
        return the existing entry and create only one DEBIT row.
        """
        # Seed balance
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("200.0000"),
            source=TransactionSource.STRIPE,
            reference_id="idemp-deduct-seed",
        )

        first = await deduct_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("75.0000"),
            source=TransactionSource.USAGE,
            reference_id="idemp-deduct-dup",
        )

        second = await deduct_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("75.0000"),
            source=TransactionSource.USAGE,
            reference_id="idemp-deduct-dup",
        )

        # Same database row returned
        assert first.id == second.id
        assert second.balance_after == Decimal("125.0000")

        # Exactly one DEBIT entry with this reference_id
        count_result = await db_session.execute(
            select(func.count()).where(
                CreditLedgerEntry.reference_id == "idemp-deduct-dup",
                CreditLedgerEntry.direction == TransactionDirection.DEBIT,
            )
        )
        assert count_result.scalar() == 1

    async def test_deduct_after_allocate_same_reference(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Allocate and deduct with the SAME reference_id but different
        directions must both succeed (unique constraint is on the pair).
        """
        alloc = await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("100.0000"),
            source=TransactionSource.STRIPE,
            reference_id="idemp-same-ref-x",
        )

        deduction = await deduct_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("30.0000"),
            source=TransactionSource.USAGE,
            reference_id="idemp-same-ref-x",
        )

        assert alloc.id != deduction.id
        assert alloc.direction == TransactionDirection.CREDIT
        assert deduction.direction == TransactionDirection.DEBIT
        assert deduction.balance_after == Decimal("70.0000")


# ---------------------------------------------------------------------------
# TestBalanceConsistency
# ---------------------------------------------------------------------------


class TestBalanceConsistency:
    """Verify running balance stays correct across mixed operations."""

    async def test_sequential_operations_maintain_balance(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """allocate 100 -> deduct 30 -> allocate 50 -> deduct 20
        Expected final balance: 100 - 30 + 50 - 20 = 100
        """
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("100.0000"),
            source=TransactionSource.STRIPE,
            reference_id="bal-seq-alloc1",
        )
        await deduct_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("30.0000"),
            source=TransactionSource.USAGE,
            reference_id="bal-seq-deduct1",
        )
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("50.0000"),
            source=TransactionSource.ADJUSTMENT,
            reference_id="bal-seq-alloc2",
        )
        await deduct_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("20.0000"),
            source=TransactionSource.USAGE,
            reference_id="bal-seq-deduct2",
        )

        balance = await get_balance(session=db_session, user_id=test_user.id)
        assert balance == Decimal("100.0000")

    async def test_deduct_exact_balance_leaves_zero(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Deducting the exact remaining balance must leave 0.0000."""
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("100.0000"),
            source=TransactionSource.STRIPE,
            reference_id="bal-exact-alloc",
        )

        entry = await deduct_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("100.0000"),
            source=TransactionSource.USAGE,
            reference_id="bal-exact-deduct",
        )

        assert entry.balance_after == Decimal("0.0000")

        balance = await get_balance(session=db_session, user_id=test_user.id)
        assert balance == Decimal("0.0000")

    async def test_deduct_more_than_balance_raises(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Deducting more than available must raise InsufficientCreditsError
        with correct available and requested amounts.
        """
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("50.0000"),
            source=TransactionSource.STRIPE,
            reference_id="bal-over-alloc",
        )

        with pytest.raises(InsufficientCreditsError) as exc_info:
            await deduct_credits(
                session=db_session,
                user_id=test_user.id,
                amount=Decimal("51.0000"),
                source=TransactionSource.USAGE,
                reference_id="bal-over-deduct",
            )

        assert exc_info.value.available == Decimal("50.0000")
        assert exc_info.value.requested == Decimal("51.0000")
        assert exc_info.value.user_id == test_user.id

    async def test_zero_balance_deduct_raises(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Deducting from a user with no allocations (zero balance) must
        raise InsufficientCreditsError with available=0.
        """
        with pytest.raises(InsufficientCreditsError) as exc_info:
            await deduct_credits(
                session=db_session,
                user_id=test_user.id,
                amount=Decimal("1.0000"),
                source=TransactionSource.USAGE,
                reference_id="bal-zero-deduct",
            )

        assert exc_info.value.available == Decimal("0.0000")
        assert exc_info.value.requested == Decimal("1.0000")


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases: fractional precision, large values, multi-user isolation."""

    async def test_allocate_fractional_credits(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Allocate the minimum precision amount (0.0001) and verify balance."""
        entry = await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("0.0001"),
            source=TransactionSource.ADJUSTMENT,
            reference_id="edge-frac-alloc",
        )

        assert entry.balance_after == Decimal("0.0001")

        balance = await get_balance(session=db_session, user_id=test_user.id)
        assert balance == Decimal("0.0001")

    async def test_large_allocation(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Allocate the maximum Numeric(12,4) value and verify storage."""
        entry = await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("99999999.9999"),
            source=TransactionSource.STRIPE,
            reference_id="edge-large-alloc",
        )

        assert entry.balance_after == Decimal("99999999.9999")

        balance = await get_balance(session=db_session, user_id=test_user.id)
        assert balance == Decimal("99999999.9999")

    async def test_multiple_users_independent_balances(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Two users with separate allocations must have independent balances."""
        # Create second user inline
        user_b = User(
            email="userb@test.com",
            name="User B",
            hashed_password=bcrypt.hash("testpass"),
            is_active=True,
            is_admin=False,
        )
        db_session.add(user_b)
        await db_session.flush()

        # Allocate to user A (test_user)
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("100.0000"),
            source=TransactionSource.STRIPE,
            reference_id="edge-multi-a",
        )

        # Allocate to user B
        await allocate_credits(
            session=db_session,
            user_id=user_b.id,
            amount=Decimal("200.0000"),
            source=TransactionSource.STRIPE,
            reference_id="edge-multi-b",
        )

        balance_a = await get_balance(session=db_session, user_id=test_user.id)
        balance_b = await get_balance(session=db_session, user_id=user_b.id)

        assert balance_a == Decimal("100.0000")
        assert balance_b == Decimal("200.0000")
