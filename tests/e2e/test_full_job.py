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

"""End-to-end job execution tests -- full lifecycle validation.

Wires together every major subsystem in-process to validate the complete
PI 2 delivery pipeline:

    register user -> allocate credits -> register edge node ->
    submit job -> dispatch -> simulate execution -> upload result ->
    update job status -> download result (presigned URL) ->
    verify credits deducted -> verify job status transitions

Three test scenarios:
1.  **Happy path** -- full success flow from dispatch through result download
2.  **Failure / retry** -- job fails, retries, then succeeds on second attempt
3.  **Insufficient credits** -- deduction rejected with 402

External dependencies are mocked:
- Redis (token blacklist + job queue) -- patched to no-op
- S3 / MinIO (storage) -- patched with in-memory stub

All database operations use the real SQLAlchemy async engine (SQLite in-memory)
via the ``db_session`` and ``client`` fixtures from ``tests/conftest.py``.

[REN-112]
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.ledger.service import allocate_credits, deduct_credits, get_balance
from core.models.base import TransactionSource
from core.scheduler.job_service import update_job_status
from core.scheduler.models import EdgeNode, JobStatus, NodeStatus
from core.storage.service import StorageService

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.models.base import User


# ---------------------------------------------------------------------------
# Module-scoped mocks -- applied to all tests in this module.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_blacklist():
    """Mock the Redis-backed token blacklist so JWT verification works."""
    with patch("core.auth.jwt.token_blacklist") as mock_bl:
        mock_bl.is_revoked = AsyncMock(return_value=False)
        yield mock_bl


@pytest.fixture(autouse=True)
def mock_redis_queue():
    """Mock the Redis job queue push (no Redis server in tests)."""
    with patch("core.scheduler.dispatch.push_to_queue", new_callable=AsyncMock) as mock_push:
        mock_push.return_value = True
        yield mock_push


# ---------------------------------------------------------------------------
# Storage mock -- records uploads in-memory and returns predictable URLs.
# ---------------------------------------------------------------------------


MOCK_PRESIGNED_URL = (
    "https://storage.example.com/rendertrust-dev/presigned?X-Amz-Signature=e2e-test-signature"
)


@pytest.fixture(autouse=True)
def mock_storage_service():
    """Patch StorageService in the jobs module to avoid real S3 calls.

    The mock records upload_file calls and returns a fixed presigned URL
    for generate_presigned_url.
    """
    mock_instance = MagicMock(spec=StorageService)
    mock_instance.upload_file.return_value = "user/job/result"
    mock_instance.generate_presigned_url.return_value = MOCK_PRESIGNED_URL
    mock_instance.file_exists.return_value = True

    with patch("core.api.v1.jobs.StorageService") as mock_cls:
        mock_cls.return_value = mock_instance
        yield mock_instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_healthy_node(
    *,
    name: str = "e2e-compute-node",
    capabilities: list[str] | None = None,
    current_load: float = 0.1,
    public_key: str | None = None,
) -> EdgeNode:
    """Create a HEALTHY EdgeNode ready to accept jobs."""
    return EdgeNode(
        public_key=public_key or f"ed25519-e2e-{uuid.uuid4().hex[:8]}",
        name=name,
        capabilities=capabilities or ["echo", "render", "inference"],
        status=NodeStatus.HEALTHY,
        current_load=current_load,
        last_heartbeat=datetime.datetime.now(tz=datetime.UTC),
    )


async def _allocate_credits_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    amount: Decimal,
    reference_id: str | None = None,
) -> None:
    """Allocate credits to a user's account directly via the ledger service."""
    await allocate_credits(
        session=session,
        user_id=user_id,
        amount=amount,
        source=TransactionSource.ADJUSTMENT,
        reference_id=reference_id or f"e2e-alloc-{uuid.uuid4().hex[:8]}",
        description="E2E test credit allocation",
    )


# =========================================================================
# 1. Happy Path -- Full Job Lifecycle
# =========================================================================


