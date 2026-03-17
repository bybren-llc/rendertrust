# Copyright 2025 ByBren, LLC
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

"""Application configuration via Pydantic Settings.

Loads environment variables from .env files with validation.
Uses lru_cache for singleton pattern to avoid repeated I/O.
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """RenderTrust application settings.

    All values are loaded from environment variables with sensible defaults
    for local development. Production deployments MUST override SECRET_KEY
    and JWT_SECRET_KEY.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "rendertrust"
    app_env: str = "development"
    app_debug: bool = False
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    secret_key: str = "change-me-in-production"  # noqa: S105

    # Database
    database_url: str = "postgresql+asyncpg://rendertrust:rendertrust_dev@db:5432/rendertrust"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # JWT
    jwt_secret_key: str = "change-me-in-production"  # noqa: S105
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""

    # Monitoring
    sentry_dsn: str = ""
    posthog_api_key: str = ""

    # x402 Payment Protocol (PoC)
    x402_enabled: bool = False
    x402_pay_to: str = ""  # EVM wallet address to receive payments
    x402_facilitator_url: str = "https://x402.org/facilitator"
    x402_network: str = "eip155:84532"  # Base Sepolia testnet
    x402_compute_price: str = "$0.01"

    # Storage encryption
    encryption_master_key: str = "0" * 64  # 32-byte hex key, MUST change in prod

    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]
    cors_allow_methods: list[str] = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    cors_allow_headers: list[str] = ["Authorization", "Content-Type", "X-Request-ID"]

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.app_env == "production"

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "AppSettings":
        """Ensure default secrets are not used in production."""
        _default_secret = "change-me-in-production"  # noqa: S105
        if self.is_production:
            if self.secret_key == _default_secret:
                msg = "SECRET_KEY must be changed in production"
                raise ValueError(msg)
            if self.jwt_secret_key == _default_secret:
                msg = "JWT_SECRET_KEY must be changed in production"
                raise ValueError(msg)
            _default_enc_key = "0" * 64
            if self.encryption_master_key == _default_enc_key:
                msg = "ENCRYPTION_MASTER_KEY must be changed in production"
                raise ValueError(msg)
        return self


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached application settings (singleton).

    Uses lru_cache to ensure settings are loaded only once
    from environment variables and .env files.
    """
    return AppSettings()
