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

"""Integration tests for edge node registration and heartbeat.

Covers:
1. Node registration (success, idempotent duplicate key)
2. Heartbeat (success, status transition, load update)
3. Authentication enforcement (missing token, wrong token type)
4. Stale node detection via mark_stale_nodes service
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from core.auth.jwt import create_access_token
from core.scheduler.models import EdgeNode, NodeStatus
from core.scheduler.service import mark_stale_nodes

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Mock the Redis-backed token blacklist for all tests in this module.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_blacklist():
    with patch("core.auth.jwt.token_blacklist") as mock_bl:
        mock_bl.is_revoked = AsyncMock(return_value=False)
        yield mock_bl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_test_keypair():
    """Generate an Ed25519 keypair for testing."""
    private = Ed25519PrivateKey.generate()
    public_pem = (
        private.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private, public_pem


async def _register_node(
    client: AsyncClient,
    name: str = "test-node",
    public_key: str | None = None,
    capabilities: list[str] | None = None,
) -> dict:
    """Register a node via the API and return the response JSON."""
    if public_key is None:
        _, public_key = _generate_test_keypair()
    payload = {
        "name": name,
        "public_key": public_key,
        "capabilities": capabilities or ["gpu-render"],
    }
    resp = await client.post("/api/v1/nodes/register", json=payload)
    return resp.json(), resp.status_code


# =========================================================================
# Node Registration
# =========================================================================


class TestNodeRegistration:
    """Test node registration endpoint."""

    async def test_register_node_success(self, client: AsyncClient) -> None:
        """POST /api/v1/nodes/register with valid data returns 201."""
        _, public_pem = _generate_test_keypair()
        resp = await client.post(
            "/api/v1/nodes/register",
            json={
                "name": "gpu-node-1",
                "public_key": public_pem,
                "capabilities": ["gpu-render", "cpu-inference"],
            },
        )
        assert resp.status_code == 201

        data = resp.json()
        assert "node_id" in data
        assert "challenge" in data
        assert "token" in data
        assert data["status"] == "REGISTERED"
        # Challenge is 64-char hex
        assert len(data["challenge"]) == 64
        # Token is a JWT (3 dot-separated parts)
        assert data["token"].count(".") == 2

    async def test_register_node_duplicate_key(self, client: AsyncClient) -> None:
        """Same public_key returns existing node (idempotent re-registration)."""
        _, public_pem = _generate_test_keypair()
        payload = {
            "name": "gpu-node-dup",
            "public_key": public_pem,
            "capabilities": ["gpu-render"],
        }

        # First registration
        resp1 = await client.post("/api/v1/nodes/register", json=payload)
        assert resp1.status_code == 201
        data1 = resp1.json()

        # Second registration with same public key
        resp2 = await client.post("/api/v1/nodes/register", json=payload)
        assert resp2.status_code == 201
        data2 = resp2.json()

        # Same node ID returned
        assert data1["node_id"] == data2["node_id"]
        # But different challenge and token (new ones generated each time)
        assert data1["challenge"] != data2["challenge"]


# =========================================================================
# Heartbeat
# =========================================================================


class TestHeartbeat:
    """Test heartbeat endpoint."""

    async def test_heartbeat_success(self, client: AsyncClient) -> None:
        """Register node, then POST heartbeat with node JWT returns 200."""
        data, status_code = await _register_node(client)
        assert status_code == 201
        node_token = data["token"]

        resp = await client.post(
            "/api/v1/nodes/heartbeat",
            json={"current_load": 0.5},
            headers={"Authorization": f"Bearer {node_token}"},
        )
        assert resp.status_code == 200

        hb_data = resp.json()
        assert hb_data["node_id"] == data["node_id"]
        assert hb_data["acknowledged"] is True
        assert hb_data["status"] == "HEALTHY"

    async def test_heartbeat_transitions_to_healthy(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """New node starts REGISTERED, heartbeat transitions to HEALTHY."""
        data, _ = await _register_node(client)
        node_id = data["node_id"]
        node_token = data["token"]

        # Verify node starts as REGISTERED
        assert data["status"] == "REGISTERED"

        # Send heartbeat
        resp = await client.post(
            "/api/v1/nodes/heartbeat",
            json={"current_load": 0.1},
            headers={"Authorization": f"Bearer {node_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "HEALTHY"

        # Verify in DB
        result = await db_session.execute(select(EdgeNode).where(EdgeNode.id == uuid.UUID(node_id)))
        node = result.scalar_one_or_none()
        assert node is not None
        assert node.status == NodeStatus.HEALTHY

    async def test_heartbeat_updates_load(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Load value updated in DB after heartbeat."""
        data, _ = await _register_node(client)
        node_id = data["node_id"]
        node_token = data["token"]

        # Send heartbeat with load 0.75
        resp = await client.post(
            "/api/v1/nodes/heartbeat",
            json={"current_load": 0.75},
            headers={"Authorization": f"Bearer {node_token}"},
        )
        assert resp.status_code == 200

        # Verify load in DB
        result = await db_session.execute(select(EdgeNode).where(EdgeNode.id == uuid.UUID(node_id)))
        node = result.scalar_one_or_none()
        assert node is not None
        assert node.current_load == pytest.approx(0.75)

    async def test_heartbeat_without_auth_returns_401_or_403(self, client: AsyncClient) -> None:
        """No Bearer token on heartbeat returns 401 or 403."""
        resp = await client.post(
            "/api/v1/nodes/heartbeat",
            json={"current_load": 0.0},
        )
        # HTTPBearer returns 403 for missing header in some FastAPI versions
        assert resp.status_code in (401, 403)

    async def test_heartbeat_with_user_token_returns_401(
        self, client: AsyncClient, test_user
    ) -> None:
        """User JWT rejected as node token (token_type mismatch)."""
        user_token = create_access_token({"sub": str(test_user.id)})
        resp = await client.post(
            "/api/v1/nodes/heartbeat",
            json={"current_load": 0.0},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 401


# =========================================================================
# Stale node detection
# =========================================================================


class TestStaleNodeDetection:
    """Test mark_stale_nodes service function."""

    async def test_mark_stale_nodes(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """HEALTHY nodes with old heartbeat transition to UNHEALTHY."""
        # Register and send heartbeat to make node HEALTHY
        data, _ = await _register_node(client)
        node_id = data["node_id"]
        node_token = data["token"]

        resp = await client.post(
            "/api/v1/nodes/heartbeat",
            json={"current_load": 0.3},
            headers={"Authorization": f"Bearer {node_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "HEALTHY"

        # Manually backdate last_heartbeat to simulate staleness
        result = await db_session.execute(select(EdgeNode).where(EdgeNode.id == uuid.UUID(node_id)))
        node = result.scalar_one()
        node.last_heartbeat = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(
            seconds=120
        )
        session = db_session
        session.add(node)
        await session.flush()

        # Run stale detection
        count = await mark_stale_nodes(session)
        assert count == 1

        # Verify node is now UNHEALTHY
        result2 = await db_session.execute(
            select(EdgeNode).where(EdgeNode.id == uuid.UUID(node_id))
        )
        node2 = result2.scalar_one()
        assert node2.status == NodeStatus.UNHEALTHY
