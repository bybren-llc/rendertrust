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

"""Tests for OpenAPI documentation endpoints.

Validates that /docs, /redoc, and /openapi.json are always available
regardless of the APP_DEBUG setting.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_docs_endpoint_returns_200(client: AsyncClient) -> None:
    """GET /docs returns 200 (Swagger UI)."""
    response = await client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_redoc_endpoint_returns_200(client: AsyncClient) -> None:
    """GET /redoc returns 200 (ReDoc UI)."""
    response = await client.get("/redoc")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_openapi_json_returns_valid_spec(client: AsyncClient) -> None:
    """GET /openapi.json returns valid OpenAPI JSON with expected fields."""
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]

    spec = response.json()
    assert "openapi" in spec
    assert spec["openapi"].startswith("3.")
    assert "info" in spec
    assert spec["info"]["title"] == "RenderTrust API"
    assert "paths" in spec


@pytest.mark.asyncio
async def test_openapi_spec_contains_health_path(client: AsyncClient) -> None:
    """The OpenAPI spec should include the /health endpoint."""
    response = await client.get("/openapi.json")
    spec = response.json()
    assert "/health" in spec["paths"]
