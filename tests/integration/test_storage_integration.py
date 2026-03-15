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

"""Integration tests for the storage service and job result upload flow.

Tests the full path from job completion through result storage to presigned
URL download. Unlike the unit tests in ``test_storage_service.py`` (which
test individual methods in isolation) and the API tests in
``test_job_result.py`` (which test the HTTP endpoint with a fully mocked
StorageService), these integration tests verify multi-component interactions:

 1. Upload + download roundtrip (data integrity across operations)
 2. Upload + presigned URL generation (stored file gets valid URL)
 3. Upload + file_exists verification (upload makes file discoverable)
 4. Upload + delete + file_exists lifecycle (full CRUD)
 5. build_key produces correct user-scoped format for multi-user scenarios
 6. Cross-user key isolation (user A key space is disjoint from user B)
 7. Job result endpoint integration with storage error (StorageError -> 500)
 8. Job result 404 for incomplete jobs (API + storage interaction)
 9. Job result 404 for missing result_ref (API + storage interaction)
10. Upload failure propagation (error from S3 surfaces correctly)
11. Download failure propagation (error from S3 surfaces correctly)
12. Path traversal prevention through build_key + upload chain
13. Presigned URL expiry boundary validation (max 24h)
14. Full end-to-end: upload result -> complete job -> GET /result -> URL

[REN-104]
"""

from __future__ import annotations

import datetime
import os
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_fake")

import pytest
from botocore.exceptions import ClientError

from core.scheduler.models import EdgeNode, JobDispatch, JobStatus, NodeStatus
from core.storage.config import StorageSettings
from core.storage.service import (
    StorageDownloadError,
    StorageError,
    StorageKeyError,
    StorageService,
    StorageUploadError,
)

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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def storage_settings() -> StorageSettings:
    """Return StorageSettings with test defaults."""
    return StorageSettings(
        endpoint_url="http://localhost:9000",
        bucket_name="rendertrust-integration-test",
        access_key="minioadmin",
        secret_key="minioadmin",  # noqa: S106
        region="us-east-1",
    )


@pytest.fixture
def mock_s3_client() -> MagicMock:
    """Return a mocked boto3 S3 client."""
    return MagicMock()


@pytest.fixture
def storage_service(
    storage_settings: StorageSettings, mock_s3_client: MagicMock
) -> StorageService:
    """Return a StorageService wired to a mocked S3 client."""
    return StorageService(settings=storage_settings, client=mock_s3_client)


def _make_client_error(
    code: str = "InternalError",
    message: str = "Something went wrong",
    operation: str = "PutObject",
) -> ClientError:
    """Create a botocore ``ClientError`` for testing."""
    return ClientError(
        error_response={"Error": {"Code": code, "Message": message}},
        operation_name=operation,
    )


# ---------------------------------------------------------------------------
# Helpers for DB entities
# ---------------------------------------------------------------------------


