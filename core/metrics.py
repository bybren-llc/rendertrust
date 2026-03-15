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

"""Prometheus metrics for the RenderTrust API.

Exposes HTTP request metrics via middleware and custom business metrics
via helper functions.  The ``/metrics`` endpoint serves Prometheus
scrape format (``text/plain; version=0.0.4; charset=utf-8``).

Usage::

    from core.metrics import setup_metrics
    app = FastAPI(...)
    setup_metrics(app)

Other modules record business metrics with the helper functions::

    from core.metrics import record_job_dispatched, record_job_completed
    record_job_dispatched("render")
    record_job_completed("render", "completed")
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request

# ---------------------------------------------------------------------------
# Prometheus metric definitions (module-level, default REGISTRY)
# ---------------------------------------------------------------------------

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

http_requests_total = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status_code"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
)

jobs_dispatched_total = Counter(
    "jobs_dispatched_total",
    "Total number of jobs dispatched",
    ["job_type"],
)

jobs_completed_total = Counter(
    "jobs_completed_total",
    "Total number of jobs completed",
    ["job_type", "status"],
)

fleet_nodes_total = Gauge(
    "fleet_nodes_total",
    "Current number of fleet nodes by status",
    ["status"],
)

credits_consumed_total = Counter(
    "credits_consumed_total",
    "Total credits consumed",
)

active_websocket_connections = Gauge(
    "active_websocket_connections",
    "Current number of active WebSocket connections",
)


# ---------------------------------------------------------------------------
# Helper functions for recording business metrics
# ---------------------------------------------------------------------------


def record_job_dispatched(job_type: str) -> None:
    """Increment the jobs dispatched counter for the given job type."""
    jobs_dispatched_total.labels(job_type=job_type).inc()


def record_job_completed(job_type: str, status: str) -> None:
    """Increment the jobs completed counter.

    Args:
        job_type: The type of job (e.g. "render", "inference").
        status: Completion status -- ``"completed"`` or ``"failed"``.
    """
    jobs_completed_total.labels(job_type=job_type, status=status).inc()


def set_fleet_nodes(healthy: int, unhealthy: int, offline: int) -> None:
    """Update the fleet node gauge for each status category."""
    fleet_nodes_total.labels(status="healthy").set(healthy)
    fleet_nodes_total.labels(status="unhealthy").set(unhealthy)
    fleet_nodes_total.labels(status="offline").set(offline)


def record_credits_consumed(amount: float) -> None:
    """Increment the credits consumed counter by *amount*."""
    credits_consumed_total.inc(amount)


def set_active_connections(count: int) -> None:
    """Set the active WebSocket connections gauge to *count*."""
    active_websocket_connections.set(count)


# ---------------------------------------------------------------------------
# Registry-aware helpers (for testing with isolated registries)
# ---------------------------------------------------------------------------


def create_metrics(
    registry: CollectorRegistry | None = None,
) -> dict[str, Counter | Histogram | Gauge]:
    """Create a fresh set of metrics, optionally bound to a custom *registry*.

    This is primarily useful in tests to avoid collector-already-registered
    errors when using the default ``REGISTRY``.

    Returns a dict keyed by metric name.
    """
    reg = registry or REGISTRY
    return {
        "http_requests_total": Counter(
            "http_requests_total",
            "Total number of HTTP requests",
            ["method", "endpoint", "status_code"],
            registry=reg,
        ),
        "http_request_duration_seconds": Histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "endpoint"],
            registry=reg,
        ),
        "jobs_dispatched_total": Counter(
            "jobs_dispatched_total",
            "Total number of jobs dispatched",
            ["job_type"],
            registry=reg,
        ),
        "jobs_completed_total": Counter(
            "jobs_completed_total",
            "Total number of jobs completed",
            ["job_type", "status"],
            registry=reg,
        ),
        "fleet_nodes_total": Gauge(
            "fleet_nodes_total",
            "Current number of fleet nodes by status",
            ["status"],
            registry=reg,
        ),
        "credits_consumed_total": Counter(
            "credits_consumed_total",
            "Total credits consumed",
            registry=reg,
        ),
        "active_websocket_connections": Gauge(
            "active_websocket_connections",
            "Current number of active WebSocket connections",
            registry=reg,
        ),
    }


# ---------------------------------------------------------------------------
# Metrics middleware
# ---------------------------------------------------------------------------


def _normalise_path(path: str) -> str:
    """Collapse path parameters to ``{id}`` to reduce cardinality.

    For example ``/api/v1/jobs/abc-123`` becomes ``/api/v1/jobs/{id}``.
    Only the last segment is replaced if it looks like a UUID or numeric ID.
    """
    parts = path.rstrip("/").split("/")
    normalised: list[str] = []
    for part in parts:
        # Replace UUID-like or numeric segments with {id}
        if part and (part.isdigit() or (len(part) >= 8 and "-" in part)):
            normalised.append("{id}")
        else:
            normalised.append(part)
    return "/".join(normalised) or "/"


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that records HTTP request count and duration.

    Metrics are recorded using the module-level ``http_requests_total``
    counter and ``http_request_duration_seconds`` histogram.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip /metrics itself to avoid self-referential noise
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        path = _normalise_path(request.url.path)

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        status_code = str(response.status_code)

        http_requests_total.labels(method=method, endpoint=path, status_code=status_code).inc()
        http_request_duration_seconds.labels(method=method, endpoint=path).observe(duration)

        return response


# ---------------------------------------------------------------------------
# Setup entrypoint
# ---------------------------------------------------------------------------


def setup_metrics(app: FastAPI) -> None:
    """Wire Prometheus metrics into *app*.

    Adds the ``PrometheusMiddleware`` and registers a ``GET /metrics``
    endpoint that returns the current scrape data.
    """
    app.add_middleware(PrometheusMiddleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> Response:
        """Prometheus scrape endpoint."""
        body = generate_latest(REGISTRY)
        return Response(content=body, media_type=PROMETHEUS_CONTENT_TYPE)