class TestFullJobLifecycleHappyPath:
    """Complete E2E flow: credits -> dispatch -> execute -> result -> verify.

    Steps:
    1. Allocate credits to user
    2. Register edge node with 'echo' capability
    3. Dispatch echo job via API
    4. Transition: DISPATCHED -> RUNNING (simulating relay pickup)
    5. Transition: RUNNING -> COMPLETED with result_ref (simulating upload)
    6. Deduct credits for the completed job
    7. Verify job status is COMPLETED via API
    8. Download result via presigned URL endpoint
    9. Verify credits were deducted correctly
    10. Verify full job detail fields
    """

    async def test_end_to_end_echo_job_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Full happy-path lifecycle from credit allocation to result download."""

        # -- Step 1: Allocate credits to test user --
        initial_credits = Decimal("100.0000")
        await _allocate_credits_for_user(
            session=db_session,
            user_id=test_user.id,
            amount=initial_credits,
            reference_id="e2e-happy-alloc",
        )

        # Verify balance via API
        balance_resp = await client.get("/api/v1/credits/balance", headers=auth_headers)
        assert balance_resp.status_code == 200
        assert Decimal(balance_resp.json()["balance"]) == initial_credits

        # -- Step 2: Register a healthy edge node --
        node = _make_healthy_node(
            name="e2e-happy-node",
            capabilities=["echo", "render"],
            public_key="ed25519-e2e-happy",
        )
        db_session.add(node)
        await db_session.flush()
        node_id = node.id

        # -- Step 3: Dispatch echo job via API --
        dispatch_resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={
                "job_type": "echo",
                "payload_ref": "s3://e2e-bucket/echo-input.json",
            },
            headers=auth_headers,
        )
        assert dispatch_resp.status_code == 201
        dispatch_data = dispatch_resp.json()
        assert dispatch_data["status"] == "DISPATCHED"
        assert dispatch_data["node_id"] == str(node_id)

        job_id_str = dispatch_data["job_id"]
        job_id = uuid.UUID(job_id_str)

        # Verify DISPATCHED status via GET
        get_resp = await client.get(f"/api/v1/jobs/{job_id_str}", headers=auth_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "DISPATCHED"
        assert get_resp.json()["dispatched_at"] is not None

        # -- Step 4: Simulate relay pickup -> RUNNING --
        running_job = await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.RUNNING,
        )
        assert running_job.status == JobStatus.RUNNING

        # Verify RUNNING via API
        running_resp = await client.get(f"/api/v1/jobs/{job_id_str}", headers=auth_headers)
        assert running_resp.status_code == 200
        assert running_resp.json()["status"] == "RUNNING"

        # -- Step 5: Simulate execution + upload -> COMPLETED --
        result_key = f"{test_user.id}/{job_id}/result.json"
        completed_job = await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.COMPLETED,
            result_ref=result_key,
        )
        assert completed_job.status == JobStatus.COMPLETED
        assert completed_job.result_ref == result_key
        assert completed_job.completed_at is not None

        # -- Step 6: Deduct credits for the completed job --
        job_cost = Decimal("5.0000")
        await deduct_credits(
            session=db_session,
            user_id=test_user.id,
            amount=job_cost,
            source=TransactionSource.USAGE,
            reference_id=f"job-{job_id_str}",
            description=f"Echo job execution: {job_id_str}",
        )

        # -- Step 7: Verify COMPLETED status via API --
        completed_resp = await client.get(f"/api/v1/jobs/{job_id_str}", headers=auth_headers)
        assert completed_resp.status_code == 200
        completed_data = completed_resp.json()
        assert completed_data["status"] == "COMPLETED"
        assert completed_data["result_ref"] == result_key
        assert completed_data["completed_at"] is not None
        assert completed_data["error_message"] is None
        assert completed_data["retry_count"] == 0

        # -- Step 8: Download result via presigned URL endpoint --
        result_resp = await client.get(f"/api/v1/jobs/{job_id_str}/result", headers=auth_headers)
        assert result_resp.status_code == 200
        result_data = result_resp.json()
        assert result_data["job_id"] == job_id_str
        assert result_data["download_url"] == MOCK_PRESIGNED_URL
        assert result_data["expires_in"] == 3600

        # -- Step 9: Verify credits were deducted --
        expected_balance = initial_credits - job_cost
        final_balance = await get_balance(session=db_session, user_id=test_user.id)
        assert final_balance == expected_balance

        # Also verify via API
        balance_resp_final = await client.get("/api/v1/credits/balance", headers=auth_headers)
        assert balance_resp_final.status_code == 200
        assert Decimal(balance_resp_final.json()["balance"]) == expected_balance

        # -- Step 10: Verify full job detail fields --
        detail_resp = await client.get(f"/api/v1/jobs/{job_id_str}", headers=auth_headers)
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["id"] == job_id_str
        assert detail["node_id"] == str(node_id)
        assert detail["job_type"] == "echo"
        assert detail["payload_ref"] == "s3://e2e-bucket/echo-input.json"
        assert detail["queued_at"] is not None
        assert detail["dispatched_at"] is not None
        assert detail["completed_at"] is not None
        assert detail["created_at"] is not None
        assert detail["updated_at"] is not None

    async def test_job_appears_in_list_with_completed_filter(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Completed job is visible in the jobs list filtered by COMPLETED status."""
        node = _make_healthy_node(
            name="e2e-list-node",
            capabilities=["echo"],
            public_key="ed25519-e2e-list",
        )
        db_session.add(node)
        await db_session.flush()

        # Dispatch and complete a job
        dispatch_resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "echo", "payload_ref": "s3://e2e/list-test.json"},
            headers=auth_headers,
        )
        assert dispatch_resp.status_code == 201
        job_id = uuid.UUID(dispatch_resp.json()["job_id"])

        await update_job_status(session=db_session, job_id=job_id, new_status=JobStatus.RUNNING)
        await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.COMPLETED,
            result_ref="e2e/list-test/result",
        )

        # Query the list endpoint with COMPLETED filter
        list_resp = await client.get("/api/v1/jobs?status=COMPLETED", headers=auth_headers)
        assert list_resp.status_code == 200
        jobs = list_resp.json()["jobs"]
        completed_ids = [j["id"] for j in jobs]
        assert str(job_id) in completed_ids


