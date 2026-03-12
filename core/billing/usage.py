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

"""Usage tracking service for automatic credit deduction on job completion.

Provides pricing lookup (DB -> default -> fallback), pre-flight balance
checks, and idempotent deduction via the credit ledger service.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from core.billing.models import JobPricing
from core.ledger.service import deduct_credits, get_balance
from core.models.base import TransactionSource

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from core.models.base import CreditLedgerEntry
    from core.scheduler.models import JobDispatch

logger = structlog.get_logger(__name__)

# Default per-job-type pricing used when no DB pricing row exists.
DEFAULT_PRICING: dict[str, Decimal] = {
    "render": Decimal("10.0"),
    "inference": Decimal("5.0"),
    "echo": Decimal("0.0"),
    "cpu_benchmark": Decimal("1.0"),
}

# Fallback price when job_type is not in DB or DEFAULT_PRICING.
_FALLBACK_PRICE = Decimal("1.0")


async def get_job_price(session: AsyncSession, job_type: str) -> Decimal:
    """Look up the credit price for a given job type.

    Resolution order:
      1. Active row in the ``job_pricing`` table.
      2. ``DEFAULT_PRICING`` dict.
      3. Fallback of ``Decimal("1.0")``.

    Args:
        session: Async database session.
        job_type: The job type identifier (e.g. 'render', 'inference').

    Returns:
        Credit cost as a Decimal.
    """
    result = await session.execute(
        select(JobPricing).where(
            JobPricing.job_type == job_type,
            JobPricing.is_active.is_(True),
        )
    )
    pricing = result.scalar_one_or_none()

    if pricing is not None:
        logger.debug("job_price_from_db", job_type=job_type, price=str(pricing.credits_per_unit))
        return pricing.credits_per_unit

    default = DEFAULT_PRICING.get(job_type)
    if default is not None:
        logger.debug("job_price_from_default", job_type=job_type, price=str(default))
        return default

    logger.warning("job_price_fallback", job_type=job_type, price=str(_FALLBACK_PRICE))
    return _FALLBACK_PRICE


async def deduct_on_completion(
    session: AsyncSession,
    job: JobDispatch,
    user_id: uuid.UUID,
) -> CreditLedgerEntry:
    """Calculate cost for a completed job and deduct credits from the user.

    Uses the credit ledger's idempotency (reference_id) to prevent
    double-deduction if called multiple times for the same job.

    Args:
        session: Async database session.
        job: The completed JobDispatch instance.
        user_id: UUID of the user who owns the job.

    Returns:
        The CreditLedgerEntry created (or existing, if idempotent).

    Raises:
        InsufficientCreditsError: If the user's balance is too low.
        ValueError: If the computed cost is zero or negative (free jobs
            should be filtered before calling this function, but the
            ledger service will reject non-positive amounts).
    """
    cost = await get_job_price(session, job.job_type)
    reference_id = f"job-{job.id}"

    logger.info(
        "deducting_usage_credits",
        job_id=str(job.id),
        job_type=job.job_type,
        user_id=str(user_id),
        cost=str(cost),
        reference_id=reference_id,
    )

    entry = await deduct_credits(
        session=session,
        user_id=user_id,
        amount=cost,
        source=TransactionSource.USAGE,
        reference_id=reference_id,
        description=f"Usage charge for {job.job_type} job {job.id}",
    )

    logger.info(
        "usage_credits_deducted",
        job_id=str(job.id),
        user_id=str(user_id),
        cost=str(cost),
        balance_after=str(entry.balance_after),
    )
    return entry


async def check_sufficient_credits(
    session: AsyncSession,
    user_id: uuid.UUID,
    job_type: str,
) -> bool:
    """Pre-flight check: does the user have enough credits for this job type?

    Returns True immediately for free job types (price == 0).

    Args:
        session: Async database session.
        user_id: UUID of the user to check.
        job_type: The job type to price.

    Returns:
        True if the user can afford the job, False otherwise.
    """
    price = await get_job_price(session, job_type)

    if price <= 0:
        return True

    balance = await get_balance(session, user_id)
    has_enough = balance >= price

    logger.debug(
        "credit_sufficiency_check",
        user_id=str(user_id),
        job_type=job_type,
        price=str(price),
        balance=str(balance),
        sufficient=has_enough,
    )
    return has_enough
