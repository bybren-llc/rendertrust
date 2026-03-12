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

"""Unit tests for the object storage service.

Covers:
 1. Upload file with bytes data
 2. Upload file with BinaryIO (file-like) data
 3. Upload returns the storage key
 4. Upload sets correct content type
 5. Upload with invalid key raises StorageKeyError
 6. Upload failure raises StorageUploadError
 7. Download file returns bytes
 8. Download missing file raises StorageDownloadError
 9. Download with invalid key raises StorageKeyError
10. Generate presigned URL returns a URL string
11. Generate presigned URL with custom expiry
12. Generate presigned URL with invalid expiry raises ValueError
13. Delete file calls delete_object
14. Delete failure raises StorageDeleteError
15. file_exists returns True when file exists
16. file_exists returns False when file does not exist
17. file_exists raises StorageError on unexpected error
18. build_key produces correct user-scoped format
19. build_key with empty components raises StorageKeyError
20. validate_key rejects empty keys
21. validate_key rejects keys starting with slash
22. StorageSettings loads defaults for MinIO dev
23. StorageService creates client from settings

Uses mocked boto3 -- no actual S3/MinIO connection required.
"""

from __future__ import annotations

import io
import os
from unittest.mock import MagicMock, patch

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
from botocore.exceptions import ClientError

