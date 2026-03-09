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

"""Credit ledger service for allocating, deducting, and querying credits.

All operations are atomic and idempotent. Uses the CreditLedgerEntry model
with SELECT FOR UPDATE row locking for concurrent safety.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.models.base import CreditLedgerEntry, TransactionDirection, TransactionSource

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class InsufficientCreditsError(Exception):
    """Raised when a debit would cause a negative balance."""

    def __init__(self, user_id: uuid.UUID, requested: Decimal, available: Decimal) -> None:
        self.user_id = user_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient credits for user {user_id}: "
            f"requested {requested}, available {available}"
        )


async def allocate_credits(
    session: AsyncSession,
    user_id: uuid.UUID,
    amount: Decimal,
    source: TransactionSource,
    reference_id: str,
    description: str | None = None,
) -> CreditLedgerEntry:
    """Allocate credits to a user's account.

    Idempotent: if a CREDIT entry with the same reference_id already exists,
    returns the existing entry without creating a duplicate.

    Args:
        session: Async database session.
        user_id: UUID of the user to credit.
        amount: Positive credit amount.
        source: Source of the credit (STRIPE, ADJUSTMENT, REFUND).
        reference_id: External reference for idempotency.
        description: Optional human-readable description.

    Returns:
        The created (or existing) CreditLedgerEntry.

    Raises:
        ValueError: If amount is zero or negative.
    """
    if amount <= 0:
        msg = "Credit amount must be positive"
        raise ValueError(msg)

    # Check for existing entry (idempotency)
    existing = await session.execute(
        select(CreditLedgerEntry).where(
            CreditLedgerEntry.reference_id == reference_id,
            CreditLedgerEntry.direction == TransactionDirection.CREDIT,
        )
    )
    existing_entry = existing.scalar_one_or_none()
    if existing_entry is not None:
        logger.info(
            "credit_allocation_idempotent",
            reference_id=reference_id,
            user_id=str(user_id),
        )
        return existing_entry

    # Get current balance (last entry's balance_after, or 0 if first).
    # Use FOR UPDATE to prevent concurrent balance reads.
    last_entry_result = await session.execute(
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.user_id == user_id)
        .order_by(CreditLedgerEntry.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    last_entry = last_entry_result.scalar_one_or_none()
    current_balance = last_entry.balance_after if last_entry else Decimal("0.0000")

    new_balance = current_balance + amount

    entry = CreditLedgerEntry(
        user_id=user_id,
        amount=amount,
        direction=TransactionDirection.CREDIT,
        source=source,
        reference_id=reference_id,
        balance_after=new_balance,
        description=description,
    )
    session.add(entry)

    try:
        await session.flush()
    except IntegrityError:
        # Race condition: another transaction created the entry first.
        await session.rollback()
        existing = await session.execute(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.reference_id == reference_id,
                CreditLedgerEntry.direction == TransactionDirection.CREDIT,
            )
        )
        return existing.scalar_one()

    logger.info(
        "credits_allocated",
        user_id=str(user_id),
        amount=str(amount),
        source=source.value,
        reference_id=reference_id,
        new_balance=str(new_balance),
    )
    return entry


async def get_balance(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> Decimal:
    """Get the current credit balance for a user.

    Returns Decimal("0.0000") if the user has no ledger entries.
    """
    result = await session.execute(
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.user_id == user_id)
        .order_by(CreditLedgerEntry.created_at.desc())
        .limit(1)
    )
    last_entry = result.scalar_one_or_none()
    return last_entry.balance_after if last_entry else Decimal("0.0000")


async def deduct_credits(
    session: AsyncSession,
    user_id: uuid.UUID,
    amount: Decimal,
    source: TransactionSource,
    reference_id: str,
    description: str | None = None,
) -> CreditLedgerEntry:
    """Deduct credits from a user's account.

    Idempotent: if a DEBIT entry with the same reference_id already exists,
    returns the existing entry without creating a duplicate.

    Args:
        session: Async database session.
        user_id: UUID of the user to debit.
        amount: Positive debit amount.
        source: Source of the debit (USAGE, ADJUSTMENT).
        reference_id: External reference for idempotency.
        description: Optional human-readable description.

    Returns:
        The created (or existing) CreditLedgerEntry.

    Raises:
        ValueError: If amount is zero or negative.
        InsufficientCreditsError: If balance would go negative.
    """
    if amount <= 0:
        msg = "Debit amount must be positive"
        raise ValueError(msg)

    # Check for existing entry (idempotency)
    existing = await session.execute(
        select(CreditLedgerEntry).where(
            CreditLedgerEntry.reference_id == reference_id,
            CreditLedgerEntry.direction == TransactionDirection.DEBIT,
        )
    )
    existing_entry = existing.scalar_one_or_none()
    if existing_entry is not None:
        logger.info(
            "credit_deduction_idempotent",
            reference_id=reference_id,
            user_id=str(user_id),
        )
        return existing_entry

    # Get current balance (last entry's balance_after, or 0 if first).
    # Use FOR UPDATE to prevent concurrent balance reads.
    last_entry_result = await session.execute(
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.user_id == user_id)
        .order_by(CreditLedgerEntry.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    last_entry = last_entry_result.scalar_one_or_none()
    current_balance = last_entry.balance_after if last_entry else Decimal("0.0000")

    new_balance = current_balance - amount
    if new_balance < 0:
        raise InsufficientCreditsError(
            user_id=user_id,
            requested=amount,
            available=current_balance,
        )

    entry = CreditLedgerEntry(
        user_id=user_id,
        amount=amount,
        direction=TransactionDirection.DEBIT,
        source=source,
        reference_id=reference_id,
        balance_after=new_balance,
        description=description,
    )
    session.add(entry)

    try:
        await session.flush()
    except IntegrityError:
        # Race condition: another transaction created the entry first.
        await session.rollback()
        existing = await session.execute(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.reference_id == reference_id,
                CreditLedgerEntry.direction == TransactionDirection.DEBIT,
            )
        )
        return existing.scalar_one()

    logger.info(
        "credits_deducted",
        user_id=str(user_id),
        amount=str(amount),
        source=source.value,
        reference_id=reference_id,
        new_balance=str(new_balance),
    )
    return entry


_MAX_HISTORY_LIMIT = 100


async def get_history(
    session: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[CreditLedgerEntry]:
    """Return credit ledger entries for a user, newest first.

    Args:
        session: Async database session.
        user_id: UUID of the user whose history to retrieve.
        limit: Maximum number of entries to return (default 50, max 100).
        offset: Number of entries to skip for pagination.

    Returns:
        List of CreditLedgerEntry ordered by created_at descending.
    """
    # Silently clamp limit to the allowed maximum.
    clamped_limit = min(limit, _MAX_HISTORY_LIMIT)

    result = await session.execute(
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.user_id == user_id)
        .order_by(CreditLedgerEntry.created_at.desc())
        .limit(clamped_limit)
        .offset(offset)
    )
    return list(result.scalars().all())
