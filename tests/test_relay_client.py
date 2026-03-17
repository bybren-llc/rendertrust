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

"""Unit tests for the edge relay WebSocket client.

Covers:
1. Client connects with valid token
2. Client responds to heartbeat ping with pong
3. Client calls on_job_assigned callback
4. Client sends job_ack on job receipt
5. Client sends status_update
6. Reconnection on disconnect
7. Exponential backoff timing
8. Disconnect method
9. send_status_update raises when not connected
10. Invalid JSON handling

Uses mocked WebSocket connections for unit testing.
"""

from __future__ import annotations

import json
import os
import uuid
from unittest.mock import AsyncMock, patch

# Environment overrides must come before application imports.
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_fake")

import pytest

from edgekit.relay.client import RelayClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def node_id():
    """Generate a test node UUID."""
    return uuid.uuid4()


@pytest.fixture
def token():
    """Fake JWT token for testing."""
    return "fake-jwt-token-for-testing"


@pytest.fixture
def server_url():
    """Test relay server URL."""
    return "ws://localhost:8000/api/v1"


@pytest.fixture
def job_callback():
    """Async mock callback for job assignments."""
    return AsyncMock()


@pytest.fixture
def client(server_url, node_id, token, job_callback):
    """Create a RelayClient instance with test parameters."""
    return RelayClient(
        server_url=server_url,
        node_id=node_id,
        token=token,
        on_job_assigned=job_callback,
        initial_backoff=0.01,
        max_backoff=0.1,
        backoff_multiplier=2.0,
    )


class _MockWebSocket:
    """Minimal mock WebSocket that supports async iteration and send/close."""

    def __init__(self, messages=None):
        self.send = AsyncMock()
        self.close = AsyncMock()
        self._messages = messages or []

    def __aiter__(self):
        return self._aiter_impl()

    async def _aiter_impl(self):
        for msg in self._messages:
            yield msg


class _DisconnectingMockWebSocket:
    """Mock WebSocket that raises ConnectionError on iteration."""

    def __init__(self):
        self.send = AsyncMock()
        self.close = AsyncMock()

    def __aiter__(self):
        return self._aiter_impl()

    async def _aiter_impl(self):
        raise ConnectionError("Connection lost")
        # unreachable, but required to make this an async generator
        yield  # pragma: no cover


def _make_mock_ws(messages=None):
    """Create a mock WebSocket connection that yields given messages.

    Args:
        messages: List of JSON-serializable dicts or raw strings to yield.

    Returns:
        A mock WebSocket with ``send``, ``close``, and async iteration.
    """
    raw_messages = []
    if messages is not None:
        for msg in messages:
            if isinstance(msg, dict):
                raw_messages.append(json.dumps(msg))
            else:
                raw_messages.append(msg)

    return _MockWebSocket(raw_messages)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRelayClientProperties:
    """Test basic client properties and URL construction."""

    def test_ws_url_construction(self, server_url, node_id, token):
        """ws_url includes node_id path and token query parameter."""
        client = RelayClient(
            server_url=server_url,
            node_id=node_id,
            token=token,
        )
        expected = f"{server_url}/relay/ws/{node_id}?token={token}"
        assert client.ws_url == expected

    def test_ws_url_strips_trailing_slash(self, node_id, token):
        """ws_url strips trailing slashes from server_url."""
        client = RelayClient(
            server_url="ws://localhost:8000/api/v1/",
            node_id=node_id,
            token=token,
        )
        assert "/v1//relay" not in client.ws_url
        assert "/v1/relay/ws/" in client.ws_url

    def test_initially_not_connected(self, client):
        """Client starts in disconnected state."""
        assert client.connected is False


