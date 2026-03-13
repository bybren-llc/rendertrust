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

"""Credit API endpoints for balance queries, history, and deductions.

Provides authenticated endpoints for users to check their credit balance,
view transaction history, and deduct credits for usage.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from core.auth.jwt import get_current_user
from core.database import get_db_session
from core.ledger.service import InsufficientCreditsError, deduct_credits, get_balance, get_history
from core.models.base import TransactionSource

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.models.base import User

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------


class BalanceResponse(BaseModel):
    """Credit balance response."""

    balance: str
    user_id: str


class LedgerEntryResponse(BaseModel):
    """Single ledger entry in history responses."""

    id: str
    amount: str
    direction: str
    source: str
    reference_id: str
    balance_after: str
    description: str | None
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class HistoryResponse(BaseModel):
    """Paginated credit history response."""

    entries: list[LedgerEntryResponse]
    count: int


class DeductRequest(BaseModel):
    """Credit deduction request body."""

    amount: str
    reference_id: str
    description: str | None = None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/credits")


# ---------------------------------------------------------------------------
# GET /credits/balance
# ---------------------------------------------------------------------------


@router.get("/balance", response_model=BalanceResponse)
async def credit_balance(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> BalanceResponse:
    """Return the current credit balance for the authenticated user."""
    balance = await get_balance(session=session, user_id=current_user.id)
    logger.info("balance_queried", user_id=str(current_user.id), balance=str(balance))
    return BalanceResponse(
        balance=str(balance),
        user_id=str(current_user.id),
    )


# ---------------------------------------------------------------------------
# GET /credits/history
# ---------------------------------------------------------------------------


@router.get("/history", response_model=HistoryResponse)
async def credit_history(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> HistoryResponse:
    """Return paginated credit transaction history for the authenticated user."""
    entries = await get_history(
        session=session,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    entry_responses = [
        LedgerEntryResponse(
            id=str(entry.id),
            amount=str(entry.amount),
            direction=entry.direction.value,
            source=entry.source.value,
            reference_id=entry.reference_id,
            balance_after=str(entry.balance_after),
            description=entry.description,
            created_at=entry.created_at.isoformat(),
        )
        for entry in entries
    ]
    logger.info(
        "history_queried",
        user_id=str(current_user.id),
        count=len(entry_responses),
        limit=limit,
        offset=offset,
    )
    return HistoryResponse(entries=entry_responses, count=len(entry_responses))


# ---------------------------------------------------------------------------
# POST /credits/deduct
# ---------------------------------------------------------------------------


@router.post("/deduct", response_model=LedgerEntryResponse)
async def credit_deduct(
    payload: DeductRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> LedgerEntryResponse | JSONResponse:
    """Deduct credits from the authenticated user's account.

    Returns 402 if the user has insufficient credits.
    Returns 422 if the amount is not a valid positive decimal.
    """
    try:
        amount = Decimal(payload.amount)
    except InvalidOperation as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid amount: {payload.amount}",
        ) from err

    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Amount must be a positive number",
        )

    try:
        entry = await deduct_credits(
            session=session,
            user_id=current_user.id,
            amount=amount,
            source=TransactionSource.USAGE,
            reference_id=payload.reference_id,
            description=payload.description,
        )
    except InsufficientCreditsError as err:
        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content={
                "detail": "Insufficient credits",
                "available": str(err.available),
                "requested": str(err.requested),
            },
        )

    await session.commit()

    logger.info(
        "credits_deducted_via_api",
        user_id=str(current_user.id),
        amount=str(amount),
        reference_id=payload.reference_id,
    )
    return LedgerEntryResponse(
        id=str(entry.id),
        amount=str(entry.amount),
        direction=entry.direction.value,
        source=entry.source.value,
        reference_id=entry.reference_id,
        balance_after=str(entry.balance_after),
        description=entry.description,
        created_at=entry.created_at.isoformat(),
    )
