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

"""Integration tests for health check endpoints.

Covers:
- Liveness probe schema validation (/health, /api/v1/health)
- Version endpoint schema validation (/version)
- Readiness probe (/api/v1/health/ready):
  - Database connectivity check
  - Redis connectivity check
  - Degraded state when Redis is unavailable
  - Ready state when all services are available (mocked Redis)
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient


# ═══════════════════════════════════════════════════════════════════════════
# Liveness probes — schema validation
# ═══════════════════════════════════════════════════════════════════════════
class TestLivenessProbes:
    """Validate liveness probe response schemas."""

    @pytest.mark.integration
    async def test_root_health_schema(self, client: AsyncClient) -> None:
        """GET /health response contains all expected keys."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert data["status"] == "healthy"
        assert data["version"] == "0.1.0"

    @pytest.mark.integration
    async def test_api_v1_health_includes_environment(self, client: AsyncClient) -> None:
        """GET /api/v1/health returns environment field."""
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "environment" in data
        assert "status" in data
        assert "version" in data
        assert data["status"] == "healthy"
        assert data["version"] == "0.1.0"

    @pytest.mark.integration
    async def test_health_response_is_json(self, client: AsyncClient) -> None:
        """GET /health returns application/json content type."""
        response = await client.get("/health")
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "application/json" in content_type


# ═══════════════════════════════════════════════════════════════════════════
# Version endpoint — schema validation
# ═══════════════════════════════════════════════════════════════════════════
class TestVersionEndpoint:
    """Validate version endpoint response schema."""

    @pytest.mark.integration
    async def test_version_response_schema(self, client: AsyncClient) -> None:
        """GET /version has name, version, and environment keys."""
        response = await client.get("/version")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "environment" in data
        assert data["name"] == "rendertrust"
        assert data["version"] == "0.1.0"


# ═══════════════════════════════════════════════════════════════════════════
# Readiness probe — /api/v1/health/ready
# ═══════════════════════════════════════════════════════════════════════════
class TestReadinessProbe:
    """Validate the readiness probe endpoint behaviour."""

    @pytest.mark.integration
    async def test_readiness_returns_200(self, client: AsyncClient) -> None:
        """GET /api/v1/health/ready returns 200 regardless of service state."""
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 200

    @pytest.mark.integration
    async def test_readiness_checks_database(self, client: AsyncClient) -> None:
        """Readiness response includes a database check."""
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert "checks" in data
        assert "database" in data["checks"]

    @pytest.mark.integration
    async def test_readiness_checks_redis(self, client: AsyncClient) -> None:
        """Readiness response includes a Redis check."""
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert "checks" in data
        assert "redis" in data["checks"]

    @pytest.mark.integration
    async def test_readiness_status_is_ready_or_degraded(self, client: AsyncClient) -> None:
        """Status field is one of the expected values."""
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in {"ready", "degraded"}

    @pytest.mark.integration
    async def test_readiness_degraded_when_redis_unavailable(self, client: AsyncClient) -> None:
        """Without a running Redis instance, readiness reports degraded.

        The test database (SQLite in-memory) responds to ``SELECT 1``,
        so the database check passes.  Redis is not running in the test
        environment, so the endpoint should report degraded status with
        ``redis = "unavailable"``.

        When Redis IS available (CI), the endpoint returns "ready" instead,
        so we accept either outcome.
        """
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["checks"]["database"] == "connected"
        if data["checks"]["redis"] == "unavailable":
            assert data["status"] == "degraded"
        else:
            assert data["status"] == "ready"

    @pytest.mark.integration
    async def test_readiness_ready_with_all_services(self, client: AsyncClient) -> None:
        """With all services up, readiness should report ready.

        Mocks ``redis.asyncio.from_url`` inside the health module so that
        the Redis ping succeeds, while the real database check still runs
        against the test SQLite engine.
        """
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        mock_redis.aclose.return_value = None

        with patch("core.api.v1.health.aioredis.from_url", return_value=mock_redis):
            response = await client.get("/api/v1/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["checks"]["database"] == "connected"
        assert data["checks"]["redis"] == "connected"