# =========================================================================
# 2. Failure and Retry Flow
# =========================================================================


class TestJobFailureAndRetry:
    """Job fails on first attempt, gets retried, succeeds on second attempt.

    Validates:
    - DISPATCHED -> RUNNING -> FAILED with error message
    - FAILED -> QUEUED (retry, retry_count incremented)
    - QUEUED -> DISPATCHED -> RUNNING -> COMPLETED on retry
    - Credits deducted only after successful completion
    - Error message stored on first failure
    - Result ref stored on second completion
    """

    async def test_fail_retry_succeed(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Job fails, retries once, and completes successfully."""

        # Setup: allocate credits
        initial_credits = Decimal("50.0000")
        await _allocate_credits_for_user(
            session=db_session,
            user_id=test_user.id,
            amount=initial_credits,
            reference_id="e2e-retry-alloc",
        )

        # Register node
        node = _make_healthy_node(
            name="e2e-retry-node",
            capabilities=["render"],
            public_key="ed25519-e2e-retry",
        )
        db_session.add(node)
        await db_session.flush()

        # Dispatch job
        dispatch_resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={
                "job_type": "render",
                "payload_ref": "s3://e2e-bucket/scene-retry.blend",
            },
            headers=auth_headers,
        )
        assert dispatch_resp.status_code == 201
        job_id = uuid.UUID(dispatch_resp.json()["job_id"])

        # -- First attempt: DISPATCHED -> RUNNING -> FAILED --
        await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.RUNNING,
        )

        await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.FAILED,
            error_message="GPU out of memory: CUDA error 0x2",
        )

        # Verify failure via API
        fail_resp = await client.get(f"/api/v1/jobs/{job_id}", headers=auth_headers)
        assert fail_resp.status_code == 200
        fail_data = fail_resp.json()
        assert fail_data["status"] == "FAILED"
        assert fail_data["error_message"] == "GPU out of memory: CUDA error 0x2"
        assert fail_data["completed_at"] is not None
        assert fail_data["retry_count"] == 0

        # Result endpoint should return 404 for failed job
        result_fail_resp = await client.get(f"/api/v1/jobs/{job_id}/result", headers=auth_headers)
        assert result_fail_resp.status_code == 404

        # -- Retry: FAILED -> QUEUED --
        retried = await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.QUEUED,
        )
        assert retried.retry_count == 1

        retry_resp = await client.get(f"/api/v1/jobs/{job_id}", headers=auth_headers)
        assert retry_resp.json()["status"] == "QUEUED"
        assert retry_resp.json()["retry_count"] == 1

        # -- Second attempt: QUEUED -> DISPATCHED -> RUNNING -> COMPLETED --
        await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.DISPATCHED,
        )
        await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.RUNNING,
        )

        result_key = f"{test_user.id}/{job_id}/render-output.exr"
        await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.COMPLETED,
            result_ref=result_key,
        )

        # Verify second completion via API
        completed_resp = await client.get(f"/api/v1/jobs/{job_id}", headers=auth_headers)
        assert completed_resp.status_code == 200
        completed_data = completed_resp.json()
        assert completed_data["status"] == "COMPLETED"
        assert completed_data["result_ref"] == result_key
        assert completed_data["retry_count"] == 1

        # Deduct credits only now (after success)
        job_cost = Decimal("10.0000")
        await deduct_credits(
            session=db_session,
            user_id=test_user.id,
            amount=job_cost,
            source=TransactionSource.USAGE,
            reference_id=f"job-{job_id}",
            description=f"Render job (retry): {job_id}",
        )

        # Verify balance
        expected_balance = initial_credits - job_cost
        balance = await get_balance(session=db_session, user_id=test_user.id)
        assert balance == expected_balance

        # Download result should now work
        result_resp = await client.get(f"/api/v1/jobs/{job_id}/result", headers=auth_headers)
        assert result_resp.status_code == 200
        assert result_resp.json()["download_url"] == MOCK_PRESIGNED_URL


# =========================================================================
# 3. Insufficient Credits
# =========================================================================


class TestInsufficientCredits:
    """Job completes but credit deduction fails due to insufficient balance.

    Validates:
    - Job can complete execution without pre-checking credits
    - Credit deduction API returns 402 when balance is too low
    - User balance remains unchanged after failed deduction
    """

    async def test_deduction_fails_with_402_when_insufficient(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Credit deduction returns 402 when user has insufficient balance."""

        # Setup: allocate only 2 credits
        small_balance = Decimal("2.0000")
        await _allocate_credits_for_user(
            session=db_session,
            user_id=test_user.id,
            amount=small_balance,
            reference_id="e2e-insufficient-alloc",
        )

        # Register node and dispatch job
        node = _make_healthy_node(
            name="e2e-insufficient-node",
            capabilities=["render"],
            public_key="ed25519-e2e-insufficient",
        )
        db_session.add(node)
        await db_session.flush()

        dispatch_resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={
                "job_type": "render",
                "payload_ref": "s3://e2e-bucket/scene-expensive.blend",
            },
            headers=auth_headers,
        )
        assert dispatch_resp.status_code == 201
        job_id = uuid.UUID(dispatch_resp.json()["job_id"])

        # Complete the job (execution succeeds regardless of credits)
        await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.RUNNING,
        )
        await update_job_status(
            session=db_session,
            job_id=job_id,
            new_status=JobStatus.COMPLETED,
            result_ref=f"{test_user.id}/{job_id}/result.exr",
        )

        # Attempt to deduct 10 credits (more than available 2)
        deduct_resp = await client.post(
            "/api/v1/credits/deduct",
            json={
                "amount": "10.0000",
                "reference_id": f"job-{job_id}",
                "description": "Render job execution",
            },
            headers=auth_headers,
        )
        assert deduct_resp.status_code == 402
        deduct_data = deduct_resp.json()
        assert deduct_data["detail"] == "Insufficient credits"
        assert Decimal(deduct_data["available"]) == small_balance
        assert Decimal(deduct_data["requested"]) == Decimal("10.0000")

        # Balance unchanged
        balance = await get_balance(session=db_session, user_id=test_user.id)
        assert balance == small_balance


