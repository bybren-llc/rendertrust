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

"""Storage configuration via Pydantic Settings.

Loads S3-compatible storage settings from environment variables.
Defaults are configured for local MinIO development.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageSettings(BaseSettings):
    """S3-compatible object storage settings.

    Defaults target a local MinIO instance for development.
    Override via environment variables for Cloudflare R2 or AWS S3 in production.

    Environment variables::

        STORAGE_ENDPOINT_URL  -- S3-compatible endpoint (default: http://localhost:9000)
        STORAGE_BUCKET_NAME   -- Target bucket (default: rendertrust-dev)
        STORAGE_ACCESS_KEY    -- Access key ID (default: minioadmin)
        STORAGE_SECRET_KEY    -- Secret access key (default: minioadmin)
        STORAGE_REGION        -- AWS region or region hint (default: us-east-1)
        STORAGE_USE_SSL       -- Whether to use SSL for connections (default: true)
    """

    model_config = SettingsConfigDict(
        env_prefix="STORAGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    endpoint_url: str = "http://localhost:9000"
    bucket_name: str = "rendertrust-dev"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"  # noqa: S105
    region: str = "us-east-1"
    use_ssl: bool = True


@lru_cache(maxsize=1)
def get_storage_settings() -> StorageSettings:
    """Return cached storage settings (singleton).

    Uses lru_cache to ensure settings are loaded only once
    from environment variables and .env files.
    """
    return StorageSettings()
