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

"""Tests for the auto-scale trigger fleet load monitoring service.

Covers:
- get_fleet_load calculates correct average
- get_fleet_load returns 0.0 with no healthy nodes
- get_fleet_load excludes UNHEALTHY/OFFLINE nodes
- check_and_scale emits scale_up when load > 80%
- check_and_scale emits scale_down when load < 20%
- check_and_scale returns None for normal load (20-80%)
- Cooldown prevents repeated scale_up within 5 minutes
- Cooldown prevents repeated scale_down within 5 minutes
- Cooldown allows scale_up after 5 minutes
- emit_scale_event publishes to correct Redis channel
- emit_scale_event fails open when Redis unavailable
- Event payload includes avg_load and node_count
- reset clears cooldown state
- Thresholds are configurable constants
"""

from __future__ import annotations

import datetime
import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.scheduler.autoscale import (
    COOLDOWN_PERIOD,
    SCALE_DOWN_CHANNEL,
    SCALE_DOWN_THRESHOLD,
    SCALE_UP_CHANNEL,
    SCALE_UP_THRESHOLD,
    AutoScaleMonitor,
)
from core.scheduler.models import EdgeNode, NodeStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def monitor() -> AutoScaleMonitor:
    """Return a fresh AutoScaleMonitor instance for each test."""
    return AutoScaleMonitor()


@pytest.fixture
async def healthy_node_high_load(db_session: AsyncSession) -> EdgeNode:
    """Create a HEALTHY node with high load (0.9)."""
    node = EdgeNode(
        name="autoscale-node-high",
        public_key="autoscale-pubkey-high",
        capabilities=["render"],
        status=NodeStatus.HEALTHY,
        current_load=0.9,
    )
    db_session.add(node)
    await db_session.flush()
    return node


@pytest.fixture
async def healthy_node_low_load(db_session: AsyncSession) -> EdgeNode:
    """Create a HEALTHY node with low load (0.1)."""
    node = EdgeNode(
        name="autoscale-node-low",
        public_key="autoscale-pubkey-low",
        capabilities=["render"],
        status=NodeStatus.HEALTHY,
        current_load=0.1,
    )
    db_session.add(node)
    await db_session.flush()
    return node


@pytest.fixture
async def healthy_node_mid_load(db_session: AsyncSession) -> EdgeNode:
    """Create a HEALTHY node with mid-range load (0.5)."""
    node = EdgeNode(
        name="autoscale-node-mid",
        public_key="autoscale-pubkey-mid",
        capabilities=["render"],
        status=NodeStatus.HEALTHY,
        current_load=0.5,
    )
    db_session.add(node)
    await db_session.flush()
    return node


@pytest.fixture
async def unhealthy_node(db_session: AsyncSession) -> EdgeNode:
    """Create an UNHEALTHY node."""
    node = EdgeNode(
        name="autoscale-node-unhealthy",
        public_key="autoscale-pubkey-unhealthy",
        capabilities=["render"],
        status=NodeStatus.UNHEALTHY,
        current_load=0.95,
    )
    db_session.add(node)
    await db_session.flush()
    return node


@pytest.fixture
async def offline_node(db_session: AsyncSession) -> EdgeNode:
    """Create an OFFLINE node."""
    node = EdgeNode(
        name="autoscale-node-offline",
        public_key="autoscale-pubkey-offline",
        capabilities=["render"],
        status=NodeStatus.OFFLINE,
        current_load=0.0,
    )
    db_session.add(node)
    await db_session.flush()
    return node


# ---------------------------------------------------------------------------
# get_fleet_load tests
# ---------------------------------------------------------------------------


async def test_get_fleet_load_calculates_correct_average(
    db_session: AsyncSession,
    monitor: AutoScaleMonitor,
    healthy_node_high_load: EdgeNode,
    healthy_node_low_load: EdgeNode,
) -> None:
    """get_fleet_load returns the correct average of healthy nodes' load."""
    avg = await monitor.get_fleet_load(db_session)
    # (0.9 + 0.1) / 2 = 0.5
    assert avg == pytest.approx(0.5, abs=0.01)


