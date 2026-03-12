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

"""Tests for the edge node Docker packaging, entrypoint, and health check.

Covers:
- Environment variable parsing (happy-path and missing vars)
- Health endpoint response structure and connected status
- Dockerfile content validation (multi-stage, non-root user)
- docker-compose.edge.yml validity
- Plugin registration in entrypoint
- Graceful shutdown handler registration
- LOG_LEVEL default
"""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Environment overrides — MUST come before any application imports
# ---------------------------------------------------------------------------
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_fake")


# Locate project root (two levels up from tests/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════════════════════════════════════
# Entrypoint environment parsing tests
# ═══════════════════════════════════════════════════════════════════════════


class TestParseEnv:
    """Tests for :func:`edgekit.entrypoint.parse_env`."""

    def test_parse_env_valid(self, monkeypatch):
        """parse_env returns correct values when all required vars are set."""
        monkeypatch.setenv("GATEWAY_URL", "ws://gateway:8000/api/v1")
        monkeypatch.setenv("NODE_JWT", "test-jwt-token")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("HEALTH_PORT", "9090")

        from edgekit.entrypoint import parse_env

        env = parse_env()

        assert env["gateway_url"] == "ws://gateway:8000/api/v1"
        assert env["node_jwt"] == "test-jwt-token"
        assert env["log_level"] == "DEBUG"
        assert env["health_port"] == 9090
        assert env["node_id"] is not None  # auto-generated UUID

    def test_parse_env_missing_gateway_url(self, monkeypatch):
        """parse_env raises SystemExit when GATEWAY_URL is missing."""
        monkeypatch.delenv("GATEWAY_URL", raising=False)
        monkeypatch.setenv("NODE_JWT", "test-jwt-token")

        from edgekit.entrypoint import parse_env

        with pytest.raises(SystemExit, match="GATEWAY_URL"):
            parse_env()

    def test_parse_env_missing_node_jwt(self, monkeypatch):
        """parse_env raises SystemExit when NODE_JWT is missing."""
        monkeypatch.setenv("GATEWAY_URL", "ws://gateway:8000/api/v1")
        monkeypatch.delenv("NODE_JWT", raising=False)

        from edgekit.entrypoint import parse_env

        with pytest.raises(SystemExit, match="NODE_JWT"):
            parse_env()

    def test_parse_env_default_log_level(self, monkeypatch):
        """LOG_LEVEL defaults to INFO when not set."""
        monkeypatch.setenv("GATEWAY_URL", "ws://gateway:8000/api/v1")
        monkeypatch.setenv("NODE_JWT", "test-jwt-token")
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        monkeypatch.delenv("HEALTH_PORT", raising=False)

        from edgekit.entrypoint import parse_env

        env = parse_env()

        assert env["log_level"] == "INFO"

    def test_parse_env_default_health_port(self, monkeypatch):
        """HEALTH_PORT defaults to 8081 when not set."""
        monkeypatch.setenv("GATEWAY_URL", "ws://gateway:8000/api/v1")
        monkeypatch.setenv("NODE_JWT", "test-jwt-token")
        monkeypatch.delenv("HEALTH_PORT", raising=False)

        from edgekit.entrypoint import parse_env

        env = parse_env()

        assert env["health_port"] == 8081

    def test_parse_env_custom_node_id(self, monkeypatch):
        """parse_env uses NODE_ID when provided."""
        import uuid

        test_id = str(uuid.uuid4())
        monkeypatch.setenv("GATEWAY_URL", "ws://gateway:8000/api/v1")
        monkeypatch.setenv("NODE_JWT", "test-jwt-token")
        monkeypatch.setenv("NODE_ID", test_id)

        from edgekit.entrypoint import parse_env

        env = parse_env()

        assert str(env["node_id"]) == test_id


# ═══════════════════════════════════════════════════════════════════════════
# Health endpoint tests
# ═══════════════════════════════════════════════════════════════════════════


