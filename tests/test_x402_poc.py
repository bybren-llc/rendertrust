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

"""Tests for x402 PoC endpoints.

These tests verify the PoC endpoints work correctly WITHOUT the x402 SDK
installed (middleware not active). When middleware is inactive, the compute
endpoint returns 200 directly (no payment wall).
"""

from __future__ import annotations

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Route handler tests -- call route functions directly (no HTTP transport)
# ---------------------------------------------------------------------------


async def test_x402_pricing_endpoint():
    """x402 pricing endpoint returns pricing info."""
    from core.gateway.x402.routes import x402_pricing

    result = await x402_pricing()
    assert "endpoints" in result
    assert "facilitator" in result
    assert "POST /api/v1/x402/compute" in result["endpoints"]
    endpoint_info = result["endpoints"]["POST /api/v1/x402/compute"]
    assert endpoint_info["price_usd"] == "0.01"
    assert endpoint_info["network"] == "eip155:84532"
    assert endpoint_info["asset"] == "USDC"
    assert endpoint_info["scheme"] == "exact"


async def test_x402_compute_endpoint():
    """x402 compute endpoint returns result when no payment wall is active."""
    from core.gateway.x402.routes import x402_compute

    result = await x402_compute()
    assert result["status"] == "completed"
    assert result["payment_verified"] is True
    assert "job_id" in result
    assert "result_hash" in result
    assert len(result["result_hash"]) == 64  # SHA-256 hex digest
    assert "compute_time_ms" in result


async def test_x402_compute_unique_results():
    """Each compute call returns a unique job_id and result_hash."""
    from core.gateway.x402.routes import x402_compute

    result1 = await x402_compute()
    result2 = await x402_compute()
    assert result1["job_id"] != result2["job_id"]
    assert result1["result_hash"] != result2["result_hash"]


# ---------------------------------------------------------------------------
# Middleware configuration tests -- verify graceful degradation
# ---------------------------------------------------------------------------


async def test_x402_middleware_configure_without_sdk():
    """configure_x402 gracefully handles missing x402 SDK."""
    from core.gateway.x402.middleware import configure_x402

    app = MagicMock()

    # With empty pay_to, should gracefully skip (logs warning, no middleware added)
    configure_x402(app, pay_to="")
    # Should not have added any middleware via @app.middleware decorator
    assert not app.middleware.called


async def test_x402_middleware_configure_empty_routes():
    """configure_x402 with empty pay_to does not attach middleware."""
    from core.gateway.x402.middleware import configure_x402

    app = MagicMock()

    # Empty pay_to should skip middleware entirely
    configure_x402(app, pay_to="", routes={"POST /test": {"price": "$0.01"}})
    assert not app.middleware.called