async def test_get_fleet_load_returns_zero_with_no_healthy_nodes(
    db_session: AsyncSession,
    monitor: AutoScaleMonitor,
) -> None:
    """get_fleet_load returns 0.0 when no healthy nodes exist."""
    avg = await monitor.get_fleet_load(db_session)
    assert avg == 0.0


async def test_get_fleet_load_excludes_unhealthy_and_offline_nodes(
    db_session: AsyncSession,
    monitor: AutoScaleMonitor,
    healthy_node_low_load: EdgeNode,
    unhealthy_node: EdgeNode,
    offline_node: EdgeNode,
) -> None:
    """get_fleet_load only considers HEALTHY nodes, excluding UNHEALTHY/OFFLINE."""
    avg = await monitor.get_fleet_load(db_session)
    # Only the healthy node (0.1) should be counted
    assert avg == pytest.approx(0.1, abs=0.01)


# ---------------------------------------------------------------------------
# check_and_scale tests
# ---------------------------------------------------------------------------


async def test_check_and_scale_emits_scale_up_when_load_above_threshold(
    db_session: AsyncSession,
    monitor: AutoScaleMonitor,
    healthy_node_high_load: EdgeNode,
) -> None:
    """check_and_scale emits scale_up when avg load > SCALE_UP_THRESHOLD."""
    with patch.object(monitor, "emit_scale_event", new_callable=AsyncMock) as mock_emit:
        mock_emit.return_value = True
        result = await monitor.check_and_scale(db_session)

    assert result == "scale_up"
    mock_emit.assert_called_once_with(SCALE_UP_CHANNEL, pytest.approx(0.9, abs=0.01), 1)


async def test_check_and_scale_emits_scale_down_when_load_below_threshold(
    db_session: AsyncSession,
    monitor: AutoScaleMonitor,
    healthy_node_low_load: EdgeNode,
) -> None:
    """check_and_scale emits scale_down when avg load < SCALE_DOWN_THRESHOLD."""
    with patch.object(monitor, "emit_scale_event", new_callable=AsyncMock) as mock_emit:
        mock_emit.return_value = True
        result = await monitor.check_and_scale(db_session)

    assert result == "scale_down"
    mock_emit.assert_called_once_with(SCALE_DOWN_CHANNEL, pytest.approx(0.1, abs=0.01), 1)


async def test_check_and_scale_returns_none_for_normal_load(
    db_session: AsyncSession,
    monitor: AutoScaleMonitor,
    healthy_node_mid_load: EdgeNode,
) -> None:
    """check_and_scale returns None when load is within normal range (20-80%)."""
    with patch.object(monitor, "emit_scale_event", new_callable=AsyncMock) as mock_emit:
        result = await monitor.check_and_scale(db_session)

    assert result is None
    mock_emit.assert_not_called()


# ---------------------------------------------------------------------------
# Cooldown tests
# ---------------------------------------------------------------------------


async def test_cooldown_prevents_repeated_scale_up(
    db_session: AsyncSession,
    monitor: AutoScaleMonitor,
    healthy_node_high_load: EdgeNode,
) -> None:
    """Cooldown prevents repeated scale_up within COOLDOWN_PERIOD."""
    with patch.object(monitor, "emit_scale_event", new_callable=AsyncMock) as mock_emit:
        mock_emit.return_value = True
        # First call should emit
        result1 = await monitor.check_and_scale(db_session)
        assert result1 == "scale_up"

        # Second call within cooldown should NOT emit
        result2 = await monitor.check_and_scale(db_session)
        assert result2 is None

    # emit_scale_event should have been called only once
    assert mock_emit.call_count == 1


async def test_cooldown_prevents_repeated_scale_down(
    db_session: AsyncSession,
    monitor: AutoScaleMonitor,
    healthy_node_low_load: EdgeNode,
) -> None:
    """Cooldown prevents repeated scale_down within COOLDOWN_PERIOD."""
    with patch.object(monitor, "emit_scale_event", new_callable=AsyncMock) as mock_emit:
        mock_emit.return_value = True
        # First call should emit
        result1 = await monitor.check_and_scale(db_session)
        assert result1 == "scale_down"

        # Second call within cooldown should NOT emit
        result2 = await monitor.check_and_scale(db_session)
        assert result2 is None

    assert mock_emit.call_count == 1


