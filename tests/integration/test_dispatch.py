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

"""Integration tests for job dispatch endpoint.

Covers:
1. Successful dispatch -- creates job, returns 201
2. No healthy nodes -- returns 503
3. No nodes with matching capability -- returns 503
4. Scheduler picks least-loaded node when multiple are available
5. Job record created in database with correct status
6. Unauthenticated request returns 401/403
7. Dispatch with missing fields returns 422
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from core.scheduler.models import EdgeNode, JobDispatch, JobStatus, NodeStatus

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
# Mock the Redis queue push (no Redis server in tests).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_redis_queue():
    with patch("core.scheduler.dispatch.push_to_queue", new_callable=AsyncMock) as mock_push:
        mock_push.return_value = True
        yield mock_push


# ---------------------------------------------------------------------------
# Helper: create an EdgeNode directly in the database.
# ---------------------------------------------------------------------------


def _make_node(
    *,
    name: str = "test-node",
    status: NodeStatus = NodeStatus.HEALTHY,
    capabilities: list[str] | None = None,
    current_load: float = 0.0,
    public_key: str = "ed25519-test-key",
    last_heartbeat: datetime.datetime | None = None,
) -> EdgeNode:
    """Create an EdgeNode instance (not yet persisted)."""
    return EdgeNode(
        public_key=public_key,
        name=name,
        capabilities=capabilities or ["render"],
        status=status,
        current_load=current_load,
        last_heartbeat=last_heartbeat or datetime.datetime.now(tz=datetime.UTC),
    )


# =========================================================================
# Test: Successful Dispatch
# =========================================================================


class TestSuccessfulDispatch:
    """POST /api/v1/jobs/dispatch with valid data and available nodes."""

    async def test_dispatch_returns_201(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Dispatch to a healthy node returns 201 with job details."""
        node = _make_node(name="gpu-node-1", capabilities=["render", "inference"])
        db_session.add(node)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render", "payload_ref": "s3://bucket/scene.blend"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "job_id" in data
        assert data["node_id"] == str(node.id)
        assert data["status"] == "DISPATCHED"

    async def test_dispatch_creates_db_record(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Dispatch creates a JobDispatch record in the database with correct status."""
        node = _make_node(
            name="db-check-node",
            capabilities=["render"],
            public_key="key-db-check",
        )
        db_session.add(node)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render", "payload_ref": "s3://bucket/job.blend"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        job_id = data["job_id"]

        # Verify DB record
        import uuid

        result = await db_session.execute(
            select(JobDispatch).where(JobDispatch.id == uuid.UUID(job_id))
        )
        job = result.scalar_one_or_none()
        assert job is not None
        assert job.status == JobStatus.DISPATCHED
        assert job.node_id == node.id
        assert job.job_type == "render"
        assert job.payload_ref == "s3://bucket/job.blend"
        assert job.dispatched_at is not None

    async def test_dispatch_pushes_to_redis_queue(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
        mock_redis_queue: AsyncMock,
    ) -> None:
        """Dispatch pushes the job payload to the Redis queue."""
        node = _make_node(
            name="redis-check-node",
            capabilities=["render"],
            public_key="key-redis-check",
        )
        db_session.add(node)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render", "payload_ref": "s3://bucket/redis.blend"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()

        mock_redis_queue.assert_called_once_with(
            node_id=str(node.id),
            job_id=data["job_id"],
            job_type="render",
            payload_ref="s3://bucket/redis.blend",
        )


# =========================================================================
# Test: No Healthy Nodes
# =========================================================================


class TestNoHealthyNodes:
    """POST /api/v1/jobs/dispatch when no suitable nodes exist."""

    async def test_no_nodes_returns_503(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """No nodes at all returns 503."""
        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render", "payload_ref": "s3://bucket/scene.blend"},
            headers=auth_headers,
        )
        assert resp.status_code == 503
        assert "No healthy nodes available for job type: render" in resp.json()["detail"]

    async def test_only_unhealthy_nodes_returns_503(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Only UNHEALTHY nodes returns 503."""
        node = _make_node(
            name="sick-node",
            status=NodeStatus.UNHEALTHY,
            capabilities=["render"],
            public_key="key-unhealthy",
        )
        db_session.add(node)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render", "payload_ref": "s3://bucket/scene.blend"},
            headers=auth_headers,
        )
        assert resp.status_code == 503

    async def test_no_matching_capability_returns_503(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Healthy node exists but without matching capability returns 503."""
        node = _make_node(
            name="gpu-node",
            status=NodeStatus.HEALTHY,
            capabilities=["inference"],
            public_key="key-no-cap",
        )
        db_session.add(node)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render", "payload_ref": "s3://bucket/scene.blend"},
            headers=auth_headers,
        )
        assert resp.status_code == 503
        assert "render" in resp.json()["detail"]


# =========================================================================
# Test: Least-Loaded Scheduling
# =========================================================================


class TestLeastLoadedScheduling:
    """Verify scheduler picks the least-loaded node among candidates."""

    async def test_picks_least_loaded_node(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """When multiple healthy nodes match, the one with lowest load is selected."""
        heavy_node = _make_node(
            name="heavy-node",
            capabilities=["render"],
            current_load=0.9,
            public_key="key-heavy",
        )
        light_node = _make_node(
            name="light-node",
            capabilities=["render"],
            current_load=0.1,
            public_key="key-light",
        )
        medium_node = _make_node(
            name="medium-node",
            capabilities=["render"],
            current_load=0.5,
            public_key="key-medium",
        )
        db_session.add(heavy_node)
        db_session.add(light_node)
        db_session.add(medium_node)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render", "payload_ref": "s3://bucket/scene.blend"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["node_id"] == str(light_node.id)

    async def test_skips_unhealthy_low_load_node(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """An UNHEALTHY node with lower load is not selected over a HEALTHY one."""
        unhealthy_idle = _make_node(
            name="idle-unhealthy",
            status=NodeStatus.UNHEALTHY,
            capabilities=["render"],
            current_load=0.0,
            public_key="key-uh-idle",
        )
        healthy_busy = _make_node(
            name="busy-healthy",
            status=NodeStatus.HEALTHY,
            capabilities=["render"],
            current_load=0.8,
            public_key="key-h-busy",
        )
        db_session.add(unhealthy_idle)
        db_session.add(healthy_busy)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render", "payload_ref": "s3://bucket/scene.blend"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["node_id"] == str(healthy_busy.id)


# =========================================================================
# Test: Authentication
# =========================================================================


class TestAuthentication:
    """Verify dispatch endpoint requires authentication."""

    async def test_unauthenticated_returns_401_or_403(
        self,
        client: AsyncClient,
    ) -> None:
        """No Authorization header returns 401 or 403."""
        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render", "payload_ref": "s3://bucket/scene.blend"},
        )
        assert resp.status_code in (401, 403)


# =========================================================================
# Test: Validation
# =========================================================================


class TestValidation:
    """Verify request body validation."""

    async def test_missing_job_type_returns_422(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Missing job_type field returns 422."""
        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"payload_ref": "s3://bucket/scene.blend"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_missing_payload_ref_returns_422(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Missing payload_ref field returns 422."""
        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_empty_body_returns_422(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Empty request body returns 422."""
        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_empty_job_type_returns_422(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Empty string for job_type returns 422 (min_length=1)."""
        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "", "payload_ref": "s3://bucket/scene.blend"},
            headers=auth_headers,
        )
        assert resp.status_code == 422
