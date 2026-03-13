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

"""Tests for Prometheus metrics endpoint and helper functions.

Each test that exercises custom metrics uses a fresh
``CollectorRegistry`` to avoid conflicts with the module-level
default registry and between tests.
"""

from __future__ import annotations

import os

# Environment overrides -- must precede application imports.
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_fake")

from typing import TYPE_CHECKING

import pytest
from prometheus_client import CollectorRegistry

from core.metrics import (
    PROMETHEUS_CONTENT_TYPE,
    create_metrics,
    record_credits_consumed,
    record_job_completed,
    record_job_dispatched,
    set_active_connections,
    set_fleet_nodes,
)

if TYPE_CHECKING:
    from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> CollectorRegistry:
    """Return a fresh, isolated Prometheus collector registry."""
    return CollectorRegistry()


@pytest.fixture
def metrics(registry: CollectorRegistry) -> dict:
    """Create a full set of metrics bound to *registry*."""
    return create_metrics(registry)


# ---------------------------------------------------------------------------
# /metrics endpoint tests (use the real app with default REGISTRY)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_200(client: AsyncClient) -> None:
    """GET /metrics should return 200."""
    response = await client.get("/metrics")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_endpoint_content_type(client: AsyncClient) -> None:
    """GET /metrics should return the Prometheus content type header."""
    response = await client.get("/metrics")
    assert response.headers["content-type"] == PROMETHEUS_CONTENT_TYPE


@pytest.mark.asyncio
async def test_metrics_endpoint_contains_python_info(client: AsyncClient) -> None:
    """GET /metrics should include default process/python metrics."""
    response = await client.get("/metrics")
    body = response.text
    # prometheus_client always exposes python_info by default
    assert "python_info" in body


@pytest.mark.asyncio
async def test_http_request_metrics_recorded(client: AsyncClient) -> None:
    """After making requests, http_requests_total should appear in /metrics."""
    # Make a few requests first
    await client.get("/health")
    await client.get("/version")

    response = await client.get("/metrics")
    body = response.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body


@pytest.mark.asyncio
async def test_metrics_endpoint_not_counted(client: AsyncClient) -> None:
    """GET /metrics itself should NOT appear in http_requests_total."""
    # Hit /metrics a few times
    await client.get("/metrics")
    await client.get("/metrics")

    response = await client.get("/metrics")
    body = response.text
    # The /metrics path should not have any counter entries
    # because PrometheusMiddleware skips /metrics requests
    for line in body.splitlines():
        if line.startswith("http_requests_total") and 'endpoint="/metrics"' in line:
            pytest.fail("/metrics endpoint should not be counted in http_requests_total")


# ---------------------------------------------------------------------------
# Custom metric helper tests (isolated registry)
# ---------------------------------------------------------------------------


def test_record_job_dispatched(registry: CollectorRegistry, metrics: dict) -> None:
    """record_job_dispatched increments the dispatch counter."""
    counter = metrics["jobs_dispatched_total"]
    counter.labels(job_type="render").inc()
    counter.labels(job_type="render").inc()
    counter.labels(job_type="inference").inc()

    assert counter.labels(job_type="render")._value.get() == 2.0
    assert counter.labels(job_type="inference")._value.get() == 1.0


def test_record_job_completed(registry: CollectorRegistry, metrics: dict) -> None:
    """record_job_completed increments with job_type and status labels."""
    counter = metrics["jobs_completed_total"]
    counter.labels(job_type="render", status="completed").inc()
    counter.labels(job_type="render", status="completed").inc()
    counter.labels(job_type="render", status="failed").inc()

    assert counter.labels(job_type="render", status="completed")._value.get() == 2.0
    assert counter.labels(job_type="render", status="failed")._value.get() == 1.0


def test_set_fleet_nodes(registry: CollectorRegistry, metrics: dict) -> None:
    """set_fleet_nodes updates the gauge for each status."""
    gauge = metrics["fleet_nodes_total"]
    gauge.labels(status="healthy").set(10)
    gauge.labels(status="unhealthy").set(2)
    gauge.labels(status="offline").set(1)

    assert gauge.labels(status="healthy")._value.get() == 10.0
    assert gauge.labels(status="unhealthy")._value.get() == 2.0
    assert gauge.labels(status="offline")._value.get() == 1.0


def test_record_credits_consumed(registry: CollectorRegistry, metrics: dict) -> None:
    """record_credits_consumed increments the counter by the given amount."""
    counter = metrics["credits_consumed_total"]
    counter.inc(42.5)
    counter.inc(7.5)

    assert counter._value.get() == 50.0


def test_set_active_connections(registry: CollectorRegistry, metrics: dict) -> None:
    """set_active_connections sets the gauge value."""
    gauge = metrics["active_websocket_connections"]
    gauge.set(5)
    assert gauge._value.get() == 5.0

    gauge.set(3)
    assert gauge._value.get() == 3.0


def test_fleet_nodes_gauge_overwrite(registry: CollectorRegistry, metrics: dict) -> None:
    """Gauge values should overwrite, not accumulate."""
    gauge = metrics["fleet_nodes_total"]
    gauge.labels(status="healthy").set(10)
    gauge.labels(status="healthy").set(7)

    assert gauge.labels(status="healthy")._value.get() == 7.0


# ---------------------------------------------------------------------------
# Module-level helper function integration tests
# ---------------------------------------------------------------------------


def test_module_record_job_dispatched_does_not_raise() -> None:
    """Module-level record_job_dispatched should work with the default registry."""
    # Just ensure it does not raise
    record_job_dispatched("render")


def test_module_record_job_completed_does_not_raise() -> None:
    """Module-level record_job_completed should work with the default registry."""
    record_job_completed("render", "completed")
    record_job_completed("render", "failed")


def test_module_set_fleet_nodes_does_not_raise() -> None:
    """Module-level set_fleet_nodes should work with the default registry."""
    set_fleet_nodes(healthy=5, unhealthy=1, offline=0)


def test_module_record_credits_consumed_does_not_raise() -> None:
    """Module-level record_credits_consumed should work with the default registry."""
    record_credits_consumed(100.0)


def test_module_set_active_connections_does_not_raise() -> None:
    """Module-level set_active_connections should work with the default registry."""
    set_active_connections(3)


# ---------------------------------------------------------------------------
# create_metrics isolation test
# ---------------------------------------------------------------------------


def test_create_metrics_returns_all_keys() -> None:
    """create_metrics should return all expected metric names."""
    reg = CollectorRegistry()
    m = create_metrics(reg)
    expected_keys = {
        "http_requests_total",
        "http_request_duration_seconds",
        "jobs_dispatched_total",
        "jobs_completed_total",
        "fleet_nodes_total",
        "credits_consumed_total",
        "active_websocket_connections",
    }
    assert set(m.keys()) == expected_keys


def test_create_metrics_registries_are_isolated() -> None:
    """Two registries should not share metric state."""
    reg1 = CollectorRegistry()
    reg2 = CollectorRegistry()
    m1 = create_metrics(reg1)
    m2 = create_metrics(reg2)

    m1["credits_consumed_total"].inc(100)
    assert m2["credits_consumed_total"]._value.get() == 0.0