async def test_cooldown_allows_scale_up_after_period(
    db_session: AsyncSession,
    monitor: AutoScaleMonitor,
    healthy_node_high_load: EdgeNode,
) -> None:
    """Cooldown allows scale_up after COOLDOWN_PERIOD has elapsed."""
    with patch.object(monitor, "emit_scale_event", new_callable=AsyncMock) as mock_emit:
        mock_emit.return_value = True

        # First call
        result1 = await monitor.check_and_scale(db_session)
        assert result1 == "scale_up"

        # Simulate cooldown period elapsed
        monitor._last_scale_up = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(
            seconds=COOLDOWN_PERIOD + 1
        )

        # Second call after cooldown should emit again
        result2 = await monitor.check_and_scale(db_session)
        assert result2 == "scale_up"

    assert mock_emit.call_count == 2


# ---------------------------------------------------------------------------
# emit_scale_event tests
# ---------------------------------------------------------------------------


async def test_emit_scale_event_publishes_to_correct_channel(
    monitor: AutoScaleMonitor,
) -> None:
    """emit_scale_event publishes to the specified Redis channel."""
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock(return_value=1)
    mock_redis.aclose = AsyncMock()

    with patch("core.scheduler.autoscale.aioredis") as mock_aioredis:
        mock_aioredis.from_url.return_value = mock_redis
        result = await monitor.emit_scale_event(SCALE_UP_CHANNEL, 0.85, 5)

    assert result is True
    mock_redis.publish.assert_called_once()
    call_args = mock_redis.publish.call_args
    assert call_args[0][0] == SCALE_UP_CHANNEL


async def test_emit_scale_event_fails_open_when_redis_unavailable(
    monitor: AutoScaleMonitor,
) -> None:
    """emit_scale_event returns False when Redis is unavailable."""
    with patch("core.scheduler.autoscale.aioredis") as mock_aioredis:
        mock_aioredis.from_url.side_effect = ConnectionError("Redis unavailable")
        result = await monitor.emit_scale_event(SCALE_UP_CHANNEL, 0.85, 5)

    assert result is False


async def test_emit_scale_event_payload_includes_avg_load_and_node_count(
    monitor: AutoScaleMonitor,
) -> None:
    """Event payload JSON includes avg_load and node_count fields."""
    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock(return_value=1)
    mock_redis.aclose = AsyncMock()
    published_payload = None

    async def capture_publish(channel, payload):
        nonlocal published_payload
        published_payload = payload
        return 1

    mock_redis.publish = capture_publish

    with patch("core.scheduler.autoscale.aioredis") as mock_aioredis:
        mock_aioredis.from_url.return_value = mock_redis
        await monitor.emit_scale_event(SCALE_DOWN_CHANNEL, 0.15, 3)

    assert published_payload is not None
    data = json.loads(published_payload)
    assert data["avg_load"] == pytest.approx(0.15, abs=0.01)
    assert data["node_count"] == 3
    assert data["event"] == SCALE_DOWN_CHANNEL
    assert "timestamp" in data


# ---------------------------------------------------------------------------
# reset tests
# ---------------------------------------------------------------------------


async def test_reset_clears_cooldown_state(
    monitor: AutoScaleMonitor,
) -> None:
    """reset() clears both scale-up and scale-down cooldown timestamps."""
    monitor._last_scale_up = datetime.datetime.now(tz=datetime.UTC)
    monitor._last_scale_down = datetime.datetime.now(tz=datetime.UTC)

    monitor.reset()

    assert monitor._last_scale_up is None
    assert monitor._last_scale_down is None


# ---------------------------------------------------------------------------
# Threshold constants tests
# ---------------------------------------------------------------------------


def test_thresholds_are_configurable_constants() -> None:
    """Verify threshold constants have expected values and are importable."""
    assert SCALE_UP_THRESHOLD == 0.8
    assert SCALE_DOWN_THRESHOLD == 0.2
    assert COOLDOWN_PERIOD == 300
    assert SCALE_UP_CHANNEL == "fleet:scale_up"
    assert SCALE_DOWN_CHANNEL == "fleet:scale_down"
