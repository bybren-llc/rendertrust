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

"""x402 payment middleware for FastAPI.

Provides configuration and initialization for x402 HTTP 402 payment
protocol integration. Enables per-route payment requirements using
stablecoins on EVM-compatible chains.

Usage:
    from core.gateway.x402.middleware import configure_x402

    app = FastAPI()
    configure_x402(app, pay_to="0x...", routes=route_configs)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = structlog.get_logger(__name__)


def configure_x402(
    app: FastAPI,
    pay_to: str,
    facilitator_url: str = "https://x402.org/facilitator",
    network: str = "eip155:84532",  # Base Sepolia
    routes: dict | None = None,
) -> None:
    """Configure x402 payment middleware on a FastAPI application.

    Args:
        app: The FastAPI application instance.
        pay_to: The wallet address to receive payments (EVM address).
        facilitator_url: URL of the x402 facilitator service.
        network: CAIP-2 chain identifier (default: Base Sepolia testnet).
        routes: Dict mapping route patterns to payment configurations.
            Example: {"POST /v1/x402/compute": {"price": "$0.10", "description": "Compute job"}}
    """
    try:
        from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
        from x402.http.middleware.fastapi import payment_middleware
        from x402.http.types import RouteConfig
        from x402.mechanisms.evm.exact import ExactEvmServerScheme
        from x402.server import x402ResourceServer
    except ImportError:
        logger.warning(
            "x402_sdk_not_installed",
            msg="x402 SDK not installed. Install with: pip install x402",
        )
        return

    if not pay_to:
        logger.warning("x402_no_pay_to_address", msg="x402 disabled: no pay_to address configured")
        return

    if routes is None:
        routes = {}

    facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=facilitator_url))
    server = x402ResourceServer(facilitator)
    server.register(network, ExactEvmServerScheme())

    route_configs = {}
    for route_pattern, config in routes.items():
        route_configs[route_pattern] = RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    pay_to=pay_to,
                    price=config.get("price", "$0.01"),
                    network=network,
                )
            ],
            description=config.get("description", "Paid endpoint"),
        )

    @app.middleware("http")
    async def x402_mw(request, call_next):
        return await payment_middleware(route_configs, server)(request, call_next)

    logger.info(
        "x402_configured",
        network=network,
        pay_to=pay_to,
        facilitator_url=facilitator_url,
        route_count=len(route_configs),
    )
