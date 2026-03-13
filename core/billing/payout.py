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

"""Payout service for calculating and distributing node operator earnings.

Queries completed jobs for edge nodes in a given month, calculates
revenue shares (70% operator / 30% platform), and creates idempotent
ledger credit entries for operator payouts.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import func, select

from core.billing.usage import get_job_price
from core.ledger.service import allocate_credits
from core.models.base import TransactionSource
from core.scheduler.models import JobDispatch, JobStatus

if TYPE_CHECKING:
    import uuid
    from datetime import date

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# Revenue split: 70% to node operator, 30% platform.
OPERATOR_SHARE = Decimal("0.70")
PLATFORM_SHARE = Decimal("0.30")


@dataclass(frozen=True)
class PayoutSummary:
    """Summary of payout calculations for a single node in a given month.

    Attributes:
        node_id: UUID of the edge node.
        month: The billing month (first day of month).
        total_jobs: Number of completed jobs in the month.
        gross_revenue: Total revenue from all completed jobs.
        operator_earnings: Operator's share (gross_revenue * OPERATOR_SHARE).
        platform_fee: Platform's share (gross_revenue * PLATFORM_SHARE).
        is_paid: Whether a ledger entry has been created for this payout.
    """

    node_id: uuid.UUID
    month: date
    total_jobs: int
    gross_revenue: Decimal
    operator_earnings: Decimal
    platform_fee: Decimal
    is_paid: bool = False


def _month_boundaries(month: date) -> tuple[date, date]:
    """Return the first day of the given month and the first day of the next month.

    Args:
        month: Any date within the target month.

    Returns:
        Tuple of (first_day_of_month, first_day_of_next_month).
    """
    first_day = month.replace(day=1)
    if first_day.month == 12:
        next_month = first_day.replace(year=first_day.year + 1, month=1)
    else:
        next_month = first_day.replace(month=first_day.month + 1)
    return first_day, next_month


async def _get_completed_jobs(
    session: AsyncSession,
    node_id: uuid.UUID,
    month: date,
) -> list[JobDispatch]:
    """Fetch all COMPLETED jobs for a node within the given month.

    Args:
        session: Async database session.
        node_id: UUID of the edge node.
        month: Any date within the target month.

    Returns:
        List of completed JobDispatch records.
    """
    first_day, next_month = _month_boundaries(month)
    result = await session.execute(
        select(JobDispatch).where(
            JobDispatch.node_id == node_id,
            JobDispatch.status == JobStatus.COMPLETED,
            JobDispatch.completed_at >= first_day,
            JobDispatch.completed_at < next_month,
        )
    )
    return list(result.scalars().all())


async def _get_active_node_ids(
    session: AsyncSession,
    month: date,
) -> list[uuid.UUID]:
    """Return distinct node IDs that have COMPLETED jobs in the given month.

    Args:
        session: Async database session.
        month: Any date within the target month.

    Returns:
        List of unique node UUIDs with completed jobs.
    """
    first_day, next_month = _month_boundaries(month)
    result = await session.execute(
        select(func.distinct(JobDispatch.node_id)).where(
            JobDispatch.status == JobStatus.COMPLETED,
            JobDispatch.completed_at >= first_day,
            JobDispatch.completed_at < next_month,
        )
    )
    return list(result.scalars().all())


async def calculate_earnings(
    session: AsyncSession,
    node_id: uuid.UUID,
    month: date,
) -> PayoutSummary:
    """Calculate earnings for a single node in a given month.

    Queries all COMPLETED jobs for the node in the target month,
    sums revenue using per-job-type pricing, and applies the
    operator/platform revenue split.

    Args:
        session: Async database session.
        node_id: UUID of the edge node.
        month: Any date within the target month.

    Returns:
        PayoutSummary with calculated earnings.
    """
    jobs = await _get_completed_jobs(session, node_id, month)

    gross_revenue = Decimal("0")
    for job in jobs:
        price = await get_job_price(session, job.job_type)
        gross_revenue += price

    operator_earnings = gross_revenue * OPERATOR_SHARE
    platform_fee = gross_revenue * PLATFORM_SHARE

    logger.info(
        "earnings_calculated",
        node_id=str(node_id),
        month=month.isoformat(),
        total_jobs=len(jobs),
        gross_revenue=str(gross_revenue),
        operator_earnings=str(operator_earnings),
        platform_fee=str(platform_fee),
    )

    return PayoutSummary(
        node_id=node_id,
        month=month.replace(day=1),
        total_jobs=len(jobs),
        gross_revenue=gross_revenue,
        operator_earnings=operator_earnings,
        platform_fee=platform_fee,
    )


async def generate_payout_report(
    session: AsyncSession,
    month: date,
) -> list[PayoutSummary]:
    """Generate payout summaries for all nodes with completed jobs in the month.

    Args:
        session: Async database session.
        month: Any date within the target month.

    Returns:
        List of PayoutSummary for each active node.
    """
    node_ids = await _get_active_node_ids(session, month)

    summaries: list[PayoutSummary] = []
    for nid in node_ids:
        summary = await calculate_earnings(session, nid, month)
        summaries.append(summary)

    logger.info(
        "payout_report_generated",
        month=month.isoformat(),
        total_nodes=len(summaries),
        total_gross=str(sum(s.gross_revenue for s in summaries)),
    )

    return summaries


async def execute_payouts(
    session: AsyncSession,
    month: date,
) -> list[PayoutSummary]:
    """Generate payout report and create ledger credit entries for each operator.

    Idempotent: uses reference_id format ``payout-{node_id}-{month}``
    to prevent double-payment via the ledger service's built-in
    idempotency check.

    Args:
        session: Async database session.
        month: Any date within the target month.

    Returns:
        List of PayoutSummary with is_paid=True for each successful payout.
    """
    summaries = await generate_payout_report(session, month)
    paid_summaries: list[PayoutSummary] = []

    for summary in summaries:
        if summary.operator_earnings <= 0:
            logger.info(
                "payout_skipped_zero_earnings",
                node_id=str(summary.node_id),
                month=month.isoformat(),
            )
            paid_summaries.append(summary)
            continue

        canonical_month = month.replace(day=1)
        reference_id = f"payout-{summary.node_id}-{canonical_month.isoformat()}"

        await allocate_credits(
            session=session,
            user_id=summary.node_id,
            amount=summary.operator_earnings,
            source=TransactionSource.ADJUSTMENT,
            reference_id=reference_id,
            description=(
                f"Operator payout for {canonical_month.isoformat()}: "
                f"{summary.total_jobs} jobs, gross {summary.gross_revenue}"
            ),
        )

        paid_summary = PayoutSummary(
            node_id=summary.node_id,
            month=summary.month,
            total_jobs=summary.total_jobs,
            gross_revenue=summary.gross_revenue,
            operator_earnings=summary.operator_earnings,
            platform_fee=summary.platform_fee,
            is_paid=True,
        )
        paid_summaries.append(paid_summary)

        logger.info(
            "payout_executed",
            node_id=str(summary.node_id),
            month=canonical_month.isoformat(),
            operator_earnings=str(summary.operator_earnings),
            reference_id=reference_id,
        )

    logger.info(
        "payouts_batch_complete",
        month=month.isoformat(),
        total_paid=sum(1 for s in paid_summaries if s.is_paid),
        total_skipped=sum(1 for s in paid_summaries if not s.is_paid),
    )

    return paid_summaries
