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

"""Tests for health check and version endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_health_returns_200(client: AsyncClient) -> None:
    """GET /health returns 200 with healthy status."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_version_returns_app_info(client: AsyncClient) -> None:
    """GET /version returns application name and version."""
    response = await client.get("/version")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "rendertrust"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_api_v1_health_returns_200(client: AsyncClient) -> None:
    """GET /api/v1/health returns 200 with healthy status."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"
