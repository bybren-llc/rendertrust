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

"""Integration tests for the full job lifecycle.

Covers the complete job lifecycle from dispatch through terminal states:

1.  Dispatch success -- submit job, verify DISPATCHED status
2.  Happy-path lifecycle: DISPATCHED -> RUNNING -> COMPLETED
3.  Invalid state transitions return proper errors (QUEUED -> COMPLETED)
4.  Cancel queued job (success)
5.  Cancel dispatched job (success)
6.  Cancel running job (rejected)
7.  Get single job detail
8.  List jobs with pagination and status filter
9.  Cross-user isolation (OWASP A01 -- currently no user_id on JobDispatch)
10. Error message storage (FAILED jobs store error_message)
11. Retry count tracking (FAILED -> QUEUED increments retry_count)
12. Result reference storage (COMPLETED jobs store result_ref)
13. Full happy path: dispatch -> RUNNING -> COMPLETED via service + API
14. Dispatch -> RUNNING -> FAILED with error message via service + API

Tests exercise both the HTTP API layer (FastAPI endpoints via AsyncClient)
and the service layer (job_service functions) to validate the full lifecycle.

[REN-99]
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from core.auth.jwt import create_access_token
from core.scheduler.job_service import update_job_status
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
    with patch(
        "core.scheduler.dispatch.push_to_queue", new_callable=AsyncMock
    ) as mock_push:
        mock_push.return_value = True
        yield mock_push


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(
    *,
    name: str = "lifecycle-node",
    status: NodeStatus = NodeStatus.HEALTHY,
    capabilities: list[str] | None = None,
    current_load: float = 0.0,
    public_key: str = "ed25519-lifecycle-key",
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
# 1. Dispatch Success
# =========================================================================


class TestDispatchSuccess:
    """Dispatch a job and verify the initial DISPATCHED status."""

    async def test_dispatch_creates_job_with_dispatched_status(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Dispatch returns 201 and the job starts in DISPATCHED status."""
        node = _make_node(name="dispatch-ok", public_key="key-dispatch-ok")
        db_session.add(node)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render", "payload_ref": "s3://bucket/lc-001.blend"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "DISPATCHED"
        assert "job_id" in data

        # Verify via GET endpoint
        get_resp = await client.get(
            f"/api/v1/jobs/{data['job_id']}", headers=auth_headers
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "DISPATCHED"


# =========================================================================
# 2. Happy Path: DISPATCHED -> RUNNING -> COMPLETED
# =========================================================================


class TestHappyPathLifecycle:
    """Full happy-path lifecycle via service layer + API verification."""

    async def test_dispatched_to_running_to_completed(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Walk a job through DISPATCHED -> RUNNING -> COMPLETED."""
        node = _make_node(name="happy-node", public_key="key-happy-path")
        db_session.add(node)
        await db_session.flush()

        # Create job in DISPATCHED state (simulating post-dispatch)
        job = _make_job(node=node, status=JobStatus.DISPATCHED)
        db_session.add(job)
        await db_session.flush()
        job_id = job.id

        # Transition: DISPATCHED -> RUNNING
        updated = await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.RUNNING,
        )
        assert updated.status == JobStatus.RUNNING

        # Transition: RUNNING -> COMPLETED with result_ref
        completed = await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.COMPLETED,
            result_ref="s3://bucket/result-happy.zip",
        )
        assert completed.status == JobStatus.COMPLETED
        assert completed.completed_at is not None
        assert completed.result_ref == "s3://bucket/result-happy.zip"

        # Verify via API
        resp = await client.get(
            f"/api/v1/jobs/{job_id}", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "COMPLETED"
        assert data["result_ref"] == "s3://bucket/result-happy.zip"
        assert data["completed_at"] is not None


# =========================================================================
# 3. Invalid State Transitions
# =========================================================================


class TestInvalidTransitions:
    """Invalid state transitions raise ValueError at the service layer."""

    async def test_queued_to_completed_is_invalid(
        self,
        db_session: AsyncSession,
    ) -> None:
        """QUEUED -> COMPLETED skips required intermediate states."""
        node = _make_node(name="invalid-node-1", public_key="key-invalid-1")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.QUEUED)
        db_session.add(job)
        await db_session.flush()

        with pytest.raises(ValueError, match="Invalid transition"):
            await update_job_status(
                session=db_session,
                job_id=job.id,
                new_status=JobStatus.COMPLETED,
            )

    async def test_queued_to_running_is_invalid(
        self,
        db_session: AsyncSession,
    ) -> None:
        """QUEUED -> RUNNING must go through DISPATCHED first."""
        node = _make_node(name="invalid-node-2", public_key="key-invalid-2")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.QUEUED)
        db_session.add(job)
        await db_session.flush()

        with pytest.raises(ValueError, match="Invalid transition"):
            await update_job_status(
                session=db_session,
                job_id=job.id,
                new_status=JobStatus.RUNNING,
            )

    async def test_completed_is_terminal(
        self,
        db_session: AsyncSession,
    ) -> None:
        """COMPLETED is a terminal state -- no transitions allowed."""
        node = _make_node(name="invalid-node-3", public_key="key-invalid-3")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.COMPLETED)
        db_session.add(job)
        await db_session.flush()

        with pytest.raises(ValueError, match="Invalid transition"):
            await update_job_status(
                session=db_session,
                job_id=job.id,
                new_status=JobStatus.RUNNING,
            )


# =========================================================================
# 4. Cancel Queued Job
# =========================================================================


class TestCancelQueuedJob:
    """Cancel a QUEUED job via the API."""

    async def test_cancel_queued_succeeds(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Cancelling a QUEUED job sets status to FAILED with message."""
        node = _make_node(name="cancel-q", public_key="key-cancel-q")
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
        assert data["completed_at"] is not None


# =========================================================================
# 5. Cancel Dispatched Job
# =========================================================================


class TestCancelDispatchedJob:
    """Cancel a DISPATCHED job via the API."""

    async def test_cancel_dispatched_succeeds(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Cancelling a DISPATCHED job sets status to FAILED."""
        node = _make_node(name="cancel-d", public_key="key-cancel-d")
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


# =========================================================================
# 6. Cancel Running Job (Rejected)
# =========================================================================


class TestCancelRunningJobRejected:
    """Running jobs cannot be cancelled -- must complete or fail."""

    async def test_cancel_running_returns_400(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Cancelling a RUNNING job returns 400 with descriptive error."""
        node = _make_node(name="cancel-r", public_key="key-cancel-r")
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


# =========================================================================
# 7. Get Single Job Detail
# =========================================================================


class TestGetJobDetail:
    """GET /api/v1/jobs/{job_id} returns full job details."""

    async def test_get_job_returns_all_fields(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Verify all response fields are present and correct."""
        node = _make_node(name="detail-node", public_key="key-detail")
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
        assert data["result_ref"] is None
        assert data["error_message"] is None
        assert data["queued_at"] is not None
        assert data["created_at"] is not None
        assert data["updated_at"] is not None


# =========================================================================
# 8. List Jobs with Pagination and Status Filter
# =========================================================================


class TestListJobsPaginationAndFilter:
    """GET /api/v1/jobs with pagination and status filtering."""

    async def test_list_with_status_filter(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Filter by status returns only matching jobs."""
        node = _make_node(name="filter-lc", public_key="key-filter-lc")
        db_session.add(node)
        await db_session.flush()

        # Create jobs in different states
        queued = _make_job(node=node, status=JobStatus.QUEUED, payload_ref="s3://q")
        running = _make_job(node=node, status=JobStatus.RUNNING, payload_ref="s3://r")
        completed = _make_job(
            node=node, status=JobStatus.COMPLETED, payload_ref="s3://c"
        )
        db_session.add_all([queued, running, completed])
        await db_session.flush()

        # Filter for RUNNING only
        resp = await client.get(
            "/api/v1/jobs?status=RUNNING", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        assert all(j["status"] == "RUNNING" for j in data["jobs"])

    async def test_list_with_pagination(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Pagination returns correct page slices."""
        node = _make_node(name="page-lc", public_key="key-page-lc")
        db_session.add(node)
        await db_session.flush()

        for i in range(4):
            job = _make_job(node=node, payload_ref=f"s3://page-{i}")
            db_session.add(job)
        await db_session.flush()

        # Page 1: limit=2
        resp1 = await client.get(
            "/api/v1/jobs?limit=2&offset=0", headers=auth_headers
        )
        assert resp1.status_code == 200
        assert len(resp1.json()["jobs"]) == 2

        # Page 2: offset=2, limit=2
        resp2 = await client.get(
            "/api/v1/jobs?limit=2&offset=2", headers=auth_headers
        )
        assert resp2.status_code == 200
        assert len(resp2.json()["jobs"]) == 2


# =========================================================================
# 9. Cross-User Isolation (OWASP A01)
# =========================================================================


class TestCrossUserIsolation:
    """Verify that users cannot cancel other users' jobs.

    NOTE: JobDispatch currently has no user_id column, so list/get endpoints
    return all jobs regardless of user. This test validates that authenticated
    endpoints require auth and tests cancel isolation for the current design.
    When user_id is added to JobDispatch, these tests should be expanded to
    verify list/get isolation as well.
    """

    async def test_unauthenticated_cannot_list_jobs(
        self,
        client: AsyncClient,
    ) -> None:
        """Unauthenticated requests to list jobs are rejected."""
        resp = await client.get("/api/v1/jobs")
        assert resp.status_code in (401, 403)

    async def test_unauthenticated_cannot_get_job(
        self,
        client: AsyncClient,
    ) -> None:
        """Unauthenticated requests to get a job are rejected."""
        resp = await client.get(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000"
        )
        assert resp.status_code in (401, 403)

    async def test_unauthenticated_cannot_cancel_job(
        self,
        client: AsyncClient,
    ) -> None:
        """Unauthenticated requests to cancel a job are rejected."""
        resp = await client.post(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000/cancel"
        )
        assert resp.status_code in (401, 403)

    async def test_different_user_auth_required_for_dispatch(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        admin_user: User,
    ) -> None:
        """Both users can dispatch (auth is required, not user-specific filtering).

        This documents the current design: JobDispatch has no user_id,
        so all authenticated users see all jobs. When per-user isolation
        is added (user_id FK on JobDispatch), this test should verify
        that User A cannot see/cancel User B's jobs.
        """
        node = _make_node(name="cross-user", public_key="key-cross-user")
        db_session.add(node)
        await db_session.flush()

        # User A dispatches
        token_a = create_access_token({"sub": str(test_user.id)})
        headers_a = {"Authorization": f"Bearer {token_a}"}
        resp_a = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render", "payload_ref": "s3://user-a/scene.blend"},
            headers=headers_a,
        )
        assert resp_a.status_code == 201
        job_a_id = resp_a.json()["job_id"]

        # User B (admin) can also see and cancel User A's job
        # This is the CURRENT behavior -- no per-user isolation yet
        token_b = create_access_token({"sub": str(admin_user.id)})
        headers_b = {"Authorization": f"Bearer {token_b}"}
        resp_b = await client.get(
            f"/api/v1/jobs/{job_a_id}", headers=headers_b
        )
        assert resp_b.status_code == 200
        assert resp_b.json()["id"] == job_a_id


# =========================================================================
# 10. Error Message Storage
# =========================================================================


class TestErrorMessageStorage:
    """FAILED jobs store the error_message field."""

    async def test_failed_job_stores_error_message(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Transition to FAILED stores error_message, visible via API."""
        node = _make_node(name="err-node", public_key="key-err")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.RUNNING)
        db_session.add(job)
        await db_session.flush()

        # Fail the job via service layer with a specific error
        failed = await update_job_status(
            session=db_session,
            job_id=job.id,
            new_status=JobStatus.FAILED,
            error_message="GPU out of memory: CUDA error 0x2",
        )
        assert failed.status == JobStatus.FAILED
        assert failed.error_message == "GPU out of memory: CUDA error 0x2"
        assert failed.completed_at is not None

        # Verify via API
        resp = await client.get(
            f"/api/v1/jobs/{job.id}", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "FAILED"
        assert data["error_message"] == "GPU out of memory: CUDA error 0x2"
        assert data["completed_at"] is not None


# =========================================================================
# 11. Retry Count Tracking
# =========================================================================


class TestRetryCountTracking:
    """FAILED -> QUEUED (retry) increments retry_count."""

    async def test_retry_increments_count(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Each retry cycle (FAILED -> QUEUED) increments retry_count by 1."""
        node = _make_node(name="retry-node", public_key="key-retry")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.FAILED)
        db_session.add(job)
        await db_session.flush()
        assert job.retry_count == 0

        # First retry: FAILED -> QUEUED
        retried = await update_job_status(
            session=db_session,
            job_id=job.id,
            new_status=JobStatus.QUEUED,
        )
        assert retried.retry_count == 1
        assert retried.status == JobStatus.QUEUED

        # Verify via API
        resp = await client.get(
            f"/api/v1/jobs/{job.id}", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["retry_count"] == 1

    async def test_multiple_retries_accumulate(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Multiple retry cycles accumulate retry_count correctly."""
        node = _make_node(name="multi-retry", public_key="key-multi-retry")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.DISPATCHED)
        db_session.add(job)
        await db_session.flush()

        # Cycle 1: DISPATCHED -> RUNNING -> FAILED -> QUEUED
        await update_job_status(
            session=db_session, job_id=job.id, new_status=JobStatus.RUNNING
        )
        await update_job_status(
            session=db_session,
            job_id=job.id,
            new_status=JobStatus.FAILED,
            error_message="Timeout",
        )
        result = await update_job_status(
            session=db_session, job_id=job.id, new_status=JobStatus.QUEUED
        )
        assert result.retry_count == 1

        # Cycle 2: QUEUED -> DISPATCHED -> RUNNING -> FAILED -> QUEUED
        await update_job_status(
            session=db_session, job_id=job.id, new_status=JobStatus.DISPATCHED
        )
        await update_job_status(
            session=db_session, job_id=job.id, new_status=JobStatus.RUNNING
        )
        await update_job_status(
            session=db_session,
            job_id=job.id,
            new_status=JobStatus.FAILED,
            error_message="OOM again",
        )
        result2 = await update_job_status(
            session=db_session, job_id=job.id, new_status=JobStatus.QUEUED
        )
        assert result2.retry_count == 2


# =========================================================================
# 12. Result Reference Storage
# =========================================================================


class TestResultRefStorage:
    """COMPLETED jobs store the result_ref field."""

    async def test_completed_job_stores_result_ref(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Transitioning to COMPLETED stores result_ref, visible via API."""
        node = _make_node(name="result-node", public_key="key-result")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.RUNNING)
        db_session.add(job)
        await db_session.flush()

        # Complete the job with a result reference
        completed = await update_job_status(
            session=db_session,
            job_id=job.id,
            new_status=JobStatus.COMPLETED,
            result_ref="ipfs://QmXoY123abc/render-output.exr",
        )
        assert completed.status == JobStatus.COMPLETED
        assert completed.result_ref == "ipfs://QmXoY123abc/render-output.exr"

        # Verify via API
        resp = await client.get(
            f"/api/v1/jobs/{job.id}", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "COMPLETED"
        assert data["result_ref"] == "ipfs://QmXoY123abc/render-output.exr"


# =========================================================================
# 13. Full Lifecycle: Dispatch -> Running -> Completed (API + Service)
# =========================================================================


class TestFullLifecycleDispatchToComplete:
    """End-to-end: dispatch via API, transition via service, verify via API."""

    async def test_dispatch_run_complete_via_api_and_service(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Full lifecycle from HTTP dispatch to COMPLETED, checking each step."""
        node = _make_node(name="full-lc", public_key="key-full-lc")
        db_session.add(node)
        await db_session.flush()

        # Step 1: Dispatch via API
        dispatch_resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render", "payload_ref": "s3://bucket/full-lc.blend"},
            headers=auth_headers,
        )
        assert dispatch_resp.status_code == 201
        job_id_str = dispatch_resp.json()["job_id"]

        import uuid

        job_id = uuid.UUID(job_id_str)

        # Verify DISPATCHED via API
        resp1 = await client.get(
            f"/api/v1/jobs/{job_id_str}", headers=auth_headers
        )
        assert resp1.json()["status"] == "DISPATCHED"

        # Step 2: Transition to RUNNING via service
        await update_job_status(
            session=db_session, job_id=job_id, new_status=JobStatus.RUNNING
        )

        # Verify RUNNING via API
        resp2 = await client.get(
            f"/api/v1/jobs/{job_id_str}", headers=auth_headers
        )
        assert resp2.json()["status"] == "RUNNING"

        # Step 3: Complete via service with result
        await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.COMPLETED,
            result_ref="s3://bucket/output-full-lc.zip",
        )

        # Verify COMPLETED via API
        resp3 = await client.get(
            f"/api/v1/jobs/{job_id_str}", headers=auth_headers
        )
        data = resp3.json()
        assert data["status"] == "COMPLETED"
        assert data["result_ref"] == "s3://bucket/output-full-lc.zip"
        assert data["completed_at"] is not None
        assert data["error_message"] is None


# =========================================================================
# 14. Full Lifecycle: Dispatch -> Running -> Failed with Error
# =========================================================================


class TestFullLifecycleDispatchToFailed:
    """End-to-end: dispatch via API, fail via service, verify error storage."""

    async def test_dispatch_run_fail_stores_error(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Dispatch, transition to RUNNING, then FAILED -- error stored."""
        node = _make_node(name="fail-lc", public_key="key-fail-lc")
        db_session.add(node)
        await db_session.flush()

        # Dispatch via API
        dispatch_resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render", "payload_ref": "s3://bucket/fail-lc.blend"},
            headers=auth_headers,
        )
        assert dispatch_resp.status_code == 201
        job_id_str = dispatch_resp.json()["job_id"]

        import uuid

        job_id = uuid.UUID(job_id_str)

        # DISPATCHED -> RUNNING
        await update_job_status(
            session=db_session, job_id=job_id, new_status=JobStatus.RUNNING
        )

        # RUNNING -> FAILED with error
        await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.FAILED,
            error_message="Node crashed: segmentation fault in renderer",
        )

        # Verify via API
        resp = await client.get(
            f"/api/v1/jobs/{job_id_str}", headers=auth_headers
        )
        data = resp.json()
        assert data["status"] == "FAILED"
        assert data["error_message"] == "Node crashed: segmentation fault in renderer"
        assert data["completed_at"] is not None
        assert data["result_ref"] is None