class TestRelayClientConnect:
    """Test connection and disconnection."""

    @pytest.mark.asyncio
    async def test_connect_with_valid_token(self, client):
        """Client connects to relay server via websockets.connect."""
        mock_ws = _make_mock_ws()
        with patch("edgekit.relay.client.websockets.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = mock_ws
            await client.connect()
            mock_conn.assert_called_once_with(client.ws_url)
            assert client.connected is True

    @pytest.mark.asyncio
    async def test_disconnect_closes_connection(self, client):
        """disconnect() closes the WebSocket and sets connected to False."""
        mock_ws = _make_mock_ws()
        with patch("edgekit.relay.client.websockets.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = mock_ws
            await client.connect()
            assert client.connected is True

            await client.disconnect()
            mock_ws.close.assert_called_once()
            assert client.connected is False

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected_is_safe(self, client):
        """disconnect() when not connected does not raise."""
        await client.disconnect()
        assert client.connected is False


class TestRelayClientHeartbeat:
    """Test heartbeat ping/pong handling."""

    @pytest.mark.asyncio
    async def test_responds_to_heartbeat_ping_with_pong(self, client):
        """Client responds to heartbeat_ping with heartbeat_pong."""
        ping_msg = {"type": "heartbeat_ping", "payload": {}}
        mock_ws = _make_mock_ws(messages=[ping_msg])

        with patch("edgekit.relay.client.websockets.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = mock_ws
            await client.connect()
            await client._receive_loop()

        # Verify pong was sent
        mock_ws.send.assert_called_once()
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "heartbeat_pong"
        assert sent_data["payload"] == {}


class TestRelayClientJobAssignment:
    """Test job assignment handling."""

    @pytest.mark.asyncio
    async def test_calls_on_job_assigned_callback(self, client, job_callback):
        """Client invokes on_job_assigned callback when a job_assign message arrives."""
        job_id = str(uuid.uuid4())
        assign_msg = {
            "type": "job_assign",
            "job_id": job_id,
            "job_type": "render",
            "payload_ref": "s3://bucket/payload.zip",
        }
        mock_ws = _make_mock_ws(messages=[assign_msg])

        with patch("edgekit.relay.client.websockets.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = mock_ws
            await client.connect()
            await client._receive_loop()

        job_callback.assert_called_once_with(assign_msg)

    @pytest.mark.asyncio
    async def test_sends_job_ack_on_job_receipt(self, client, job_callback):
        """Client automatically sends job_ack when a job_assign is received."""
        job_id = str(uuid.uuid4())
        assign_msg = {
            "type": "job_assign",
            "job_id": job_id,
            "job_type": "inference",
            "payload_ref": "ipfs://Qm...",
        }
        mock_ws = _make_mock_ws(messages=[assign_msg])

        with patch("edgekit.relay.client.websockets.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = mock_ws
            await client.connect()
            await client._receive_loop()

        # The first send should be the job_ack
        assert mock_ws.send.call_count >= 1
        first_sent = json.loads(mock_ws.send.call_args_list[0][0][0])
        assert first_sent["type"] == "job_ack"
        assert first_sent["job_id"] == job_id
        assert first_sent["accepted"] is True


class TestRelayClientStatusUpdate:
    """Test status update sending."""

    @pytest.mark.asyncio
    async def test_sends_status_update(self, client):
        """send_status_update sends a properly formatted message."""
        mock_ws = _make_mock_ws()
        job_id = uuid.uuid4()

        with patch("edgekit.relay.client.websockets.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = mock_ws
            await client.connect()
            await client.send_status_update(
                job_id=job_id,
                status="running",
                progress=0.5,
                detail="Frame 50/100",
            )

        mock_ws.send.assert_called_once()
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "status_update"
        assert sent_data["job_id"] == str(job_id)
        assert sent_data["status"] == "running"
        assert sent_data["progress"] == 0.5
        assert sent_data["detail"] == "Frame 50/100"

    @pytest.mark.asyncio
    async def test_status_update_without_optional_fields(self, client):
        """send_status_update omits progress and detail when not provided."""
        mock_ws = _make_mock_ws()
        job_id = uuid.uuid4()

        with patch("edgekit.relay.client.websockets.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = mock_ws
            await client.connect()
            await client.send_status_update(job_id=job_id, status="completed")

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "status_update"
        assert sent_data["status"] == "completed"
        assert "progress" not in sent_data
        assert "detail" not in sent_data

    @pytest.mark.asyncio
    async def test_status_update_raises_when_not_connected(self, client):
        """send_status_update raises RuntimeError when not connected."""
        with pytest.raises(RuntimeError, match="Not connected"):
            await client.send_status_update(
                job_id=uuid.uuid4(),
                status="running",
            )

    @pytest.mark.asyncio
    async def test_job_ack_raises_when_not_connected(self, client):
        """send_job_ack raises RuntimeError when not connected."""
        with pytest.raises(RuntimeError, match="Not connected"):
            await client.send_job_ack(job_id=uuid.uuid4())


class TestRelayClientReconnection:
    """Test reconnection with exponential backoff."""

    @pytest.mark.asyncio
    async def test_reconnection_on_disconnect(self, client):
        """Client reconnects when the WebSocket connection is lost."""
        connect_count = 0
        max_connects = 3

        async def mock_connect(url):
            nonlocal connect_count
            connect_count += 1
            if connect_count >= max_connects:
                # Stop the run loop after enough reconnect attempts
                client._running = False
            return _DisconnectingMockWebSocket()

        with patch("edgekit.relay.client.websockets.connect", side_effect=mock_connect):
            await client.run()

        # Should have attempted to connect multiple times
        assert connect_count >= 2

    @pytest.mark.asyncio
    async def test_exponential_backoff_timing(self, client):
        """Backoff delay doubles on each reconnection attempt."""
        sleep_durations = []
        connect_count = 0
        max_connects = 4

        async def mock_connect(url):
            nonlocal connect_count
            connect_count += 1
            if connect_count >= max_connects:
                client._running = False
            raise ConnectionRefusedError("Server unavailable")

        async def mock_sleep(duration):
            sleep_durations.append(duration)
            # Don't actually sleep in tests

        with (
            patch("edgekit.relay.client.websockets.connect", side_effect=mock_connect),
            patch("edgekit.relay.client.asyncio.sleep", side_effect=mock_sleep),
        ):
            await client.run()

        # With initial_backoff=0.01 and multiplier=2.0:
        # First retry: 0.01, second: 0.02, third: 0.04
        assert len(sleep_durations) >= 2
        assert sleep_durations[0] == pytest.approx(0.01)
        assert sleep_durations[1] == pytest.approx(0.02)
        if len(sleep_durations) >= 3:
            assert sleep_durations[2] == pytest.approx(0.04)

    @pytest.mark.asyncio
    async def test_backoff_respects_max(self, server_url, node_id, token, job_callback):
        """Backoff does not exceed max_backoff."""
        sleep_durations = []
        connect_count = 0
        max_connects = 6

        # Use tiny backoff values to test cap quickly
        c = RelayClient(
            server_url=server_url,
            node_id=node_id,
            token=token,
            on_job_assigned=job_callback,
            initial_backoff=0.01,
            max_backoff=0.05,
            backoff_multiplier=2.0,
        )

        async def mock_connect(url):
            nonlocal connect_count
            connect_count += 1
            if connect_count >= max_connects:
                c._running = False
            raise ConnectionRefusedError("Server unavailable")

        async def mock_sleep(duration):
            sleep_durations.append(duration)

        with (
            patch("edgekit.relay.client.websockets.connect", side_effect=mock_connect),
            patch("edgekit.relay.client.asyncio.sleep", side_effect=mock_sleep),
        ):
            await c.run()

        # All backoff values should be <= max_backoff
        for d in sleep_durations:
            assert d <= 0.05 + 1e-9  # small tolerance for float math


class TestRelayClientInvalidMessages:
    """Test handling of malformed messages."""

    @pytest.mark.asyncio
    async def test_invalid_json_is_handled_gracefully(self, client):
        """Client handles invalid JSON without crashing."""
        mock_ws = _make_mock_ws(messages=["not valid json {{{"])

        with patch("edgekit.relay.client.websockets.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = mock_ws
            await client.connect()
            # Should not raise
            await client._receive_loop()

    @pytest.mark.asyncio
    async def test_unknown_message_type_is_handled(self, client):
        """Client handles unknown message types without crashing."""
        unknown_msg = {"type": "unknown_type", "data": "something"}
        mock_ws = _make_mock_ws(messages=[unknown_msg])

        with patch("edgekit.relay.client.websockets.connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = mock_ws
            await client.connect()
            # Should not raise
            await client._receive_loop()
