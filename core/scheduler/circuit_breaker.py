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

"""Circuit breaker for edge node failure detection and recovery.

Tracks consecutive job failures per node and automatically transitions
nodes to UNHEALTHY when failures exceed a threshold.  After a recovery
timeout the node enters a "half-open" state where a single probe job is
allowed through to test whether the node has recovered.

State machine::

    HEALTHY ──(failures >= FAILURE_THRESHOLD)──> UNHEALTHY
    UNHEALTHY ──(RECOVERY_TIMEOUT elapsed)──> half-open (probe)
    half-open ──(probe succeeds)──> HEALTHY
    half-open ──(probe fails)──> UNHEALTHY (timer resets)

Usage:
    from core.scheduler.circuit_breaker import circuit_breaker

    # On job failure
    new_status = await circuit_breaker.record_failure(session, node_id)

    # On job success
    await circuit_breaker.record_success(session, node_id)

    # Before dispatching to a node
    effective_status = await circuit_breaker.check_node_health(session, node_id)
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select, update

from core.scheduler.models import EdgeNode, JobDispatch, JobStatus, NodeStatus

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FAILURE_THRESHOLD: int = 3
"""Number of consecutive failures before a node is tripped to UNHEALTHY."""

RECOVERY_TIMEOUT: int = 300
"""Seconds after the last failure before the circuit enters half-open."""


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """In-memory circuit breaker tracking consecutive node failures.

    Thread-safety note: this implementation is designed for a single
    async event loop (FastAPI/uvicorn).  For multi-process deployments
    the failure state should be moved to Redis.
    """

    def __init__(self) -> None:
        self._failure_counts: dict[uuid.UUID, int] = {}
        self._last_failure_time: dict[uuid.UUID, datetime.datetime] = {}
        self._half_open: set[uuid.UUID] = set()

    # -- Recording ----------------------------------------------------------

    async def record_failure(
        self,
        session: AsyncSession,
        node_id: uuid.UUID,
    ) -> NodeStatus:
        """Record a job failure against *node_id*.

        Increments the failure counter.  When the counter reaches
        ``FAILURE_THRESHOLD`` the node is transitioned to UNHEALTHY in
        the database and queued/dispatched jobs are redistributed.

        Args:
            session: Async database session.
            node_id: UUID of the node that failed the job.

        Returns:
            The node's status after recording the failure.
        """
        count = self._failure_counts.get(node_id, 0) + 1
        self._failure_counts[node_id] = count
        self._last_failure_time[node_id] = datetime.datetime.now(tz=datetime.UTC)

        logger.info(
            "circuit_breaker_failure_recorded",
            node_id=str(node_id),
            failure_count=count,
            threshold=FAILURE_THRESHOLD,
        )

        if count >= FAILURE_THRESHOLD:
            # Trip the breaker -- transition node to UNHEALTHY
            await session.execute(
                update(EdgeNode)
                .where(EdgeNode.id == node_id)
                .values(status=NodeStatus.UNHEALTHY)
            )
            await session.flush()

            logger.warning(
                "circuit_breaker_tripped",
                node_id=str(node_id),
                failure_count=count,
            )

            # Redistribute jobs away from the unhealthy node
            redistributed = await self.redistribute_jobs(session, node_id)
            logger.info(
                "circuit_breaker_jobs_redistributed",
                node_id=str(node_id),
                redistributed_count=redistributed,
            )

            # Clear half-open if it was set
            self._half_open.discard(node_id)

            return NodeStatus.UNHEALTHY

        return NodeStatus.HEALTHY

    async def record_success(
        self,
        session: AsyncSession,
        node_id: uuid.UUID,
    ) -> None:
        """Record a successful job completion for *node_id*.

        Resets the failure counter and ensures the node is HEALTHY.
        If the node was in a half-open probe state, it is fully restored.

        Args:
            session: Async database session.
            node_id: UUID of the node that succeeded.
        """
        old_count = self._failure_counts.get(node_id, 0)
        was_half_open = node_id in self._half_open

        # Reset failure tracking
        self._failure_counts.pop(node_id, None)
        self._last_failure_time.pop(node_id, None)
        self._half_open.discard(node_id)

        # Ensure node is HEALTHY in the database
        await session.execute(
            update(EdgeNode)
            .where(EdgeNode.id == node_id)
            .values(status=NodeStatus.HEALTHY)
        )
        await session.flush()

        if old_count > 0 or was_half_open:
            logger.info(
                "circuit_breaker_reset",
                node_id=str(node_id),
                previous_failure_count=old_count,
                was_half_open=was_half_open,
            )

    # -- Health checking ----------------------------------------------------

    async def check_node_health(
        self,
        session: AsyncSession,
        node_id: uuid.UUID,
    ) -> NodeStatus:
        """Return the effective health status of *node_id*.

        If the node is UNHEALTHY and ``RECOVERY_TIMEOUT`` has elapsed
        since the last failure, the node enters a half-open state where
        one probe job is allowed.  The return value will be ``HEALTHY``
        to signal that the scheduler may try the node.

        Args:
            session: Async database session.
            node_id: UUID of the node to check.

        Returns:
            Effective ``NodeStatus``.
        """
        result = await session.execute(
            select(EdgeNode).where(EdgeNode.id == node_id)
        )
        node = result.scalar_one_or_none()
        if node is None:
            return NodeStatus.OFFLINE

        if node.status != NodeStatus.UNHEALTHY:
            return node.status

        # Node is UNHEALTHY -- check recovery timeout
        last_failure = self._last_failure_time.get(node_id)
        if last_failure is None:
            # No tracked failure (maybe server restarted) -- stay UNHEALTHY
            return NodeStatus.UNHEALTHY

        elapsed = (datetime.datetime.now(tz=datetime.UTC) - last_failure).total_seconds()
        if elapsed >= RECOVERY_TIMEOUT:
            # Enter half-open: allow one probe
            self._half_open.add(node_id)
            logger.info(
                "circuit_breaker_half_open",
                node_id=str(node_id),
                elapsed_seconds=elapsed,
            )
            return NodeStatus.HEALTHY  # signal: allow a probe dispatch

        return NodeStatus.UNHEALTHY

    # -- Job redistribution -------------------------------------------------

    async def redistribute_jobs(
        self,
        session: AsyncSession,
        node_id: uuid.UUID,
    ) -> int:
        """Move QUEUED and DISPATCHED jobs off *node_id* so they can be re-scheduled.

        Jobs in QUEUED or DISPATCHED state assigned to the unhealthy node
        are transitioned back to QUEUED.  The scheduler's ``find_best_node``
        will reassign them on the next dispatch cycle.

        Jobs in RUNNING, COMPLETED, or FAILED state are left untouched.

        Args:
            session: Async database session.
            node_id: UUID of the unhealthy node.

        Returns:
            Number of jobs redistributed.
        """
        result = await session.execute(
            select(JobDispatch).where(
                JobDispatch.node_id == node_id,
                JobDispatch.status.in_([JobStatus.QUEUED, JobStatus.DISPATCHED]),
            )
        )
        jobs = list(result.scalars().all())

        for job in jobs:
            job.status = JobStatus.QUEUED
            job.dispatched_at = None
            session.add(job)

        if jobs:
            await session.flush()

        logger.info(
            "redistribute_jobs_complete",
            node_id=str(node_id),
            count=len(jobs),
        )

        return len(jobs)

    # -- Testing helpers ----------------------------------------------------

    def reset(self, node_id: uuid.UUID) -> None:
        """Clear all failure tracking state for *node_id*.

        Intended for use in tests to reset the circuit breaker between
        test cases without creating a new instance.

        Args:
            node_id: UUID of the node to reset.
        """
        self._failure_counts.pop(node_id, None)
        self._last_failure_time.pop(node_id, None)
        self._half_open.discard(node_id)


# Module-level singleton used across the application.
circuit_breaker = CircuitBreaker()
