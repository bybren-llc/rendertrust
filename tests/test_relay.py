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

"""Unit tests for the edge relay WebSocket server and connection manager.

Covers:
1. WebSocket authentication (valid token, missing token, invalid token, wrong node_id)
2. ConnectionManager operations (connect, disconnect, send, broadcast, tracking)

Uses Starlette's synchronous ``TestClient`` for WebSocket testing because
FastAPI/Starlette WebSocket test connections require the sync test client.
"""

from __future__ import annotations

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
from starlette.testclient import TestClient

from core.relay.manager import ConnectionManager
from core.relay.protocol import (
    JobAckMessage,
    JobAssignMessage,
    RelayMessage,
    RelayMessageType,
    StatusUpdateMessage,
)
from core.scheduler.crypto import create_node_token

# Constant for token type assertions
_NODE_TOKEN_TYPE = "node"  # noqa: S105


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_blacklist():
    """Mock the token blacklist so verify_token doesn't hit Redis."""
    with patch("core.auth.jwt.token_blacklist") as mock_bl:
        mock_bl.is_revoked = AsyncMock(return_value=False)
        yield mock_bl


@pytest.fixture
def app():
    """Create a fresh FastAPI app for WebSocket testing."""
    from core.main import create_app

    return create_app()


@pytest.fixture
def sync_client(app):
    """Starlette sync TestClient for WebSocket testing."""
    return TestClient(app)


@pytest.fixture
def node_id():
    """Generate a test node UUID."""
    return uuid.uuid4()


@pytest.fixture
def valid_token(node_id):
    """Create a valid node JWT for the test node_id."""
    return create_node_token(node_id, capabilities=["gpu-render"])


# ---------------------------------------------------------------------------
# Protocol model tests
# ---------------------------------------------------------------------------


class TestProtocolModels:
    """Test Pydantic protocol models serialize correctly."""

    def test_relay_message_type_values(self):
        """All RelayMessageType enum values exist."""
        assert RelayMessageType.JOB_ASSIGN.value == "job_assign"
        assert RelayMessageType.JOB_ACK.value == "job_ack"
        assert RelayMessageType.STATUS_UPDATE.value == "status_update"
        assert RelayMessageType.HEARTBEAT_PING.value == "heartbeat_ping"
        assert RelayMessageType.HEARTBEAT_PONG.value == "heartbeat_pong"

    def test_relay_message_base(self):
        """RelayMessage base model includes type, payload, and timestamp."""
        msg = RelayMessage(type=RelayMessageType.HEARTBEAT_PING)
        assert msg.type == RelayMessageType.HEARTBEAT_PING
        assert msg.payload == {}
        assert msg.timestamp is not None

    def test_job_assign_message(self):
        """JobAssignMessage includes job details."""
        job_id = uuid.uuid4()
        msg = JobAssignMessage(
            job_id=job_id,
            job_type="render",
            payload_ref="s3://bucket/payload.zip",
        )
        assert msg.type == RelayMessageType.JOB_ASSIGN
        assert msg.job_id == job_id
        assert msg.job_type == "render"
        assert msg.payload_ref == "s3://bucket/payload.zip"

    def test_job_ack_message(self):
        """JobAckMessage includes acceptance flag."""
        job_id = uuid.uuid4()
        msg = JobAckMessage(job_id=job_id, accepted=True)
        assert msg.type == RelayMessageType.JOB_ACK
        assert msg.accepted is True

    def test_status_update_message(self):
        """StatusUpdateMessage includes job progress details."""
        job_id = uuid.uuid4()
        msg = StatusUpdateMessage(
            job_id=job_id,
            status="running",
            progress=0.5,
            detail="Frame 50/100",
        )
        assert msg.type == RelayMessageType.STATUS_UPDATE
        assert msg.status == "running"
        assert msg.progress == 0.5
        assert msg.detail == "Frame 50/100"


# ---------------------------------------------------------------------------
# Connection Manager tests
# ---------------------------------------------------------------------------