from core.storage.config import StorageSettings
from core.storage.service import (
    StorageDeleteError,
    StorageDownloadError,
    StorageError,
    StorageKeyError,
    StorageService,
    StorageUploadError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def storage_settings() -> StorageSettings:
    """Return StorageSettings with MinIO development defaults."""
    return StorageSettings(
        endpoint_url="http://localhost:9000",
        bucket_name="rendertrust-test",
        access_key="minioadmin",
        secret_key="minioadmin",  # noqa: S106
        region="us-east-1",
    )


@pytest.fixture
def mock_s3_client() -> MagicMock:
    """Return a mocked boto3 S3 client."""
    return MagicMock()


@pytest.fixture
def storage_service(storage_settings: StorageSettings, mock_s3_client: MagicMock) -> StorageService:
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
# Upload Tests
# ---------------------------------------------------------------------------


class TestUploadFile:
    """Tests for StorageService.upload_file."""

    def test_upload_bytes_data(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """Upload with bytes data calls put_object with a BytesIO body."""
        key = "user-123/job-456/result"
        data = b"hello world"

        result = storage_service.upload_file(key, data, content_type="text/plain")

        assert result == key
        mock_s3_client.put_object.assert_called_once()
        call_kwargs = mock_s3_client.put_object.call_args
        assert call_kwargs.kwargs["Bucket"] == "rendertrust-test"
        assert call_kwargs.kwargs["Key"] == key
        assert call_kwargs.kwargs["ContentType"] == "text/plain"

    def test_upload_file_like_data(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """Upload with a file-like object passes it directly as Body."""
        key = "user-123/job-456/payload.zip"
        data = io.BytesIO(b"binary content")

        result = storage_service.upload_file(key, data, content_type="application/zip")

        assert result == key
        call_kwargs = mock_s3_client.put_object.call_args
        assert call_kwargs.kwargs["Body"] is data

    def test_upload_returns_key(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """upload_file returns the storage key on success."""
        key = "user-abc/job-def/result.png"
        result = storage_service.upload_file(key, b"png-data", content_type="image/png")
        assert result == key

    def test_upload_default_content_type(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """Upload without content_type defaults to application/octet-stream."""
        key = "user-123/job-456/blob"
        storage_service.upload_file(key, b"data")

        call_kwargs = mock_s3_client.put_object.call_args
        assert call_kwargs.kwargs["ContentType"] == "application/octet-stream"

    def test_upload_invalid_key_raises_key_error(
        self, storage_service: StorageService
    ) -> None:
        """Upload with an empty key raises StorageKeyError."""
        with pytest.raises(StorageKeyError, match="must not be empty"):
            storage_service.upload_file("", b"data")

    def test_upload_key_starting_with_slash_raises_key_error(
        self, storage_service: StorageService
    ) -> None:
        """Upload with a key starting with '/' raises StorageKeyError."""
        with pytest.raises(StorageKeyError, match="must not start with"):
            storage_service.upload_file("/bad/key", b"data")

    def test_upload_failure_raises_upload_error(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """Upload that triggers a ClientError raises StorageUploadError."""
        mock_s3_client.put_object.side_effect = _make_client_error()

        with pytest.raises(StorageUploadError, match="Failed to upload"):
            storage_service.upload_file("user-1/job-1/result", b"data")


# ---------------------------------------------------------------------------
# Download Tests
# ---------------------------------------------------------------------------


class TestDownloadFile:
    """Tests for StorageService.download_file."""

    def test_download_returns_bytes(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """download_file returns the file content as bytes."""
        content = b"file content here"
        mock_body = MagicMock()
        mock_body.read.return_value = content
        mock_s3_client.get_object.return_value = {"Body": mock_body}

        result = storage_service.download_file("user-1/job-1/result")

        assert result == content
        mock_s3_client.get_object.assert_called_once_with(
            Bucket="rendertrust-test",
            Key="user-1/job-1/result",
        )

    def test_download_missing_file_raises_download_error(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """download_file raises StorageDownloadError when file does not exist."""
        mock_s3_client.get_object.side_effect = _make_client_error(
            code="NoSuchKey",
            message="The specified key does not exist.",
            operation="GetObject",
        )

        with pytest.raises(StorageDownloadError, match="Failed to download"):
            storage_service.download_file("user-1/job-1/missing")

    def test_download_invalid_key_raises_key_error(
        self, storage_service: StorageService
    ) -> None:
        """download_file with an empty key raises StorageKeyError."""
        with pytest.raises(StorageKeyError):
            storage_service.download_file("")


# ---------------------------------------------------------------------------
# Presigned URL Tests
# ---------------------------------------------------------------------------


class TestGeneratePresignedUrl:
    """Tests for StorageService.generate_presigned_url."""

    def test_generate_presigned_url_returns_string(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """generate_presigned_url returns a URL string."""
        expected_url = "https://s3.example.com/bucket/key?signature=abc"
        mock_s3_client.generate_presigned_url.return_value = expected_url

        result = storage_service.generate_presigned_url("user-1/job-1/result")

        assert result == expected_url
        mock_s3_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={
                "Bucket": "rendertrust-test",
                "Key": "user-1/job-1/result",
            },
            ExpiresIn=3600,
        )

    def test_generate_presigned_url_custom_expiry(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """generate_presigned_url respects custom expires_in."""
        mock_s3_client.generate_presigned_url.return_value = "https://example.com/url"

        storage_service.generate_presigned_url("user-1/job-1/result", expires_in=7200)

        call_kwargs = mock_s3_client.generate_presigned_url.call_args
        assert call_kwargs.kwargs["ExpiresIn"] == 7200

    def test_generate_presigned_url_invalid_expiry_raises_value_error(
        self, storage_service: StorageService
    ) -> None:
        """generate_presigned_url with non-positive expiry raises ValueError."""
        with pytest.raises(ValueError, match="expires_in must be a positive"):
            storage_service.generate_presigned_url("user-1/job-1/result", expires_in=0)

        with pytest.raises(ValueError, match="expires_in must be a positive"):
            storage_service.generate_presigned_url("user-1/job-1/result", expires_in=-100)

    def test_generate_presigned_url_invalid_key_raises_key_error(
        self, storage_service: StorageService
    ) -> None:
        """generate_presigned_url with an empty key raises StorageKeyError."""
        with pytest.raises(StorageKeyError):
            storage_service.generate_presigned_url("")


# ---------------------------------------------------------------------------
# Delete Tests
# ---------------------------------------------------------------------------


class TestDeleteFile:
    """Tests for StorageService.delete_file."""

    def test_delete_calls_delete_object(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """delete_file calls S3 delete_object with correct params."""
        storage_service.delete_file("user-1/job-1/result")

        mock_s3_client.delete_object.assert_called_once_with(
            Bucket="rendertrust-test",
            Key="user-1/job-1/result",
        )

    def test_delete_failure_raises_delete_error(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """delete_file raises StorageDeleteError on ClientError."""
        mock_s3_client.delete_object.side_effect = _make_client_error(
            operation="DeleteObject"
        )

        with pytest.raises(StorageDeleteError, match="Failed to delete"):
            storage_service.delete_file("user-1/job-1/result")

    def test_delete_invalid_key_raises_key_error(
        self, storage_service: StorageService
    ) -> None:
        """delete_file with an empty key raises StorageKeyError."""
        with pytest.raises(StorageKeyError):
            storage_service.delete_file("")


# ---------------------------------------------------------------------------
# file_exists Tests
# ---------------------------------------------------------------------------


class TestFileExists:
    """Tests for StorageService.file_exists."""

    def test_file_exists_returns_true(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """file_exists returns True when head_object succeeds."""
        mock_s3_client.head_object.return_value = {"ContentLength": 1024}

        assert storage_service.file_exists("user-1/job-1/result") is True

    def test_file_exists_returns_false_for_missing_file(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """file_exists returns False when file does not exist (404)."""
        mock_s3_client.head_object.side_effect = _make_client_error(
            code="404", operation="HeadObject"
        )

        assert storage_service.file_exists("user-1/job-1/missing") is False

    def test_file_exists_returns_false_for_no_such_key(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """file_exists returns False for NoSuchKey error code."""
        mock_s3_client.head_object.side_effect = _make_client_error(
            code="NoSuchKey", operation="HeadObject"
        )

        assert storage_service.file_exists("user-1/job-1/missing") is False

    def test_file_exists_raises_on_unexpected_error(
        self, storage_service: StorageService, mock_s3_client: MagicMock
    ) -> None:
        """file_exists raises StorageError on non-404 ClientError."""
        mock_s3_client.head_object.side_effect = _make_client_error(
            code="AccessDenied", operation="HeadObject"
        )

        with pytest.raises(StorageError, match="Failed to check existence"):
            storage_service.file_exists("user-1/job-1/result")

    def test_file_exists_invalid_key_raises_key_error(
        self, storage_service: StorageService
    ) -> None:
        """file_exists with an empty key raises StorageKeyError."""
        with pytest.raises(StorageKeyError):
            storage_service.file_exists("")


# ---------------------------------------------------------------------------
# Key Validation & Building Tests
# ---------------------------------------------------------------------------


class TestKeyValidation:
    """Tests for key validation and building utilities."""

    def test_validate_key_rejects_empty_string(self) -> None:
        """validate_key raises StorageKeyError for empty strings."""
        with pytest.raises(StorageKeyError, match="must not be empty"):
            StorageService.validate_key("")

    def test_validate_key_rejects_whitespace_only(self) -> None:
        """validate_key raises StorageKeyError for whitespace-only strings."""
        with pytest.raises(StorageKeyError, match="must not be empty"):
            StorageService.validate_key("   ")

    def test_validate_key_rejects_leading_slash(self) -> None:
        """validate_key raises StorageKeyError for keys starting with /."""
        with pytest.raises(StorageKeyError, match="must not start with"):
            StorageService.validate_key("/user/job/result")

    def test_validate_key_accepts_valid_key(self) -> None:
        """validate_key accepts a well-formed user-scoped key."""
        # Should not raise
        StorageService.validate_key("user-123/job-456/result")

    def test_build_key_produces_correct_format(self) -> None:
        """build_key produces {user_id}/{job_id}/{filename}."""
        key = StorageService.build_key("user-abc", "job-def", "result.png")
        assert key == "user-abc/job-def/result.png"

    def test_build_key_default_filename(self) -> None:
        """build_key uses 'result' as default filename."""
        key = StorageService.build_key("user-abc", "job-def")
        assert key == "user-abc/job-def/result"

    def test_build_key_empty_user_id_raises_key_error(self) -> None:
        """build_key with empty user_id raises StorageKeyError."""
        with pytest.raises(StorageKeyError, match="must not be empty"):
            StorageService.build_key("", "job-1", "result")

    def test_build_key_empty_job_id_raises_key_error(self) -> None:
        """build_key with empty job_id raises StorageKeyError."""
        with pytest.raises(StorageKeyError, match="must not be empty"):
            StorageService.build_key("user-1", "", "result")


# ---------------------------------------------------------------------------
# Configuration Tests
# ---------------------------------------------------------------------------


class TestStorageSettings:
    """Tests for StorageSettings defaults."""

    def test_default_settings_for_minio(self) -> None:
        """StorageSettings defaults match local MinIO development."""
        settings = StorageSettings()
        assert settings.endpoint_url == "http://localhost:9000"
        assert settings.bucket_name == "rendertrust-dev"
        assert settings.access_key == "minioadmin"
        assert settings.secret_key == "minioadmin"  # noqa: S105
        assert settings.region == "us-east-1"
        assert settings.use_ssl is True

    def test_settings_from_custom_values(self) -> None:
        """StorageSettings accepts custom values for R2/S3 configuration."""
        settings = StorageSettings(
            endpoint_url="https://r2.cloudflarestorage.com/account-id",
            bucket_name="rendertrust-prod",
            access_key="r2-access-key",
            secret_key="r2-secret-key",  # noqa: S106
            region="auto",
            use_ssl=True,
        )
        assert settings.endpoint_url == "https://r2.cloudflarestorage.com/account-id"
        assert settings.bucket_name == "rendertrust-prod"
        assert settings.region == "auto"


# ---------------------------------------------------------------------------
# Client Creation Tests
# ---------------------------------------------------------------------------


class TestStorageServiceInit:
    """Tests for StorageService initialization."""

    @patch("core.storage.service.boto3")
    def test_creates_client_from_settings(self, mock_boto3: MagicMock) -> None:
        """StorageService creates a boto3 S3 client when no client is provided."""
        settings = StorageSettings(
            endpoint_url="http://minio:9000",
            access_key="testkey",
            secret_key="testsecret",  # noqa: S106
            region="us-west-2",
        )
        mock_boto3.client.return_value = MagicMock()

        StorageService(settings=settings)

        mock_boto3.client.assert_called_once()
        call_kwargs = mock_boto3.client.call_args
        assert call_kwargs.args[0] == "s3"
        assert call_kwargs.kwargs["endpoint_url"] == "http://minio:9000"
        assert call_kwargs.kwargs["aws_access_key_id"] == "testkey"
        assert call_kwargs.kwargs["aws_secret_access_key"] == "testsecret"  # noqa: S105
        assert call_kwargs.kwargs["region_name"] == "us-west-2"

    def test_uses_provided_client(self, mock_s3_client: MagicMock) -> None:
        """StorageService uses an injected client instead of creating one."""
        settings = StorageSettings()
        service = StorageService(settings=settings, client=mock_s3_client)

        # Verify it uses the provided client by performing an operation
        service.delete_file("user-1/job-1/result")
        mock_s3_client.delete_object.assert_called_once()

    def test_bucket_name_property(self, storage_service: StorageService) -> None:
        """bucket_name property returns the configured bucket name."""
        assert storage_service.bucket_name == "rendertrust-test"
