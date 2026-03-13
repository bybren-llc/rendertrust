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

"""S3-compatible object storage service.

Provides an abstraction layer for file storage operations using boto3.
Works with MinIO (development), Cloudflare R2, and AWS S3.

All storage keys MUST be user-scoped with the format:
    ``{user_id}/{job_id}/result``

This prevents cross-user access at the application level.
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING, BinaryIO

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from core.storage.config import StorageSettings, get_storage_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Base exception for storage operations."""


class StorageUploadError(StorageError):
    """Raised when a file upload fails."""


class StorageDownloadError(StorageError):
    """Raised when a file download fails."""


class StorageDeleteError(StorageError):
    """Raised when a file deletion fails."""


class StorageKeyError(StorageError):
    """Raised when a storage key is invalid."""


class StorageService:
    """S3-compatible object storage service.

    Provides methods for uploading, downloading, and managing files
    in an S3-compatible object store (MinIO, Cloudflare R2, AWS S3).

    Args:
        settings: Storage configuration. If ``None``, loads from environment.
        client: Pre-configured boto3 S3 client. If ``None``, creates one from settings.
    """

    def __init__(
        self,
        settings: StorageSettings | None = None,
        client: S3Client | None = None,
    ) -> None:
        self._settings = settings or get_storage_settings()
        self._client: S3Client = client or self._create_client()

    def _create_client(self) -> S3Client:
        """Create a boto3 S3 client from storage settings."""
        return boto3.client(
            "s3",
            endpoint_url=self._settings.endpoint_url,
            aws_access_key_id=self._settings.access_key.get_secret_value(),
            aws_secret_access_key=self._settings.secret_key.get_secret_value(),
            region_name=self._settings.region,
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )

    @property
    def bucket_name(self) -> str:
        """Return the configured bucket name."""
        return self._settings.bucket_name

    @staticmethod
    def validate_key(key: str) -> None:
        """Validate that a storage key is well-formed.

        Keys must be non-empty and should follow the user-scoped format:
        ``{user_id}/{job_id}/result`` or similar hierarchical structure.

        Args:
            key: The storage key to validate.

        Raises:
            StorageKeyError: If the key is empty or invalid.
        """
        if not key or not key.strip():
            raise StorageKeyError("Storage key must not be empty")
        if key.startswith("/"):
            raise StorageKeyError("Storage key must not start with '/'")
        if ".." in key:
            raise StorageKeyError("Storage key must not contain '..' path traversal sequences")
        if "\x00" in key:
            raise StorageKeyError("Storage key must not contain null bytes")

    @staticmethod
    def build_key(user_id: str, job_id: str, filename: str = "result") -> str:
        """Build a user-scoped storage key.

        Args:
            user_id: The user identifier.
            job_id: The job identifier.
            filename: The filename or suffix (default: ``"result"``).

        Returns:
            A key in the format ``{user_id}/{job_id}/{filename}``.

        Raises:
            StorageKeyError: If any component is empty or contains invalid characters.
        """
        for name, value in [("user_id", user_id), ("job_id", job_id), ("filename", filename)]:
            if not value:
                raise StorageKeyError(f"{name} must not be empty")
            if "/" in value or ".." in value or "\x00" in value:
                raise StorageKeyError(f"{name} contains invalid characters")
        return f"{user_id}/{job_id}/{filename}"

    def upload_file(
        self,
        key: str,
        data: bytes | BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload a file to object storage.

        Args:
            key: The storage key (should be user-scoped).
            data: File content as bytes or a file-like object.
            content_type: MIME type of the file.

        Returns:
            The storage key of the uploaded file.

        Raises:
            StorageUploadError: If the upload fails.
            StorageKeyError: If the key is invalid.
        """
        self.validate_key(key)

        try:
            if isinstance(data, bytes):
                body: BinaryIO = io.BytesIO(data)
            else:
                body = data

            self._client.put_object(
                Bucket=self._settings.bucket_name,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
            logger.info("Uploaded file to storage", extra={"key": key, "bucket": self.bucket_name})
        except ClientError as exc:
            logger.exception("Failed to upload file", extra={"key": key})
            raise StorageUploadError(f"Failed to upload '{key}': {exc}") from exc

        return key

    def download_file(self, key: str) -> bytes:
        """Download a file from object storage.

        Args:
            key: The storage key of the file to download.

        Returns:
            The file content as bytes.

        Raises:
            StorageDownloadError: If the download fails (including file not found).
            StorageKeyError: If the key is invalid.
        """
        self.validate_key(key)

        try:
            response = self._client.get_object(
                Bucket=self._settings.bucket_name,
                Key=key,
            )
            return response["Body"].read()
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            logger.exception(
                "Failed to download file",
                extra={"key": key, "error_code": error_code},
            )
            raise StorageDownloadError(f"Failed to download '{key}': {exc}") from exc

    def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a presigned URL for downloading a file.

        Args:
            key: The storage key of the file.
            expires_in: URL expiry time in seconds (default: 3600 = 1 hour).

        Returns:
            A presigned URL string.

        Raises:
            StorageError: If URL generation fails.
            StorageKeyError: If the key is invalid.
            ValueError: If expires_in is not positive.
        """
        self.validate_key(key)

        max_expiry = 86400  # 24 hours
        if expires_in <= 0:
            raise ValueError("expires_in must be a positive integer")
        if expires_in > max_expiry:
            raise ValueError(f"expires_in must not exceed {max_expiry} seconds (24 hours)")

        try:
            url: str = self._client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self._settings.bucket_name,
                    "Key": key,
                },
                ExpiresIn=expires_in,
            )
            logger.info(
                "Generated presigned URL",
                extra={"key": key, "expires_in": expires_in},
            )
            return url
        except ClientError as exc:
            logger.exception("Failed to generate presigned URL", extra={"key": key})
            raise StorageError(f"Failed to generate presigned URL for '{key}': {exc}") from exc

    def delete_file(self, key: str) -> None:
        """Delete a file from object storage.

        Args:
            key: The storage key of the file to delete.

        Raises:
            StorageDeleteError: If the deletion fails.
            StorageKeyError: If the key is invalid.
        """
        self.validate_key(key)

        try:
            self._client.delete_object(
                Bucket=self._settings.bucket_name,
                Key=key,
            )
            logger.info("Deleted file from storage", extra={"key": key, "bucket": self.bucket_name})
        except ClientError as exc:
            logger.exception("Failed to delete file", extra={"key": key})
            raise StorageDeleteError(f"Failed to delete '{key}': {exc}") from exc

    def file_exists(self, key: str) -> bool:
        """Check whether a file exists in object storage.

        Args:
            key: The storage key to check.

        Returns:
            ``True`` if the file exists, ``False`` otherwise.

        Raises:
            StorageKeyError: If the key is invalid.
            StorageError: If the existence check fails for a reason other
                than the file not existing.
        """
        self.validate_key(key)

        try:
            self._client.head_object(
                Bucket=self._settings.bucket_name,
                Key=key,
            )
            return True
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            if error_code in ("404", "NoSuchKey"):
                return False
            logger.exception("Failed to check file existence", extra={"key": key})
            raise StorageError(f"Failed to check existence of '{key}': {exc}") from exc
