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

"""Integration tests for fleet listing and node health endpoints.

Covers:
- Admin-only fleet listing (200 for admin, 403 for regular user)
- Listing with data, status filtering, and pagination
- Node health detail (200, 404 for unknown UUID, 422 for invalid format)
- Unauthenticated access rejection (401/403)
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from core.scheduler.models import EdgeNode, NodeStatus

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.models.base import User


# ---------------------------------------------------------------------------
# Mock the Redis-backed token blacklist for all tests in this module.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_blacklist():
    with patch("core.auth.jwt.token_blacklist") as mock_bl:
        mock_bl.is_revoked = AsyncMock(return_value=False)
        yield mock_bl


# ---------------------------------------------------------------------------
# Fleet client fixture: mount the fleet router onto the test app.
# ---------------------------------------------------------------------------


@pytest.fixture
async def fleet_client(client: AsyncClient) -> AsyncClient:
    """Return the test client with the fleet router mounted at /api/v1."""
    app = client._transport.app  # type: ignore[union-attr]
    from core.scheduler.fleet import router as fleet_router

    app.include_router(fleet_router, prefix="/api/v1")
    return client


# ---------------------------------------------------------------------------
# Helper: create an EdgeNode directly in the database.
# ---------------------------------------------------------------------------


def _make_node(
    *,
    name: str = "test-node",
    status: NodeStatus = NodeStatus.REGISTERED,
    capabilities: list[str] | None = None,
    current_load: float = 0.0,
    public_key: str = "ed25519-test-key",
    last_heartbeat: datetime.datetime | None = None,
    metadata_: dict | None = None,
) -> EdgeNode:
    """Create an EdgeNode instance (not yet persisted)."""
    return EdgeNode(
        public_key=public_key,
        name=name,
        capabilities=capabilities or ["gpu", "render"],
        status=status,
        current_load=current_load,
        last_heartbeat=last_heartbeat,
        metadata_=metadata_,
    )


# =========================================================================
# Fleet listing tests
# =========================================================================


class TestListNodesAdmin:
    """Admin fleet listing endpoint: GET /api/v1/fleet."""

    async def test_list_nodes_admin_returns_200_empty(
        self,
        fleet_client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict,
    ) -> None:
        """Admin user listing fleet with no nodes returns 200 and empty list."""
        resp = await fleet_client.get(
            "/api/v1/fleet",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []
        assert data["total"] == 0
        assert data["limit"] == 50
        assert data["offset"] == 0

    async def test_list_nodes_non_admin_returns_403(
        self,
        fleet_client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Regular (non-admin) user gets 403 Forbidden."""
        resp = await fleet_client.get(
            "/api/v1/fleet",
            headers=auth_headers,
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Admin access required"

    async def test_list_nodes_with_data(
        self,
        fleet_client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
        admin_auth_headers: dict,
    ) -> None:
        """Create 3 nodes and verify admin can list them all."""
        for i in range(3):
            node = _make_node(name=f"node-{i}", public_key=f"key-{i}")
            db_session.add(node)
        await db_session.flush()

        resp = await fleet_client.get(
            "/api/v1/fleet",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["nodes"]) == 3

    async def test_list_nodes_status_filter(
        self,
        fleet_client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
        admin_auth_headers: dict,
    ) -> None:
        """Filter nodes by status returns only matching nodes."""
        healthy_node = _make_node(
            name="healthy-node",
            status=NodeStatus.HEALTHY,
            public_key="key-healthy",
        )
        unhealthy_node = _make_node(
            name="unhealthy-node",
            status=NodeStatus.UNHEALTHY,
            public_key="key-unhealthy",
        )
        db_session.add(healthy_node)
        db_session.add(unhealthy_node)
        await db_session.flush()

        # Filter for HEALTHY only
        resp = await fleet_client.get(
            "/api/v1/fleet?status=HEALTHY",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["status"] == "HEALTHY"
        assert data["nodes"][0]["name"] == "healthy-node"

    async def test_list_nodes_invalid_status_filter(
        self,
        fleet_client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict,
    ) -> None:
        """Invalid status filter returns 422 with valid values hint."""
        resp = await fleet_client.get(
            "/api/v1/fleet?status=BOGUS",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 422
        assert "Invalid status: BOGUS" in resp.json()["detail"]

    async def test_list_nodes_pagination(
        self,
        fleet_client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
        admin_auth_headers: dict,
    ) -> None:
        """Pagination returns correct slices of the node list."""
        for i in range(5):
            node = _make_node(name=f"page-node-{i}", public_key=f"page-key-{i}")
            db_session.add(node)
        await db_session.flush()

        # First page: limit=2, offset=0 -> 2 nodes, total=5
        resp1 = await fleet_client.get(
            "/api/v1/fleet?limit=2&offset=0",
            headers=admin_auth_headers,
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert len(data1["nodes"]) == 2
        assert data1["total"] == 5
        assert data1["limit"] == 2
        assert data1["offset"] == 0

        # Last page: offset=4 -> 1 node
        resp2 = await fleet_client.get(
            "/api/v1/fleet?limit=2&offset=4",
            headers=admin_auth_headers,
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["nodes"]) == 1
        assert data2["total"] == 5


# =========================================================================
# Node health detail tests
# =========================================================================


class TestNodeHealth:
    """Node health detail endpoint: GET /api/v1/fleet/{node_id}/health."""

    async def test_node_health_returns_detail(
        self,
        fleet_client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Authenticated user can query a node's health detail."""
        node = _make_node(
            name="detail-node",
            status=NodeStatus.HEALTHY,
            capabilities=["gpu", "render", "ai"],
            current_load=0.42,
            metadata_={"region": "us-east-1"},
            last_heartbeat=datetime.datetime.now(tz=datetime.UTC),
        )
        db_session.add(node)
        await db_session.flush()

        resp = await fleet_client.get(
            f"/api/v1/fleet/{node.id}/health",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(node.id)
        assert data["name"] == "detail-node"
        assert data["status"] == "HEALTHY"
        assert data["capabilities"] == ["gpu", "render", "ai"]
        assert data["current_load"] == 0.42
        assert data["last_heartbeat"] is not None
        assert data["uptime_seconds"] is not None
        assert data["uptime_seconds"] >= 0
        assert data["metadata"] == {"region": "us-east-1"}
        assert data["created_at"] is not None

    async def test_node_health_not_found(
        self,
        fleet_client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Unknown UUID returns 404."""
        resp = await fleet_client.get(
            "/api/v1/fleet/00000000-0000-0000-0000-000000000000/health",
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Node not found"

    async def test_node_health_invalid_id(
        self,
        fleet_client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Non-UUID node_id returns 422."""
        resp = await fleet_client.get(
            "/api/v1/fleet/not-a-uuid/health",
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Invalid node ID format"


# =========================================================================
# Unauthenticated access
# =========================================================================


class TestUnauthenticated:
    """Verify unauthenticated requests are rejected."""

    async def test_list_nodes_unauthenticated_returns_401_or_403(
        self,
        fleet_client: AsyncClient,
    ) -> None:
        """No Authorization header returns 401 or 403."""
        resp = await fleet_client.get("/api/v1/fleet")
        assert resp.status_code in (401, 403)

    async def test_node_health_unauthenticated_returns_401_or_403(
        self,
        fleet_client: AsyncClient,
    ) -> None:
        """No Authorization header on health endpoint returns 401 or 403."""
        resp = await fleet_client.get(
            "/api/v1/fleet/00000000-0000-0000-0000-000000000000/health"
        )
        assert resp.status_code in (401, 403)
