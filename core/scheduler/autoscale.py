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

"""Auto-scale trigger for fleet-level load monitoring.

Periodically queries fleet average load across all HEALTHY edge nodes
and emits scale-up / scale-down events via Redis pubsub when thresholds
are crossed.  A cooldown period prevents rapid-fire duplicate events.

Usage::

    from core.scheduler.autoscale import autoscale_monitor

    # In a background task / scheduler loop
    action = await autoscale_monitor.check_and_scale(session)

    # Reset cooldown state (testing)
    autoscale_monitor.reset()
"""

from __future__ import annotations

import datetime
import json
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
import structlog
from sqlalchemy import select

from core.config import get_settings
from core.scheduler.models import EdgeNode, NodeStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCALE_UP_THRESHOLD: float = 0.8
"""Fleet average load above this value triggers a scale-up event."""

SCALE_DOWN_THRESHOLD: float = 0.2
"""Fleet average load below this value triggers a scale-down event."""

CHECK_INTERVAL: int = 60
"""Seconds between successive fleet load checks."""

COOLDOWN_PERIOD: int = 300
"""Seconds between same-type scale events (5 minutes)."""

SCALE_UP_CHANNEL: str = "fleet:scale_up"
"""Redis pubsub channel for scale-up events."""

SCALE_DOWN_CHANNEL: str = "fleet:scale_down"
"""Redis pubsub channel for scale-down events."""


# ---------------------------------------------------------------------------
# AutoScaleMonitor
# ---------------------------------------------------------------------------


class AutoScaleMonitor:
    """Fleet-level load monitor that emits scale events via Redis pubsub.

    Tracks cooldown state in-memory to prevent rapid-fire duplicate
    scale events.  Designed for a single async event loop
    (FastAPI/uvicorn).
    """

    def __init__(self) -> None:
        self._last_scale_up: datetime.datetime | None = None
        self._last_scale_down: datetime.datetime | None = None

    # -- Fleet load ---------------------------------------------------------

    async def get_fleet_load(self, session: AsyncSession) -> float:
        """Calculate the average ``current_load`` of all HEALTHY nodes.

        Args:
            session: Async database session.

        Returns:
            Average load as a float in [0.0, 1.0], or 0.0 if there are
            no healthy nodes.
        """
        result = await session.execute(
            select(EdgeNode).where(EdgeNode.status == NodeStatus.HEALTHY)
        )
        nodes = list(result.scalars().all())

        if not nodes:
            logger.info("fleet_load_no_healthy_nodes")
            return 0.0

        avg_load = sum(n.current_load for n in nodes) / len(nodes)

        logger.info(
            "fleet_load_calculated",
            avg_load=round(avg_load, 4),
            healthy_node_count=len(nodes),
        )
        return avg_load

    # -- Event emission -----------------------------------------------------

    async def emit_scale_event(
        self,
        channel: str,
        avg_load: float,
        node_count: int,
    ) -> bool:
        """Publish a JSON scale event to a Redis pubsub channel.

        Fail-open: if Redis is unavailable a warning is logged and the
        method returns ``False`` without raising.

        Args:
            channel: Redis pubsub channel name.
            avg_load: Current fleet average load.
            node_count: Number of healthy nodes at time of check.

        Returns:
            ``True`` if the event was published, ``False`` otherwise.
        """
        settings = get_settings()
        payload = json.dumps(
            {
                "event": channel,
                "avg_load": round(avg_load, 4),
                "node_count": node_count,
                "timestamp": datetime.datetime.now(tz=datetime.UTC).isoformat(),
            }
        )

        try:
            r = aioredis.from_url(settings.redis_url)
            try:
                await r.publish(channel, payload)
                logger.info(
                    "scale_event_emitted",
                    channel=channel,
                    avg_load=round(avg_load, 4),
                    node_count=node_count,
                )
                return True
            finally:
                await r.aclose()
        except Exception:
            logger.warning(
                "scale_event_redis_unavailable",
                channel=channel,
                avg_load=round(avg_load, 4),
                node_count=node_count,
                operation="emit_scale_event",
            )
            return False

    # -- Cooldown helpers ---------------------------------------------------

    def _is_cooled_down(self, last_event: datetime.datetime | None) -> bool:
        """Return ``True`` if enough time has passed since *last_event*."""
        if last_event is None:
            return True
        elapsed = (datetime.datetime.now(tz=datetime.UTC) - last_event).total_seconds()
        return elapsed >= COOLDOWN_PERIOD

    # -- Main check ---------------------------------------------------------

    async def check_and_scale(self, session: AsyncSession) -> str | None:
        """Evaluate fleet load and emit a scale event if warranted.

        1. Query average fleet load across HEALTHY nodes.
        2. Compare against thresholds.
        3. Respect cooldown periods.
        4. Emit a Redis pubsub event if thresholds are crossed.

        Args:
            session: Async database session.

        Returns:
            ``"scale_up"`` if a scale-up event was emitted,
            ``"scale_down"`` if a scale-down event was emitted,
            or ``None`` if no action was taken.
        """
        # Query fleet load
        result = await session.execute(
            select(EdgeNode).where(EdgeNode.status == NodeStatus.HEALTHY)
        )
        nodes = list(result.scalars().all())
        node_count = len(nodes)

        avg_load = 0.0 if not nodes else sum(n.current_load for n in nodes) / len(nodes)

        logger.info(
            "autoscale_check",
            avg_load=round(avg_load, 4),
            node_count=node_count,
        )

        # Check scale-up threshold
        if avg_load > SCALE_UP_THRESHOLD:
            if self._is_cooled_down(self._last_scale_up):
                await self.emit_scale_event(SCALE_UP_CHANNEL, avg_load, node_count)
                self._last_scale_up = datetime.datetime.now(tz=datetime.UTC)
                return "scale_up"
            logger.info(
                "autoscale_cooldown_active",
                direction="scale_up",
                avg_load=round(avg_load, 4),
            )
            return None

        # Check scale-down threshold
        if avg_load < SCALE_DOWN_THRESHOLD:
            if self._is_cooled_down(self._last_scale_down):
                await self.emit_scale_event(SCALE_DOWN_CHANNEL, avg_load, node_count)
                self._last_scale_down = datetime.datetime.now(tz=datetime.UTC)
                return "scale_down"
            logger.info(
                "autoscale_cooldown_active",
                direction="scale_down",
                avg_load=round(avg_load, 4),
            )
            return None

        # Load is within normal range
        return None

    # -- Testing helpers ----------------------------------------------------

    def reset(self) -> None:
        """Clear all cooldown state.

        Intended for use in tests to reset the monitor between test
        cases without creating a new instance.
        """
        self._last_scale_up = None
        self._last_scale_down = None


# Module-level singleton used across the application.
autoscale_monitor = AutoScaleMonitor()
