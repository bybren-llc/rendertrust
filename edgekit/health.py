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

"""Health check micro-service for the edge node.

Provides a minimal FastAPI application that exposes ``GET /health`` for
Docker HEALTHCHECK and container orchestrator probes.  The response
includes the relay connection status and node uptime.

Usage::

    from edgekit.health import create_health_app, set_relay_client

    set_relay_client(my_relay_client)
    app = create_health_app()
    uvicorn.run(app, host="0.0.0.0", port=8081)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from edgekit.relay.client import RelayClient

# Module-level state -- set by the entrypoint before the server starts.
_relay_client: RelayClient | None = None
_start_time: float = time.monotonic()


def set_relay_client(client: RelayClient) -> None:
    """Register the relay client so the health endpoint can report its status.

    Args:
        client: The :class:`~edgekit.relay.client.RelayClient` instance.
    """
    global _relay_client
    _relay_client = client


def get_relay_client() -> RelayClient | None:
    """Return the currently registered relay client (or ``None``)."""
    return _relay_client


def reset_start_time() -> None:
    """Reset the uptime counter (primarily for testing)."""
    global _start_time
    _start_time = time.monotonic()


def create_health_app() -> FastAPI:
    """Create and return the health-check FastAPI application.

    Returns:
        A :class:`FastAPI` instance with a single ``/health`` endpoint.
    """
    app = FastAPI(
        title="EdgeNode Health",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health")
    async def health_check() -> JSONResponse:
        """Return current health status of the edge node.

        Response body::

            {
                "status": "ok",
                "connected": true,
                "uptime_seconds": 123.45
            }

        ``connected`` reflects whether the relay WebSocket is currently open.
        """
        connected = False
        if _relay_client is not None:
            connected = _relay_client.connected

        uptime = round(time.monotonic() - _start_time, 2)

        return JSONResponse(
            content={
                "status": "ok",
                "connected": connected,
                "uptime_seconds": uptime,
            }
        )

    return app