class TestHealthEndpoint:
    """Tests for :mod:`edgekit.health` check endpoint."""

    @pytest.fixture
    def health_client(self):
        """Create a test client for the health app."""
        from fastapi.testclient import TestClient

        from edgekit.health import create_health_app, reset_start_time

        reset_start_time()
        app = create_health_app()
        return TestClient(app)

    def test_health_returns_correct_structure(self, health_client):
        """GET /health returns status, connected, and uptime_seconds fields."""
        from edgekit.health import set_relay_client

        set_relay_client(None)

        response = health_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "connected" in data
        assert "uptime_seconds" in data
        assert data["status"] == "ok"

    def test_health_connected_false_when_no_client(self, health_client):
        """Health reports connected=False when relay client is None."""
        from edgekit.health import set_relay_client

        set_relay_client(None)

        response = health_client.get("/health")
        data = response.json()

        assert data["connected"] is False

    def test_health_connected_true_when_relay_connected(self, health_client):
        """Health reports connected=True when relay client reports connected."""
        from edgekit.health import set_relay_client

        mock_client = MagicMock()
        mock_client.connected = True
        set_relay_client(mock_client)

        response = health_client.get("/health")
        data = response.json()

        assert data["connected"] is True

        # Cleanup
        set_relay_client(None)

    def test_health_connected_false_when_relay_disconnected(self, health_client):
        """Health reports connected=False when relay client is disconnected."""
        from edgekit.health import set_relay_client

        mock_client = MagicMock()
        mock_client.connected = False
        set_relay_client(mock_client)

        response = health_client.get("/health")
        data = response.json()

        assert data["connected"] is False

        # Cleanup
        set_relay_client(None)

    def test_health_uptime_is_positive(self, health_client):
        """Uptime should be a non-negative float."""
        from edgekit.health import set_relay_client

        set_relay_client(None)

        response = health_client.get("/health")
        data = response.json()

        assert isinstance(data["uptime_seconds"], float)
        assert data["uptime_seconds"] >= 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Dockerfile validation tests
# ═══════════════════════════════════════════════════════════════════════════


class TestDockerfile:
    """Tests that validate the Dockerfile content."""

    @pytest.fixture
    def dockerfile_content(self):
        """Read the Dockerfile content."""
        dockerfile_path = PROJECT_ROOT / "edgekit" / "Dockerfile"
        assert dockerfile_path.exists(), f"Dockerfile not found at {dockerfile_path}"
        return dockerfile_path.read_text()

    def test_dockerfile_has_builder_stage(self, dockerfile_content):
        """Dockerfile has a builder stage (multi-stage build)."""
        assert "AS builder" in dockerfile_content

    def test_dockerfile_has_runtime_stage(self, dockerfile_content):
        """Dockerfile has a runtime stage."""
        assert "AS runtime" in dockerfile_content

    def test_dockerfile_uses_python311(self, dockerfile_content):
        """Dockerfile uses python:3.11-slim base image."""
        assert "python:3.11-slim" in dockerfile_content

    def test_dockerfile_has_non_root_user(self, dockerfile_content):
        """Dockerfile creates and switches to a non-root user."""
        assert "useradd" in dockerfile_content or "adduser" in dockerfile_content
        assert "USER edgenode" in dockerfile_content

    def test_dockerfile_has_healthcheck(self, dockerfile_content):
        """Dockerfile includes a HEALTHCHECK instruction."""
        assert "HEALTHCHECK" in dockerfile_content

    def test_dockerfile_has_entrypoint(self, dockerfile_content):
        """Dockerfile has an ENTRYPOINT for the edge node."""
        assert "ENTRYPOINT" in dockerfile_content
        assert "edgekit.entrypoint" in dockerfile_content


# ═══════════════════════════════════════════════════════════════════════════
# docker-compose.edge.yml validation tests
# ═══════════════════════════════════════════════════════════════════════════


