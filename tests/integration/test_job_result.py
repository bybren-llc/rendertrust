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

"""Integration tests for GET /api/v1/jobs/{job_id}/result endpoint.

Covers:
1.  Completed job with result_ref returns presigned URL (happy path)
2.  Response schema includes job_id, download_url, expires_in
3.  Presigned URL has 1-hour default expiry (3600 seconds)
4.  Job not found returns 404
5.  Incomplete job (QUEUED) returns 404 with descriptive message
6.  Incomplete job (RUNNING) returns 404 with descriptive message
7.  Incomplete job (DISPATCHED) returns 404 with descriptive message
8.  Failed job returns 404 with descriptive message
9.  Completed job without result_ref returns 404
10. Invalid UUID format returns 422
11. Unauthenticated request returns 401/403
12. StorageService is called with correct key and expiry

[REN-103]
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

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
# Mock the StorageService so tests don't need a real S3/MinIO backend.
# ---------------------------------------------------------------------------

MOCK_PRESIGNED_URL = "https://s3.example.com/presigned/user123/job456/result?X-Amz-Signature=abc123"


@pytest.fixture(autouse=True)
def mock_storage_service():
    """Patch StorageService in the jobs module to avoid real S3 calls."""
    mock_storage_instance = MagicMock()
    mock_storage_instance.generate_presigned_url.return_value = MOCK_PRESIGNED_URL

    with patch("core.api.v1.jobs.StorageService") as mock_cls:
        mock_cls.return_value = mock_storage_instance
        yield mock_storage_instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(
    *,
    name: str = "result-test-node",
    status: NodeStatus = NodeStatus.HEALTHY,
    capabilities: list[str] | None = None,
    current_load: float = 0.0,
    public_key: str = "ed25519-result-test-key",
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
        completed_at=now if status in (JobStatus.COMPLETED, JobStatus.FAILED) else None,
        result_ref=result_ref,
        error_message=error_message,
        retry_count=retry_count,
    )


# =========================================================================
# 1. Happy Path -- Completed Job with Result
# =========================================================================


class TestGetJobResultHappyPath:
    """GET /api/v1/jobs/{job_id}/result returns presigned URL for completed jobs."""

    async def test_completed_job_returns_presigned_url(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Completed job with result_ref returns 200 with presigned download URL."""
        node = _make_node(name="result-ok", public_key="key-result-ok")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(
            node=node,
            status=JobStatus.COMPLETED,
            result_ref="user123/job456/result.zip",
        )
        db_session.add(job)
        await db_session.flush()

        resp = await client.get(f"/api/v1/jobs/{job.id}/result", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["download_url"] == MOCK_PRESIGNED_URL
        assert data["job_id"] == str(job.id)

    async def test_response_schema_contains_required_fields(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Response includes job_id, download_url, and expires_in."""
        node = _make_node(name="schema-node", public_key="key-schema")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(
            node=node,
            status=JobStatus.COMPLETED,
            result_ref="user1/job1/output.exr",
        )
        db_session.add(job)
        await db_session.flush()

        resp = await client.get(f"/api/v1/jobs/{job.id}/result", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert "download_url" in data
        assert "expires_in" in data
        assert isinstance(data["job_id"], str)
        assert isinstance(data["download_url"], str)
        assert isinstance(data["expires_in"], int)

    async def test_presigned_url_default_expiry_is_one_hour(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Presigned URL has a 1-hour (3600 seconds) default expiry."""
        node = _make_node(name="expiry-node", public_key="key-expiry")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(
            node=node,
            status=JobStatus.COMPLETED,
            result_ref="user1/job1/result.zip",
        )
        db_session.add(job)
        await db_session.flush()

        resp = await client.get(f"/api/v1/jobs/{job.id}/result", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["expires_in"] == 3600


# =========================================================================
# 2. Job Not Found
# =========================================================================


class TestGetJobResultNotFound:
    """GET /api/v1/jobs/{job_id}/result returns 404 for missing jobs."""

    async def test_nonexistent_job_returns_404(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Request for a non-existent job ID returns 404."""
        resp = await client.get(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000/result",
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Job not found"


# =========================================================================
# 3. Incomplete Jobs Return 404
# =========================================================================


class TestGetJobResultIncompleteJobs:
    """GET /api/v1/jobs/{job_id}/result returns 404 for non-COMPLETED jobs."""

    async def test_queued_job_returns_404(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """QUEUED job returns 404 with 'not completed' message."""
        node = _make_node(name="queued-node", public_key="key-queued-result")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.QUEUED)
        db_session.add(job)
        await db_session.flush()

        resp = await client.get(f"/api/v1/jobs/{job.id}/result", headers=auth_headers)
        assert resp.status_code == 404
        assert "not completed" in resp.json()["detail"]

    async def test_running_job_returns_404(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """RUNNING job returns 404 with 'not completed' message."""
        node = _make_node(name="running-node", public_key="key-running-result")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.RUNNING)
        db_session.add(job)
        await db_session.flush()

        resp = await client.get(f"/api/v1/jobs/{job.id}/result", headers=auth_headers)
        assert resp.status_code == 404
        assert "not completed" in resp.json()["detail"]

    async def test_dispatched_job_returns_404(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """DISPATCHED job returns 404 with 'not completed' message."""
        node = _make_node(name="dispatched-node", public_key="key-dispatched-result")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.DISPATCHED)
        db_session.add(job)
        await db_session.flush()

        resp = await client.get(f"/api/v1/jobs/{job.id}/result", headers=auth_headers)
        assert resp.status_code == 404
        assert "not completed" in resp.json()["detail"]

    async def test_failed_job_returns_404(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """FAILED job returns 404 with 'not completed' message."""
        node = _make_node(name="failed-node", public_key="key-failed-result")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(
            node=node,
            status=JobStatus.FAILED,
            error_message="GPU crash",
        )
        db_session.add(job)
        await db_session.flush()

        resp = await client.get(f"/api/v1/jobs/{job.id}/result", headers=auth_headers)
        assert resp.status_code == 404
        assert "not completed" in resp.json()["detail"]


# =========================================================================
# 4. Completed Job Without result_ref
# =========================================================================


class TestGetJobResultNoResultRef:
    """GET /api/v1/jobs/{job_id}/result returns 404 for completed jobs with no result."""

    async def test_completed_without_result_ref_returns_404(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Completed job with result_ref=None returns 404 with 'no result stored'."""
        node = _make_node(name="no-ref-node", public_key="key-no-ref")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(
            node=node,
            status=JobStatus.COMPLETED,
            result_ref=None,
        )
        db_session.add(job)
        await db_session.flush()

        resp = await client.get(f"/api/v1/jobs/{job.id}/result", headers=auth_headers)
        assert resp.status_code == 404
        assert "no result stored" in resp.json()["detail"]


# =========================================================================
# 5. Invalid Job ID Format
# =========================================================================


class TestGetJobResultInvalidId:
    """GET /api/v1/jobs/{job_id}/result returns 422 for invalid UUID."""

    async def test_invalid_uuid_returns_422(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Non-UUID job_id returns 422 with 'Invalid job ID format'."""
        resp = await client.get("/api/v1/jobs/not-a-uuid/result", headers=auth_headers)
        assert resp.status_code == 422
        assert resp.json()["detail"] == "Invalid job ID format"


# =========================================================================
# 6. Authentication Required
# =========================================================================


class TestGetJobResultAuthentication:
    """GET /api/v1/jobs/{job_id}/result requires authentication."""

    async def test_unauthenticated_returns_401_or_403(
        self,
        client: AsyncClient,
    ) -> None:
        """Request without auth token returns 401 or 403."""
        resp = await client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000/result")
        assert resp.status_code in (401, 403)


# =========================================================================
# 7. StorageService Integration
# =========================================================================


class TestStorageServiceIntegration:
    """Verify StorageService is called with correct parameters."""

    async def test_storage_called_with_correct_key(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
        mock_storage_service: MagicMock,
    ) -> None:
        """StorageService.generate_presigned_url is called with the job's result_ref."""
        node = _make_node(name="storage-key-node", public_key="key-storage-key")
        db_session.add(node)
        await db_session.flush()

        result_key = "user789/job012/render-output.exr"
        job = _make_job(
            node=node,
            status=JobStatus.COMPLETED,
            result_ref=result_key,
        )
        db_session.add(job)
        await db_session.flush()

        await client.get(f"/api/v1/jobs/{job.id}/result", headers=auth_headers)

        mock_storage_service.generate_presigned_url.assert_called_once_with(
            key=result_key,
            expires_in=3600,
        )

    async def test_storage_called_with_one_hour_expiry(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
        mock_storage_service: MagicMock,
    ) -> None:
        """StorageService is called with expires_in=3600 (1 hour)."""
        node = _make_node(name="storage-expiry-node", public_key="key-storage-expiry")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(
            node=node,
            status=JobStatus.COMPLETED,
            result_ref="user1/job1/result.zip",
        )
        db_session.add(job)
        await db_session.flush()

        await client.get(f"/api/v1/jobs/{job.id}/result", headers=auth_headers)

        call_args = mock_storage_service.generate_presigned_url.call_args
        assert call_args.kwargs["expires_in"] == 3600