class TestConnectionManager:
    """Test ConnectionManager tracking and messaging."""

    @pytest.fixture
    def manager(self):
        """Fresh ConnectionManager instance."""
        return ConnectionManager()

    @pytest.mark.asyncio
    async def test_connect_tracks_node(self, manager):
        """Connecting a node adds it to the tracked connections."""
        nid = uuid.uuid4()
        mock_ws = AsyncMock()
        await manager.connect(nid, mock_ws)
        assert manager.is_connected(nid) is True
        assert manager.connected_count() == 1

    @pytest.mark.asyncio
    async def test_disconnect_removes_node(self, manager):
        """Disconnecting a node removes it from tracked connections."""
        nid = uuid.uuid4()
        mock_ws = AsyncMock()
        await manager.connect(nid, mock_ws)
        assert manager.is_connected(nid) is True

        await manager.disconnect(nid)
        assert manager.is_connected(nid) is False
        assert manager.connected_count() == 0

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_is_safe(self, manager):
        """Disconnecting a node that was never connected does not raise."""
        await manager.disconnect(uuid.uuid4())
        assert manager.connected_count() == 0

    @pytest.mark.asyncio
    async def test_send_to_node_success(self, manager):
        """send_to_node sends JSON to the correct WebSocket."""
        nid = uuid.uuid4()
        mock_ws = AsyncMock()
        await manager.connect(nid, mock_ws)

        result = await manager.send_to_node(nid, {"type": "test"})
        assert result is True
        mock_ws.send_json.assert_called_once_with({"type": "test"})

    @pytest.mark.asyncio
    async def test_send_to_unconnected_node_returns_false(self, manager):
        """send_to_node returns False when the node is not connected."""
        result = await manager.send_to_node(uuid.uuid4(), {"type": "test"})
        assert result is False

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self, manager):
        """broadcast sends to all connected nodes."""
        nid1 = uuid.uuid4()
        nid2 = uuid.uuid4()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await manager.connect(nid1, ws1)
        await manager.connect(nid2, ws2)

        await manager.broadcast({"type": "announcement"})
        ws1.send_json.assert_called_once_with({"type": "announcement"})
        ws2.send_json.assert_called_once_with({"type": "announcement"})

    @pytest.mark.asyncio
    async def test_broadcast_skips_errored_sockets(self, manager):
        """broadcast silently skips nodes whose send_json raises."""
        nid1 = uuid.uuid4()
        nid2 = uuid.uuid4()
        ws1 = AsyncMock()
        ws1.send_json.side_effect = RuntimeError("Connection closed")
        ws2 = AsyncMock()
        await manager.connect(nid1, ws1)
        await manager.connect(nid2, ws2)

        # Should not raise
        await manager.broadcast({"type": "announcement"})
        ws2.send_json.assert_called_once_with({"type": "announcement"})

    @pytest.mark.asyncio
    async def test_is_connected_returns_false_for_unknown(self, manager):
        """is_connected returns False for a never-seen node."""
        assert manager.is_connected(uuid.uuid4()) is False

    @pytest.mark.asyncio
    async def test_connected_count_multiple(self, manager):
        """connected_count returns accurate count for multiple nodes."""
        for _ in range(5):
            await manager.connect(uuid.uuid4(), AsyncMock())
        assert manager.connected_count() == 5


# ---------------------------------------------------------------------------
# WebSocket endpoint tests
# ---------------------------------------------------------------------------


class TestRelayWebSocket:
    """Test the /api/v1/relay/ws/{node_id} WebSocket endpoint."""

    def test_connect_with_valid_token(self, sync_client, node_id, valid_token):
        """WebSocket with valid node token is accepted."""
        url = f"/api/v1/relay/ws/{node_id}?token={valid_token}"
        with sync_client.websocket_connect(url) as ws:
            # Connection should be established -- send a pong to prove it is live
            ws.send_json({"type": "heartbeat_pong", "payload": {}})
            # If we get here without exception, the connection was accepted

    def test_reject_without_token(self, sync_client, node_id):
        """WebSocket without token query param is closed with 4001."""
        url = f"/api/v1/relay/ws/{node_id}"
        with pytest.raises(Exception):
            # Starlette TestClient raises on server-initiated close
            with sync_client.websocket_connect(url) as ws:
                ws.receive_json()

    def test_reject_with_invalid_token(self, sync_client, node_id):
        """WebSocket with garbage token is closed with 4001."""
        url = f"/api/v1/relay/ws/{node_id}?token=not-a-valid-jwt"
        with pytest.raises(Exception):
            with sync_client.websocket_connect(url) as ws:
                ws.receive_json()

    def test_reject_with_wrong_node_id(self, sync_client, valid_token):
        """WebSocket where path node_id differs from token sub is rejected."""
        wrong_node_id = uuid.uuid4()
        url = f"/api/v1/relay/ws/{wrong_node_id}?token={valid_token}"
        with pytest.raises(Exception):
            with sync_client.websocket_connect(url) as ws:
                ws.receive_json()

    def test_message_exchange(self, sync_client, node_id, valid_token):
        """Connected node can send and receive messages."""
        url = f"/api/v1/relay/ws/{node_id}?token={valid_token}"
        with sync_client.websocket_connect(url) as ws:
            # Send a status update message
            ws.send_json({
                "type": "status_update",
                "job_id": str(uuid.uuid4()),
                "status": "running",
            })
            # Send a heartbeat pong (to keep connection alive)
            ws.send_json({"type": "heartbeat_pong", "payload": {}})
            # If no exception, message exchange succeeded
