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

"""Integration tests for job status API endpoints.

Covers:
- List jobs (empty, with data, with status filter, invalid status, pagination)
- Get job by ID (found, not found, invalid ID format)
- Cancel job (QUEUED success, DISPATCHED success, RUNNING fails, not found)
- Auth required (401 without token)
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

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
# Helpers
# ---------------------------------------------------------------------------


def _make_node(
    *,
    name: str = "test-node",
    status: NodeStatus = NodeStatus.HEALTHY,
    capabilities: list[str] | None = None,
    current_load: float = 0.0,
    public_key: str = "ed25519-test-key",
) -> EdgeNode:
    """Create an EdgeNode instance (not yet persisted)."""
    return EdgeNode(
        public_key=public_key,
        name=name,
        capabilities=capabilities or ["render"],
        status=status,
        current_load=current_load,
        last_heartbeat=datetime.datetime.now(tz=datetime.UTC),
    )


def _make_job(
    *,
    node: EdgeNode,
    job_type: str = "render",
    payload_ref: str = "s3://bucket/scene.blend",
    status: JobStatus = JobStatus.QUEUED,
    result_ref: str | None = None,
    error_message: str | None = None,
    retry_count: int = 0,
) -> JobDispatch:
    """Create a JobDispatch instance (not yet persisted)."""
    now = datetime.datetime.now(tz=datetime.UTC)
    return JobDispatch(
        node_id=node.id,
        job_type=job_type,
        payload_ref=payload_ref,
        status=status,
        queued_at=now,
        dispatched_at=now if status != JobStatus.QUEUED else None,
        result_ref=result_ref,
        error_message=error_message,
        retry_count=retry_count,
    )


# =========================================================================
# List Jobs Tests
# =========================================================================


class TestListJobs:
    """GET /api/v1/jobs endpoint tests."""

    async def test_list_jobs_empty(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """List jobs when no jobs exist returns 200 with empty list."""
        resp = await client.get("/api/v1/jobs", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["jobs"] == []
        assert data["count"] == 0

    async def test_list_jobs_with_data(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """List jobs returns all jobs when data exists."""
        node = _make_node(name="list-node")
        db_session.add(node)
        await db_session.flush()

        for i in range(3):
            job = _make_job(node=node, payload_ref=f"s3://bucket/scene-{i}.blend")
            db_session.add(job)
        await db_session.flush()

        resp = await client.get("/api/v1/jobs", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3
        assert len(data["jobs"]) == 3

        # Verify response schema fields are present
        job_resp = data["jobs"][0]
        assert "id" in job_resp
        assert "node_id" in job_resp
        assert "job_type" in job_resp
        assert "payload_ref" in job_resp
        assert "status" in job_resp
        assert "result_ref" in job_resp
        assert "error_message" in job_resp
        assert "retry_count" in job_resp
        assert "queued_at" in job_resp
        assert "created_at" in job_resp
        assert "updated_at" in job_resp

    async def test_list_jobs_status_filter(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """List jobs with status filter returns only matching jobs."""
        node = _make_node(name="filter-node", public_key="key-filter")
        db_session.add(node)
        await db_session.flush()

        queued_job = _make_job(node=node, status=JobStatus.QUEUED, payload_ref="s3://q")
        dispatched_job = _make_job(
            node=node, status=JobStatus.DISPATCHED, payload_ref="s3://d"
        )
        db_session.add(queued_job)
        db_session.add(dispatched_job)
        await db_session.flush()

        resp = await client.get(
            "/api/v1/jobs?status=QUEUED", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["jobs"][0]["status"] == "QUEUED"

    async def test_list_jobs_invalid_status_filter(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Invalid status filter returns 422."""
        resp = await client.get(
            "/api/v1/jobs?status=BOGUS", headers=auth_headers
        )
        assert resp.status_code == 422
        assert "Invalid status: BOGUS" in resp.json()["detail"]

    async def test_list_jobs_pagination(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Pagination returns correct slices of the job list."""
        node = _make_node(name="page-node", public_key="key-page")
        db_session.add(node)
        await db_session.flush()

        for i in range(5):
            job = _make_job(node=node, payload_ref=f"s3://bucket/page-{i}.blend")
            db_session.add(job)
        await db_session.flush()

        # First page: limit=2
        resp1 = await client.get(
            "/api/v1/jobs?limit=2&offset=0", headers=auth_headers
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert len(data1["jobs"]) == 2
        assert data1["count"] == 2

        # Second page: offset=2, limit=2
        resp2 = await client.get(
            "/api/v1/jobs?limit=2&offset=2", headers=auth_headers
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["jobs"]) == 2

        # Last page: offset=4, limit=2 -> 1 job
        resp3 = await client.get(
            "/api/v1/jobs?limit=2&offset=4", headers=auth_headers
        )
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert len(data3["jobs"]) == 1


# =========================================================================
# Get Job Tests
# =========================================================================


class TestGetJob:
    """GET /api/v1/jobs/{job_id} endpoint tests."""

    async def test_get_job_found(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Get an existing job by ID returns 200 with full details."""
        node = _make_node(name="get-node", public_key="key-get")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(
            node=node,
            job_type="inference",
            payload_ref="s3://bucket/model.bin",
            status=JobStatus.DISPATCHED,
        )
        db_session.add(job)
        await db_session.flush()

        resp = await client.get(
            f"/api/v1/jobs/{job.id}", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(job.id)
        assert data["node_id"] == str(node.id)
        assert data["job_type"] == "inference"
        assert data["payload_ref"] == "s3://bucket/model.bin"
        assert data["status"] == "DISPATCHED"
        assert data["retry_count"] == 0

    async def test_get_job_not_found(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Get a non-existent job returns 404."""
        resp = await client.get(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Job not found"

    async def test_get_job_invalid_id(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Invalid UUID format returns 422."""
        resp = await client.get(
            "/api/v1/jobs/not-a-uuid", headers=auth_headers
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Invalid job ID format"


# =========================================================================
# Cancel Job Tests
# =========================================================================


class TestCancelJob:
    """POST /api/v1/jobs/{job_id}/cancel endpoint tests."""

    async def test_cancel_queued_job(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Cancel a QUEUED job succeeds and returns FAILED status."""
        node = _make_node(name="cancel-q-node", public_key="key-cancel-q")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.QUEUED)
        db_session.add(job)
        await db_session.flush()

        resp = await client.post(
            f"/api/v1/jobs/{job.id}/cancel", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "FAILED"
        assert data["error_message"] == "Cancelled by user"
        assert data["id"] == str(job.id)

    async def test_cancel_dispatched_job(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Cancel a DISPATCHED job succeeds and returns FAILED status."""
        node = _make_node(name="cancel-d-node", public_key="key-cancel-d")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.DISPATCHED)
        db_session.add(job)
        await db_session.flush()

        resp = await client.post(
            f"/api/v1/jobs/{job.id}/cancel", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "FAILED"
        assert data["error_message"] == "Cancelled by user"

    async def test_cancel_running_job_fails(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Cancel a RUNNING job returns 400."""
        node = _make_node(name="cancel-r-node", public_key="key-cancel-r")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.RUNNING)
        db_session.add(job)
        await db_session.flush()

        resp = await client.post(
            f"/api/v1/jobs/{job.id}/cancel", headers=auth_headers
        )
        assert resp.status_code == 400
        assert "Cannot cancel job" in resp.json()["detail"]

    async def test_cancel_job_not_found(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Cancel a non-existent job returns 404."""
        resp = await client.post(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000/cancel",
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Job not found"


# =========================================================================
# Authentication Tests
# =========================================================================


class TestAuthentication:
    """Verify all endpoints require authentication."""

    async def test_list_jobs_unauthenticated(
        self,
        client: AsyncClient,
    ) -> None:
        """List jobs without auth returns 401 or 403."""
        resp = await client.get("/api/v1/jobs")
        assert resp.status_code in (401, 403)

    async def test_get_job_unauthenticated(
        self,
        client: AsyncClient,
    ) -> None:
        """Get job without auth returns 401 or 403."""
        resp = await client.get(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000"
        )
        assert resp.status_code in (401, 403)

    async def test_cancel_job_unauthenticated(
        self,
        client: AsyncClient,
    ) -> None:
        """Cancel job without auth returns 401 or 403."""
        resp = await client.post(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000/cancel"
        )
        assert resp.status_code in (401, 403)