# =========================================================================
# 4. No Healthy Nodes Available
# =========================================================================


class TestNoHealthyNodes:
    """Dispatch fails with 503 when no healthy nodes match the job type."""

    async def test_dispatch_returns_503_when_no_nodes(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Dispatch without any registered nodes returns 503."""
        # No nodes registered -- dispatch should fail
        dispatch_resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={
                "job_type": "rare_capability",
                "payload_ref": "s3://e2e-bucket/input.json",
            },
            headers=auth_headers,
        )
        assert dispatch_resp.status_code == 503
        assert "No healthy nodes" in dispatch_resp.json()["detail"]

    async def test_dispatch_fails_when_node_offline(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Dispatch fails when the only node is OFFLINE."""
        offline_node = EdgeNode(
            public_key="ed25519-e2e-offline",
            name="e2e-offline-node",
            capabilities=["echo"],
            status=NodeStatus.OFFLINE,
            current_load=0.0,
            last_heartbeat=datetime.datetime.now(tz=datetime.UTC),
        )
        db_session.add(offline_node)
        await db_session.flush()

        dispatch_resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "echo", "payload_ref": "s3://e2e/offline-test.json"},
            headers=auth_headers,
        )
        assert dispatch_resp.status_code == 503


# =========================================================================
# 5. Authentication Required for Full Flow
# =========================================================================