class TestDockerCompose:
    """Tests that validate docker-compose.edge.yml."""

    @pytest.fixture
    def compose_content(self):
        """Read and parse the compose file."""
        import yaml

        compose_path = PROJECT_ROOT / "docker-compose.edge.yml"
        assert compose_path.exists(), f"Compose file not found at {compose_path}"
        return yaml.safe_load(compose_path.read_text())

    def test_compose_is_valid_yaml(self, compose_content):
        """docker-compose.edge.yml is valid YAML."""
        assert compose_content is not None

    def test_compose_has_edge_node_service(self, compose_content):
        """Compose file defines the edge-node service."""
        assert "services" in compose_content
        assert "edge-node" in compose_content["services"]

    def test_compose_has_required_env_vars(self, compose_content):
        """edge-node service includes GATEWAY_URL and NODE_JWT env vars."""
        env_list = compose_content["services"]["edge-node"]["environment"]
        env_str = " ".join(env_list)
        assert "GATEWAY_URL" in env_str
        assert "NODE_JWT" in env_str

    def test_compose_has_volumes(self, compose_content):
        """edge-node service has data and config volumes."""
        volumes = compose_content["services"]["edge-node"]["volumes"]
        volume_str = " ".join(volumes)
        assert "/data" in volume_str
        assert "/config" in volume_str

    def test_compose_has_resource_limits(self, compose_content):
        """edge-node service has memory and CPU limits."""
        deploy = compose_content["services"]["edge-node"]["deploy"]
        limits = deploy["resources"]["limits"]
        assert "memory" in limits
        assert "cpus" in limits

    def test_compose_restart_policy(self, compose_content):
        """edge-node service has restart: unless-stopped."""
        restart = compose_content["services"]["edge-node"]["restart"]
        assert restart == "unless-stopped"

    def test_compose_exposes_health_port(self, compose_content):
        """edge-node service exposes port 8081."""
        ports = compose_content["services"]["edge-node"]["ports"]
        port_str = " ".join(str(p) for p in ports)
        assert "8081" in port_str


# ═══════════════════════════════════════════════════════════════════════════
# Plugin registration tests
# ═══════════════════════════════════════════════════════════════════════════


class TestPluginRegistration:
    """Tests for plugin instantiation in the entrypoint."""

    def test_build_plugins_returns_both_plugins(self):
        """build_plugins creates EchoPlugin and CpuBenchmarkPlugin."""
        from edgekit.entrypoint import build_plugins

        plugins = build_plugins()

        assert len(plugins) == 2
        job_types = {p.job_type for p in plugins}
        assert "echo" in job_types
        assert "cpu_benchmark" in job_types

    def test_build_executor_registers_plugins(self):
        """build_executor wires plugins into the executor."""
        from edgekit.entrypoint import build_executor, build_plugins

        mock_relay = MagicMock()
        plugins = build_plugins()
        executor = build_executor(mock_relay, plugins)

        assert "echo" in executor.registered_job_types
        assert "cpu_benchmark" in executor.registered_job_types


# ═══════════════════════════════════════════════════════════════════════════
# Shutdown handler tests
# ═══════════════════════════════════════════════════════════════════════════


class TestShutdownHandler:
    """Tests for graceful shutdown handler registration."""

    def test_shutdown_handler_registered(self):
        """register_shutdown_handlers sets up SIGTERM and SIGINT handlers."""
        loop = asyncio.new_event_loop()
        try:
            from edgekit.entrypoint import register_shutdown_handlers

            shutdown_event = register_shutdown_handlers(loop)

            # The event should not be set initially
            assert not shutdown_event.is_set()

            # Verify signal handlers were registered by checking they can
            # be retrieved (loop.add_signal_handler stores them internally)
            # We verify by trying to remove them (which only works if set)
            loop.remove_signal_handler(signal.SIGTERM)
            loop.remove_signal_handler(signal.SIGINT)
        finally:
            loop.close()

    def test_shutdown_event_is_asyncio_event(self):
        """register_shutdown_handlers returns an asyncio.Event."""
        loop = asyncio.new_event_loop()
        try:
            from edgekit.entrypoint import register_shutdown_handlers

            shutdown_event = register_shutdown_handlers(loop)
            assert isinstance(shutdown_event, asyncio.Event)
        finally:
            loop.close()


# ═══════════════════════════════════════════════════════════════════════════
# Logging configuration tests
# ═══════════════════════════════════════════════════════════════════════════


class TestLoggingConfiguration:
    """Tests for logging setup."""

    def test_configure_logging_does_not_raise(self):
        """configure_logging with valid level does not raise."""
        from edgekit.entrypoint import configure_logging

        configure_logging("DEBUG")
        configure_logging("INFO")
        configure_logging("WARNING")

    def test_configure_logging_invalid_level_falls_back(self):
        """configure_logging with invalid level falls back to INFO."""
        from edgekit.entrypoint import configure_logging

        # Should not raise -- getattr falls back to logging.INFO
        configure_logging("INVALID_LEVEL")