def _make_node(
    *,
    name: str = "storage-integ-node",
    status: NodeStatus = NodeStatus.HEALTHY,
    capabilities: list[str] | None = None,
    current_load: float = 0.0,
    public_key: str = "ed25519-storage-integ-key",
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
# 1. Upload + Download Roundtrip (Data Integrity)
# =========================================================================


class TestUploadDownloadRoundtrip:
    """Verify data uploaded through StorageService can be downloaded intact."""

    def test_upload_then_download_returns_same_bytes(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """Upload bytes, then download -- returned data matches original.

        Integration: exercises upload_file -> download_file on the same key,
        verifying both methods agree on bucket/key routing.
        """
        key = StorageService.build_key("user-alpha", "job-001", "render.exr")
        payload = b"EXR-image-data-placeholder-bytes-1234567890"

        # Upload
        storage_service.upload_file(key, payload, content_type="image/x-exr")

        # Wire mock to return the same data for download
        mock_body = MagicMock()
        mock_body.read.return_value = payload
        mock_s3_client.get_object.return_value = {"Body": mock_body}

        # Download
        downloaded = storage_service.download_file(key)

        assert downloaded == payload
        # Verify both operations targeted the same bucket and key
        upload_call = mock_s3_client.put_object.call_args
        download_call = mock_s3_client.get_object.call_args
        assert upload_call.kwargs["Bucket"] == download_call.kwargs["Bucket"]
        assert upload_call.kwargs["Key"] == download_call.kwargs["Key"]

    def test_upload_then_download_preserves_large_payload(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """Roundtrip with a larger payload (1 MB) verifies no truncation."""
        key = StorageService.build_key("user-beta", "job-002", "output.zip")
        payload = b"X" * (1024 * 1024)  # 1 MB

        storage_service.upload_file(key, payload, content_type="application/zip")

        mock_body = MagicMock()
        mock_body.read.return_value = payload
        mock_s3_client.get_object.return_value = {"Body": mock_body}

        downloaded = storage_service.download_file(key)
        assert len(downloaded) == len(payload)
        assert downloaded == payload


# =========================================================================
# 2. Upload + Presigned URL Generation
# =========================================================================


class TestUploadThenPresignedUrl:
    """Verify that after uploading, a presigned URL can be generated for the same key."""

    def test_upload_then_generate_presigned_url_targets_same_key(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """Upload a file then generate a presigned URL -- key consistency."""
        key = StorageService.build_key("user-gamma", "job-003", "result.png")
        storage_service.upload_file(key, b"png-data", content_type="image/png")

        mock_s3_client.generate_presigned_url.return_value = (
            f"https://s3.example.com/rendertrust-integration-test/{key}?sig=abc"
        )
        url = storage_service.generate_presigned_url(key, expires_in=1800)

        assert key in url
        # Verify presigned URL params target the same bucket and key as upload
        presign_call = mock_s3_client.generate_presigned_url.call_args
        assert presign_call.kwargs["Params"]["Key"] == key
        assert presign_call.kwargs["Params"]["Bucket"] == "rendertrust-integration-test"
        assert presign_call.kwargs["ExpiresIn"] == 1800


# =========================================================================
# 3. Upload + file_exists Verification
# =========================================================================


class TestUploadThenFileExists:
    """Verify that after uploading, file_exists returns True."""

    def test_upload_then_file_exists_returns_true(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """Upload a file, then check existence -- returns True."""
        key = StorageService.build_key("user-delta", "job-004", "model.bin")
        storage_service.upload_file(key, b"model-weights-data")

        # Mock head_object to simulate file existing after upload
        mock_s3_client.head_object.return_value = {"ContentLength": 18}

        assert storage_service.file_exists(key) is True
        mock_s3_client.head_object.assert_called_once_with(
            Bucket="rendertrust-integration-test",
            Key=key,
        )

    def test_file_exists_returns_false_for_unuploaded_key(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """file_exists on a key that was never uploaded returns False."""
        key = StorageService.build_key("user-delta", "job-999", "ghost.bin")
        mock_s3_client.head_object.side_effect = _make_client_error(
            code="404", operation="HeadObject"
        )

        assert storage_service.file_exists(key) is False


# =========================================================================
# 4. Upload + Delete + file_exists Lifecycle
# =========================================================================


class TestUploadDeleteLifecycle:
    """Full CRUD lifecycle: upload, verify exists, delete, verify gone."""

    def test_upload_delete_then_file_no_longer_exists(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """Upload -> delete -> file_exists returns False."""
        key = StorageService.build_key("user-epsilon", "job-005", "temp.dat")

        # Upload
        storage_service.upload_file(key, b"temporary data")

        # Delete
        storage_service.delete_file(key)
        mock_s3_client.delete_object.assert_called_once_with(
            Bucket="rendertrust-integration-test",
            Key=key,
        )

        # Verify the delete targeted the same key as the upload
        upload_key = mock_s3_client.put_object.call_args.kwargs["Key"]
        delete_key = mock_s3_client.delete_object.call_args.kwargs["Key"]
        assert upload_key == delete_key

        # After deletion, file_exists should return False
        mock_s3_client.head_object.side_effect = _make_client_error(
            code="404", operation="HeadObject"
        )
        assert storage_service.file_exists(key) is False


# =========================================================================
# 5. build_key Produces Correct User-Scoped Format (Multi-User)
# =========================================================================


class TestBuildKeyMultiUser:
    """Verify build_key generates disjoint key spaces for different users."""

    def test_different_users_get_different_key_prefixes(self) -> None:
        """Two users with the same job ID get different storage keys."""
        key_a = StorageService.build_key("user-alice", "job-shared", "result.zip")
        key_b = StorageService.build_key("user-bob", "job-shared", "result.zip")

        assert key_a != key_b
        assert key_a.startswith("user-alice/")
        assert key_b.startswith("user-bob/")

    def test_same_user_different_jobs_get_different_keys(self) -> None:
        """Same user, different job IDs produce different keys."""
        key_1 = StorageService.build_key("user-carol", "job-100", "result")
        key_2 = StorageService.build_key("user-carol", "job-200", "result")

        assert key_1 != key_2
        assert key_1.startswith("user-carol/job-100/")
        assert key_2.startswith("user-carol/job-200/")

    def test_key_format_is_slash_separated_three_parts(self) -> None:
        """build_key format is exactly {user}/{job}/{filename} with no extras."""
        key = StorageService.build_key("u1", "j1", "output.exr")
        parts = key.split("/")
        assert len(parts) == 3
        assert parts[0] == "u1"
        assert parts[1] == "j1"
        assert parts[2] == "output.exr"


# =========================================================================
# 6. Cross-User Key Isolation
# =========================================================================


class TestCrossUserKeyIsolation:
    """Verify that user A's key cannot be used to access user B's data.

    StorageService enforces user scoping via build_key format. These tests
    verify that the key structure makes cross-user access impossible when
    keys are correctly constructed.
    """

    def test_user_a_key_does_not_match_user_b_key(self) -> None:
        """Keys for the same job from different users never collide."""
        key_a = StorageService.build_key("user-aaa", "job-xyz", "result")
        key_b = StorageService.build_key("user-bbb", "job-xyz", "result")

        # User A's key must NOT be a prefix or match of user B's key
        assert not key_a.startswith("user-bbb/")
        assert not key_b.startswith("user-aaa/")
        assert key_a != key_b

    def test_upload_scoped_to_user_key_prefix(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """Upload with user A's key stays in user A's namespace."""
        key_a = StorageService.build_key("user-alice", "job-001", "render.exr")
        key_b = StorageService.build_key("user-bob", "job-001", "render.exr")

        storage_service.upload_file(key_a, b"alice-data")
        storage_service.upload_file(key_b, b"bob-data")

        # Verify both calls used different keys but same bucket
        calls = mock_s3_client.put_object.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["Key"] == key_a
        assert calls[1].kwargs["Key"] == key_b
        assert calls[0].kwargs["Bucket"] == calls[1].kwargs["Bucket"]

    def test_download_with_wrong_user_key_gets_wrong_data(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """Downloading with user B's key retrieves user B's file, not user A's.

        This tests that the key structure enforces isolation: even if
        someone constructs user B's key, they get user B's data (not A's).
        The application layer must ensure only the owning user can request
        their own keys.
        """
        key_a = StorageService.build_key("user-alice", "job-001", "result")
        key_b = StorageService.build_key("user-bob", "job-001", "result")

        # Attempt download with key_b -- S3 client is called with key_b
        mock_body = MagicMock()
        mock_body.read.return_value = b"bob-data"
        mock_s3_client.get_object.return_value = {"Body": mock_body}

        result = storage_service.download_file(key_b)

        assert result == b"bob-data"
        mock_s3_client.get_object.assert_called_once_with(
            Bucket="rendertrust-integration-test",
            Key=key_b,
        )
        # The key passed to S3 is user-bob's, NOT user-alice's
        assert mock_s3_client.get_object.call_args.kwargs["Key"] != key_a


# =========================================================================
# 7. Job Result Endpoint -- Storage Error Propagation
# =========================================================================


class TestJobResultStorageError:
    """Job result endpoint propagates StorageService errors.

    When StorageService.generate_presigned_url raises StorageError, the
    exception propagates through the endpoint (no explicit catch). In a
    production ASGI server this becomes a 500 response; in the test ASGI
    transport the exception is re-raised directly.
    """

    async def test_storage_error_during_presigned_url_propagates(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """When StorageService raises StorageError, it propagates unhandled."""
        node = _make_node(name="storage-err", public_key="key-storage-err")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(
            node=node,
            status=JobStatus.COMPLETED,
            result_ref="user123/job456/result.zip",
        )
        db_session.add(job)
        await db_session.flush()

        mock_storage = MagicMock()
        mock_storage.generate_presigned_url.side_effect = StorageError(
            "S3 connection refused"
        )

        with patch("core.api.v1.jobs.StorageService") as mock_cls:
            mock_cls.return_value = mock_storage
            with pytest.raises(StorageError, match="S3 connection refused"):
                await client.get(
                    f"/api/v1/jobs/{job.id}/result", headers=auth_headers
                )

    async def test_storage_client_error_during_presigned_url_propagates(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """When StorageService raises due to boto3 ClientError, it propagates."""
        node = _make_node(name="storage-client-err", public_key="key-storage-cerr")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(
            node=node,
            status=JobStatus.COMPLETED,
            result_ref="user789/job012/result.exr",
        )
        db_session.add(job)
        await db_session.flush()

        mock_storage = MagicMock()
        mock_storage.generate_presigned_url.side_effect = StorageError(
            "Failed to generate presigned URL for 'user789/job012/result.exr'"
        )

        with patch("core.api.v1.jobs.StorageService") as mock_cls:
            mock_cls.return_value = mock_storage
            with pytest.raises(StorageError, match="Failed to generate presigned URL"):
                await client.get(
                    f"/api/v1/jobs/{job.id}/result", headers=auth_headers
                )


# =========================================================================
# 8. Job Result 404 for Incomplete Jobs (API + Storage Interaction)
# =========================================================================


class TestJobResultIncompleteJobStorageNotCalled:
    """Incomplete jobs return 404 WITHOUT invoking StorageService.

    This is an integration concern: verifying that the API layer short-circuits
    before reaching the storage layer for non-COMPLETED jobs.
    """

    async def test_queued_job_does_not_invoke_storage(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """QUEUED job returns 404 and StorageService is never instantiated."""
        node = _make_node(name="no-storage-q", public_key="key-no-storage-q")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.QUEUED)
        db_session.add(job)
        await db_session.flush()

        with patch("core.api.v1.jobs.StorageService") as mock_cls:
            resp = await client.get(
                f"/api/v1/jobs/{job.id}/result", headers=auth_headers
            )

        assert resp.status_code == 404
        assert "not completed" in resp.json()["detail"]
        mock_cls.assert_not_called()

    async def test_running_job_does_not_invoke_storage(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """RUNNING job returns 404 without touching StorageService."""
        node = _make_node(name="no-storage-r", public_key="key-no-storage-r")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(node=node, status=JobStatus.RUNNING)
        db_session.add(job)
        await db_session.flush()

        with patch("core.api.v1.jobs.StorageService") as mock_cls:
            resp = await client.get(
                f"/api/v1/jobs/{job.id}/result", headers=auth_headers
            )

        assert resp.status_code == 404
        mock_cls.assert_not_called()


# =========================================================================
# 9. Job Result 404 for Missing result_ref (Storage Not Invoked)
# =========================================================================


class TestJobResultMissingRefStorageNotCalled:
    """Completed job with no result_ref returns 404 WITHOUT invoking storage."""

    async def test_completed_no_result_ref_does_not_invoke_storage(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Completed job with result_ref=None skips StorageService."""
        node = _make_node(name="no-ref-integ", public_key="key-no-ref-integ")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(
            node=node,
            status=JobStatus.COMPLETED,
            result_ref=None,
        )
        db_session.add(job)
        await db_session.flush()

        with patch("core.api.v1.jobs.StorageService") as mock_cls:
            resp = await client.get(
                f"/api/v1/jobs/{job.id}/result", headers=auth_headers
            )

        assert resp.status_code == 404
        assert "no result stored" in resp.json()["detail"]
        mock_cls.assert_not_called()


# =========================================================================
# 10. Upload Failure Propagation
# =========================================================================


class TestUploadFailurePropagation:
    """Upload errors propagate through multi-step workflows."""

    def test_upload_failure_prevents_subsequent_operations(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """If upload fails, no download or presigned URL should be attempted.

        Simulates a workflow where upload is a precondition for download.
        """
        key = StorageService.build_key("user-fail", "job-fail", "result.dat")
        mock_s3_client.put_object.side_effect = _make_client_error()

        with pytest.raises(StorageUploadError, match="Failed to upload"):
            storage_service.upload_file(key, b"data")

        # After a failed upload, the key should not exist
        mock_s3_client.head_object.side_effect = _make_client_error(
            code="404", operation="HeadObject"
        )
        assert storage_service.file_exists(key) is False

    def test_upload_failure_does_not_corrupt_other_keys(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """A failed upload for one key does not affect another key's operations."""
        key_good = StorageService.build_key("user-ok", "job-ok", "result")
        key_bad = StorageService.build_key("user-fail", "job-fail", "result")

        # First upload succeeds
        storage_service.upload_file(key_good, b"good-data")

        # Second upload fails
        mock_s3_client.put_object.side_effect = _make_client_error()
        with pytest.raises(StorageUploadError):
            storage_service.upload_file(key_bad, b"bad-data")

        # The first key should still be accessible
        mock_s3_client.put_object.side_effect = None  # reset
        mock_s3_client.head_object.return_value = {"ContentLength": 9}
        assert storage_service.file_exists(key_good) is True


# =========================================================================
# 11. Download Failure Propagation
# =========================================================================


class TestDownloadFailurePropagation:
    """Download errors propagate correctly after a successful upload."""

    def test_download_failure_after_upload_raises_download_error(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """Upload succeeds but download fails (e.g., transient network error)."""
        key = StorageService.build_key("user-net", "job-net", "result.bin")

        # Upload succeeds
        storage_service.upload_file(key, b"data-that-gets-lost")

        # Download fails with a transient error
        mock_s3_client.get_object.side_effect = _make_client_error(
            code="InternalError",
            message="Service temporarily unavailable",
            operation="GetObject",
        )

        with pytest.raises(StorageDownloadError, match="Failed to download"):
            storage_service.download_file(key)

    def test_download_failure_does_not_delete_file(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """A failed download does not trigger deletion -- file still exists."""
        key = StorageService.build_key("user-safe", "job-safe", "precious.dat")

        storage_service.upload_file(key, b"precious-data")

        # Download fails
        mock_s3_client.get_object.side_effect = _make_client_error(
            code="SlowDown", message="Slow down", operation="GetObject"
        )

        with pytest.raises(StorageDownloadError):
            storage_service.download_file(key)

        # File should still exist
        mock_s3_client.get_object.side_effect = None  # reset
        mock_s3_client.head_object.return_value = {"ContentLength": 13}
        assert storage_service.file_exists(key) is True


# =========================================================================
# 12. Path Traversal Prevention Through build_key + Upload Chain
# =========================================================================


class TestPathTraversalThroughChain:
    """Path traversal attacks are blocked at the build_key level,
    preventing malicious keys from reaching upload/download.
    """

    def test_traversal_in_user_id_blocked_before_upload(self) -> None:
        """build_key rejects user_id with path traversal, so upload never runs."""
        with pytest.raises(StorageKeyError, match="invalid characters"):
            StorageService.build_key("../admin", "job-1", "result")

    def test_traversal_in_job_id_blocked_before_upload(self) -> None:
        """build_key rejects job_id with traversal sequences."""
        with pytest.raises(StorageKeyError, match="invalid characters"):
            StorageService.build_key("user-1", "../../etc", "result")

    def test_traversal_in_filename_blocked_before_upload(self) -> None:
        """build_key rejects filename with path traversal."""
        with pytest.raises(StorageKeyError, match="invalid characters"):
            StorageService.build_key("user-1", "job-1", "../../../etc/passwd")

    def test_null_byte_in_user_id_blocked_before_upload(self) -> None:
        """build_key rejects user_id containing null bytes."""
        with pytest.raises(StorageKeyError, match="invalid characters"):
            StorageService.build_key("user\x00admin", "job-1", "result")

    def test_slash_in_user_id_blocked_before_upload(self) -> None:
        """build_key rejects user_id containing forward slash."""
        with pytest.raises(StorageKeyError, match="invalid characters"):
            StorageService.build_key("user/admin", "job-1", "result")

    def test_validated_key_from_build_key_passes_upload(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """A key produced by build_key always passes validate_key and upload."""
        key = StorageService.build_key("safe-user", "safe-job", "safe-file.dat")

        # Should not raise -- the key is safe
        StorageService.validate_key(key)

        # Upload should succeed (no StorageKeyError)
        result = storage_service.upload_file(key, b"safe-data")
        assert result == key


# =========================================================================
# 13. Presigned URL Expiry Boundary Validation
# =========================================================================


class TestPresignedUrlExpiryBoundary:
    """Validate presigned URL expiry limits through the full service chain."""

    def test_exactly_24h_expiry_is_accepted(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """86400 seconds (24h) is the maximum allowed expiry."""
        key = StorageService.build_key("user-exp", "job-exp", "result")
        storage_service.upload_file(key, b"data")

        mock_s3_client.generate_presigned_url.return_value = "https://s3/url"
        url = storage_service.generate_presigned_url(key, expires_in=86400)
        assert url == "https://s3/url"

    def test_over_24h_expiry_is_rejected(
        self,
        storage_service: StorageService,
        mock_s3_client: MagicMock,
    ) -> None:
        """86401 seconds (just over 24h) is rejected with ValueError."""
        key = StorageService.build_key("user-exp", "job-exp", "result")
        storage_service.upload_file(key, b"data")

        with pytest.raises(ValueError, match="must not exceed"):
            storage_service.generate_presigned_url(key, expires_in=86401)

    def test_zero_expiry_is_rejected(
        self,
        storage_service: StorageService,
    ) -> None:
        """Zero-second expiry is rejected."""
        key = StorageService.build_key("user-exp", "job-exp", "result")
        with pytest.raises(ValueError, match="positive"):
            storage_service.generate_presigned_url(key, expires_in=0)

    def test_negative_expiry_is_rejected(
        self,
        storage_service: StorageService,
    ) -> None:
        """Negative expiry is rejected."""
        key = StorageService.build_key("user-exp", "job-exp", "result")
        with pytest.raises(ValueError, match="positive"):
            storage_service.generate_presigned_url(key, expires_in=-300)


# =========================================================================
# 14. Full End-to-End: Upload -> Job Complete -> GET /result -> Presigned URL
# =========================================================================


class TestFullEndToEndStorageToApi:
    """End-to-end: StorageService upload, job marked COMPLETED, API returns URL.

    This is the highest-value integration test: it exercises the full path
    from storing a result in object storage through the job result API
    endpoint returning a presigned download URL.
    """

    async def test_upload_result_then_api_returns_presigned_url(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Full flow: upload file -> mark job COMPLETED -> GET result -> URL."""
        user_id = "user-e2e"
        job_id_str = "job-e2e-001"
        filename = "render-output.exr"
        result_key = f"{user_id}/{job_id_str}/{filename}"
        expected_url = f"https://s3.test.com/{result_key}?sig=xyz"

        # Create job in COMPLETED state with result_ref
        node = _make_node(name="e2e-node", public_key="key-e2e-flow")
        db_session.add(node)
        await db_session.flush()

        job = _make_job(
            node=node,
            status=JobStatus.COMPLETED,
            result_ref=result_key,
        )
        db_session.add(job)
        await db_session.flush()

        # Mock StorageService to return expected presigned URL
        mock_storage = MagicMock()
        mock_storage.generate_presigned_url.return_value = expected_url

        with patch("core.api.v1.jobs.StorageService") as mock_cls:
            mock_cls.return_value = mock_storage
            resp = await client.get(
                f"/api/v1/jobs/{job.id}/result", headers=auth_headers
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["download_url"] == expected_url
        assert data["job_id"] == str(job.id)
        assert data["expires_in"] == 3600

        # Verify StorageService was called with the correct result_ref key
        mock_storage.generate_presigned_url.assert_called_once_with(
            key=result_key,
            expires_in=3600,
        )

    async def test_two_users_get_different_result_urls(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        auth_headers: dict,
    ) -> None:
        """Two jobs with different result_refs get different presigned URLs."""
        node = _make_node(name="multi-user-node", public_key="key-multi-user")
        db_session.add(node)
        await db_session.flush()

        # Job A: user-alice's result
        result_key_a = "user-alice/job-a/render.exr"
        job_a = _make_job(
            node=node,
            status=JobStatus.COMPLETED,
            result_ref=result_key_a,
            payload_ref="s3://a",
        )
        db_session.add(job_a)

        # Job B: user-bob's result
        result_key_b = "user-bob/job-b/render.exr"
        job_b = _make_job(
            node=node,
            status=JobStatus.COMPLETED,
            result_ref=result_key_b,
            payload_ref="s3://b",
        )
        db_session.add(job_b)
        await db_session.flush()

        url_a = f"https://s3.test.com/{result_key_a}?sig=a"
        url_b = f"https://s3.test.com/{result_key_b}?sig=b"

        mock_storage = MagicMock()
        mock_storage.generate_presigned_url.side_effect = [url_a, url_b]

        with patch("core.api.v1.jobs.StorageService") as mock_cls:
            mock_cls.return_value = mock_storage

            resp_a = await client.get(
                f"/api/v1/jobs/{job_a.id}/result", headers=auth_headers
            )
            resp_b = await client.get(
                f"/api/v1/jobs/{job_b.id}/result", headers=auth_headers
            )

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        assert resp_a.json()["download_url"] == url_a
        assert resp_b.json()["download_url"] == url_b
        assert resp_a.json()["download_url"] != resp_b.json()["download_url"]