class TestAuthenticationRequiredE2E:
    """All job lifecycle endpoints require authentication."""

    async def test_dispatch_without_auth_rejected(
        self,
        client: AsyncClient,
    ) -> None:
        """Job dispatch without auth token returns 401/403."""
        resp = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "echo", "payload_ref": "s3://bucket/input.json"},
        )
        assert resp.status_code in (401, 403)

    async def test_job_result_without_auth_rejected(
        self,
        client: AsyncClient,
    ) -> None:
        """Job result endpoint without auth token returns 401/403."""
        resp = await client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000/result")
        assert resp.status_code in (401, 403)

    async def test_credits_balance_without_auth_rejected(
        self,
        client: AsyncClient,
    ) -> None:
        """Credits balance endpoint without auth token returns 401/403."""
        resp = await client.get("/api/v1/credits/balance")
        assert resp.status_code in (401, 403)

    async def test_credits_deduct_without_auth_rejected(
        self,
        client: AsyncClient,
    ) -> None:
        """Credits deduction endpoint without auth token returns 401/403."""
        resp = await client.post(
            "/api/v1/credits/deduct",
            json={
                "amount": "1.0000",
                "reference_id": "unauth-test",
            },
        )
        assert resp.status_code in (401, 403)


# =========================================================================
# 6. Multi-Job Concurrent Dispatch
# =========================================================================


class TestMultiJobDispatch:
    """Multiple jobs dispatched to the same node, completed independently."""

    async def test_two_jobs_complete_independently(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Two jobs dispatched sequentially complete independently."""

        # Setup credits
        await _allocate_credits_for_user(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("200.0000"),
            reference_id="e2e-multi-alloc",
        )

        # Register node
        node = _make_healthy_node(
            name="e2e-multi-node",
            capabilities=["render", "inference"],
            public_key="ed25519-e2e-multi",
        )
        db_session.add(node)
        await db_session.flush()

        # Dispatch job A (render)
        resp_a = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "render", "payload_ref": "s3://e2e/scene-a.blend"},
            headers=auth_headers,
        )
        assert resp_a.status_code == 201
        job_a_id = uuid.UUID(resp_a.json()["job_id"])

        # Dispatch job B (inference)
        resp_b = await client.post(
            "/api/v1/jobs/dispatch",
            json={"job_type": "inference", "payload_ref": "s3://e2e/model-b.bin"},
            headers=auth_headers,
        )
        assert resp_b.status_code == 201
        job_b_id = uuid.UUID(resp_b.json()["job_id"])

        # Complete job A
        await update_job_status(session=db_session, job_id=job_a_id, new_status=JobStatus.RUNNING)
        await update_job_status(
            session=db_session,
            job_id=job_a_id,
            new_status=JobStatus.COMPLETED,
            result_ref=f"{test_user.id}/{job_a_id}/render.exr",
        )

        # Job B still DISPATCHED
        b_resp = await client.get(f"/api/v1/jobs/{job_b_id}", headers=auth_headers)
        assert b_resp.json()["status"] == "DISPATCHED"

        # Complete job B
        await update_job_status(session=db_session, job_id=job_b_id, new_status=JobStatus.RUNNING)
        await update_job_status(
            session=db_session,
            job_id=job_b_id,
            new_status=JobStatus.COMPLETED,
            result_ref=f"{test_user.id}/{job_b_id}/inference.json",
        )

        # Both jobs completed
        a_resp = await client.get(f"/api/v1/jobs/{job_a_id}", headers=auth_headers)
        b_resp = await client.get(f"/api/v1/jobs/{job_b_id}", headers=auth_headers)
        assert a_resp.json()["status"] == "COMPLETED"
        assert b_resp.json()["status"] == "COMPLETED"

        # Deduct credits for both
        await deduct_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("5.0000"),
            source=TransactionSource.USAGE,
            reference_id=f"job-{job_a_id}",
        )
        await deduct_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("8.0000"),
            source=TransactionSource.USAGE,
            reference_id=f"job-{job_b_id}",
        )

        # Verify total deduction: 200 - 5 - 8 = 187
        balance = await get_balance(session=db_session, user_id=test_user.id)
        assert balance == Decimal("187.0000")


# =========================================================================
# 7. Cleanup Verification
# =========================================================================


class TestCleanupAfterTest:
    """Verify database isolation -- previous test data does not leak."""

    async def test_no_jobs_leak_between_tests(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Job list is empty in a fresh test (savepoint rollback isolates data).

        This validates that the conftest.py savepoint rollback correctly
        cleans up all data between tests, which is critical for E2E test
        reliability.
        """
        resp = await client.get("/api/v1/jobs", headers=auth_headers)
        assert resp.status_code == 200
        # Due to savepoint rollback, no data from previous tests should exist
        assert resp.json()["count"] == 0

    async def test_credits_start_at_zero(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """User has zero credits at the start of a fresh test."""
        balance = await get_balance(session=db_session, user_id=test_user.id)
        assert balance == Decimal("0.0000")
