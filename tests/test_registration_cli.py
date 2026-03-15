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

"""Unit tests for the EdgeKit CLI registration and status commands.

Tests cover:
- Ed25519 key generation and storage
- Secure file permissions on private key (0o600)
- Gateway registration HTTP call (mocked)
- Config file persistence
- Re-registration detection
- --force flag to overwrite existing registration
- Status command output
- Gateway connectivity check
- Error handling for unreachable gateway
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from edgekit.cli import cli
from edgekit.cli.register import (
    CONFIG_FILE,
    PRIVATE_KEY_FILE,
    PRIVATE_KEY_MODE,
    PUBLIC_KEY_FILE,
    generate_keypair,
    get_edgekit_dir,
    load_config,
    save_config,
    save_keys,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def edgekit_home(tmp_path: Path) -> Path:
    """Provide a temporary EDGEKIT_HOME directory for isolation."""
    home = tmp_path / ".edgekit"
    home.mkdir()
    return home


@pytest.fixture(autouse=True)
def _set_edgekit_home(edgekit_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Set EDGEKIT_HOME env var for all tests."""
    monkeypatch.setenv("EDGEKIT_HOME", str(edgekit_home))


@pytest.fixture()
def runner() -> CliRunner:
    """Provide a Click test runner."""
    return CliRunner()


@pytest.fixture()
def mock_gateway_response() -> dict[str, Any]:
    """Standard successful gateway registration response."""
    return {
        "node_id": "550e8400-e29b-41d4-a716-446655440000",
        "challenge": "a" * 64,
        "token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.test.token",
        "status": "REGISTERED",
    }


# ---------------------------------------------------------------------------
# Key generation tests
# ---------------------------------------------------------------------------


class TestKeyGeneration:
    """Tests for Ed25519 keypair generation."""

    def test_generate_keypair_returns_valid_key(self) -> None:
        """generate_keypair returns a valid Ed25519 private key and PEM bytes."""
        private_key, private_pem, public_pem = generate_keypair()

        assert isinstance(private_key, Ed25519PrivateKey)
        assert private_pem.startswith(b"-----BEGIN PRIVATE KEY-----")
        assert public_pem.startswith(b"-----BEGIN PUBLIC KEY-----")

    def test_generate_keypair_unique_keys(self) -> None:
        """Each call generates a distinct keypair."""
        _, priv1, pub1 = generate_keypair()
        _, priv2, pub2 = generate_keypair()

        assert priv1 != priv2
        assert pub1 != pub2

    def test_public_key_derivable_from_private(self) -> None:
        """The public key can be derived from the generated private key."""
        private_key, _priv_pem, _public_pem = generate_keypair()
        derived_pub = private_key.public_key()

        assert isinstance(derived_pub, Ed25519PublicKey)


# ---------------------------------------------------------------------------
# Key storage tests
# ---------------------------------------------------------------------------


class TestKeyStorage:
    """Tests for saving keys to disk with correct permissions."""

    def test_save_keys_creates_files(self, edgekit_home: Path) -> None:
        """save_keys writes both key files to the specified directory."""
        _, private_pem, public_pem = generate_keypair()
        priv_path, pub_path = save_keys(edgekit_home, private_pem, public_pem)

        assert priv_path.exists()
        assert pub_path.exists()
        assert priv_path.read_bytes() == private_pem
        assert pub_path.read_bytes() == public_pem

    def test_private_key_permissions(self, edgekit_home: Path) -> None:
        """Private key file has 0o600 permissions (owner read/write only)."""
        _, private_pem, public_pem = generate_keypair()
        priv_path, _ = save_keys(edgekit_home, private_pem, public_pem)

        actual_mode = stat.S_IMODE(priv_path.stat().st_mode)
        assert actual_mode == PRIVATE_KEY_MODE, (
            f"Expected mode {oct(PRIVATE_KEY_MODE)}, got {oct(actual_mode)}"
        )

    def test_save_keys_creates_directory(self, tmp_path: Path) -> None:
        """save_keys creates the parent directory if it does not exist."""
        new_dir = tmp_path / "nested" / "edgekit"
        _, private_pem, public_pem = generate_keypair()
        priv_path, pub_path = save_keys(new_dir, private_pem, public_pem)

        assert new_dir.exists()
        assert priv_path.exists()
        assert pub_path.exists()


# ---------------------------------------------------------------------------
# Config persistence tests
# ---------------------------------------------------------------------------


class TestConfigPersistence:
    """Tests for config.json read/write."""

    def test_save_and_load_config(self, edgekit_home: Path) -> None:
        """Config round-trips through save/load."""
        config = {
            "node_id": "test-id",
            "name": "test-node",
            "gateway_url": "http://localhost:8000",
            "jwt_token": "test-token",
        }
        save_config(edgekit_home, config)
        loaded = load_config(edgekit_home)

        assert loaded == config

    def test_load_config_missing_file(self, tmp_path: Path) -> None:
        """load_config returns None when config.json does not exist."""
        assert load_config(tmp_path / "nonexistent") is None

    def test_config_file_is_valid_json(self, edgekit_home: Path) -> None:
        """Saved config file is valid JSON with indentation."""
        config = {"node_id": "x", "name": "n"}
        config_path = save_config(edgekit_home, config)
        raw = config_path.read_text()

        # Should be indented JSON
        parsed = json.loads(raw)
        assert parsed == config
        assert "\n" in raw  # Multi-line (indented)


# ---------------------------------------------------------------------------
# EDGEKIT_HOME override tests
# ---------------------------------------------------------------------------


class TestEdgekitHome:
    """Tests for EDGEKIT_HOME environment variable override."""

    def test_get_edgekit_dir_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without EDGEKIT_HOME, defaults to ~/.edgekit."""
        monkeypatch.delenv("EDGEKIT_HOME", raising=False)
        result = get_edgekit_dir()
        assert result == Path.home() / ".edgekit"

    def test_get_edgekit_dir_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """EDGEKIT_HOME overrides the config directory."""
        custom = tmp_path / "custom_edgekit"
        monkeypatch.setenv("EDGEKIT_HOME", str(custom))
        result = get_edgekit_dir()
        assert result == custom


# ---------------------------------------------------------------------------
# Register command tests (CLI integration)
# ---------------------------------------------------------------------------


class TestRegisterCommand:
    """Tests for the ``edgekit register`` CLI command."""

    def test_register_success(
        self,
        runner: CliRunner,
        edgekit_home: Path,
        mock_gateway_response: dict[str, Any],
    ) -> None:
        """Successful registration saves keys, config, and prints confirmation."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = mock_gateway_response
        mock_response.raise_for_status.return_value = None

        with patch("edgekit.cli.register.httpx.post", return_value=mock_response):
            result = runner.invoke(
                cli,
                ["register", "--gateway-url", "http://localhost:8000", "--name", "my-node"],
            )

        assert result.exit_code == 0, result.output
        assert "Node registered successfully" in result.output
        assert mock_gateway_response["node_id"] in result.output

        # Verify files created
        assert (edgekit_home / PRIVATE_KEY_FILE).exists()
        assert (edgekit_home / PUBLIC_KEY_FILE).exists()
        assert (edgekit_home / CONFIG_FILE).exists()

        # Verify config contents
        config = json.loads((edgekit_home / CONFIG_FILE).read_text())
        assert config["node_id"] == mock_gateway_response["node_id"]
        assert config["name"] == "my-node"
        assert config["gateway_url"] == "http://localhost:8000"
        assert config["jwt_token"] == mock_gateway_response["token"]

    def test_register_with_capabilities(
        self,
        runner: CliRunner,
        edgekit_home: Path,
        mock_gateway_response: dict[str, Any],
    ) -> None:
        """Registration with --capabilities passes them to the gateway."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = mock_gateway_response
        mock_response.raise_for_status.return_value = None

        with patch("edgekit.cli.register.httpx.post", return_value=mock_response) as mock_post:
            result = runner.invoke(
                cli,
                [
                    "register",
                    "--gateway-url",
                    "http://localhost:8000",
                    "--name",
                    "gpu-node",
                    "--capabilities",
                    "gpu-render,cpu-inference",
                ],
            )

        assert result.exit_code == 0, result.output

        # Verify capabilities sent in request
        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["capabilities"] == ["gpu-render", "cpu-inference"]

        # Verify capabilities stored in config
        config = json.loads((edgekit_home / CONFIG_FILE).read_text())
        assert config["capabilities"] == ["gpu-render", "cpu-inference"]

    def test_register_detects_existing_registration(
        self,
        runner: CliRunner,
        edgekit_home: Path,
    ) -> None:
        """Re-registration without --force exits with error."""
        # Create existing registration
        _, priv_pem, pub_pem = generate_keypair()
        save_keys(edgekit_home, priv_pem, pub_pem)
        save_config(
            edgekit_home,
            {
                "node_id": "existing-id",
                "name": "existing-node",
                "gateway_url": "http://old:8000",
                "jwt_token": "old-token",
            },
        )

        result = runner.invoke(
            cli,
            ["register", "--gateway-url", "http://localhost:8000", "--name", "new-node"],
        )

        assert result.exit_code != 0
        assert "already registered" in result.output

    def test_register_force_overwrites(
        self,
        runner: CliRunner,
        edgekit_home: Path,
        mock_gateway_response: dict[str, Any],
    ) -> None:
        """--force flag allows re-registration with new keys."""
        # Create existing registration
        _, priv_pem, pub_pem = generate_keypair()
        save_keys(edgekit_home, priv_pem, pub_pem)
        save_config(
            edgekit_home,
            {
                "node_id": "old-id",
                "name": "old-node",
                "gateway_url": "http://old:8000",
                "jwt_token": "old-token",
            },
        )
        old_private = (edgekit_home / PRIVATE_KEY_FILE).read_bytes()

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = mock_gateway_response
        mock_response.raise_for_status.return_value = None

        with patch("edgekit.cli.register.httpx.post", return_value=mock_response):
            result = runner.invoke(
                cli,
                [
                    "register",
                    "--gateway-url",
                    "http://localhost:8000",
                    "--name",
                    "new-node",
                    "--force",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Node registered successfully" in result.output

        # Keys should be different (new keypair)
        new_private = (edgekit_home / PRIVATE_KEY_FILE).read_bytes()
        assert old_private != new_private

        # Config should be updated
        config = json.loads((edgekit_home / CONFIG_FILE).read_text())
        assert config["node_id"] == mock_gateway_response["node_id"]
        assert config["name"] == "new-node"

    def test_register_gateway_unreachable(
        self,
        runner: CliRunner,
        edgekit_home: Path,
    ) -> None:
        """Registration fails gracefully when gateway is unreachable."""
        import httpx as _httpx

        with patch(
            "edgekit.cli.register.httpx.post",
            side_effect=_httpx.ConnectError("Connection refused"),
        ):
            result = runner.invoke(
                cli,
                ["register", "--gateway-url", "http://localhost:9999", "--name", "node"],
            )

        assert result.exit_code != 0
        assert "Cannot connect to gateway" in result.output

    def test_register_gateway_error_response(
        self,
        runner: CliRunner,
        edgekit_home: Path,
    ) -> None:
        """Registration handles HTTP error responses from gateway."""
        import httpx as _httpx

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.json.return_value = {"detail": "Database unavailable"}
        mock_response.raise_for_status.side_effect = _httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=mock_response,
        )

        with patch("edgekit.cli.register.httpx.post", return_value=mock_response):
            result = runner.invoke(
                cli,
                ["register", "--gateway-url", "http://localhost:8000", "--name", "node"],
            )

        assert result.exit_code != 0
        assert "Registration failed" in result.output

    def test_register_private_key_secure_permissions(
        self,
        runner: CliRunner,
        edgekit_home: Path,
        mock_gateway_response: dict[str, Any],
    ) -> None:
        """After registration, private key has 0o600 permissions."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = mock_gateway_response
        mock_response.raise_for_status.return_value = None

        with patch("edgekit.cli.register.httpx.post", return_value=mock_response):
            result = runner.invoke(
                cli,
                ["register", "--gateway-url", "http://localhost:8000", "--name", "sec-node"],
            )

        assert result.exit_code == 0
        priv_path = edgekit_home / PRIVATE_KEY_FILE
        actual_mode = stat.S_IMODE(priv_path.stat().st_mode)
        assert actual_mode == 0o600

    def test_register_missing_required_options(self, runner: CliRunner) -> None:
        """Register command requires --gateway-url and --name."""
        result = runner.invoke(cli, ["register"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()


# ---------------------------------------------------------------------------
# Status command tests
# ---------------------------------------------------------------------------


class TestStatusCommand:
    """Tests for the ``edgekit status`` CLI command."""

    def test_status_not_registered(
        self,
        runner: CliRunner,
        edgekit_home: Path,
    ) -> None:
        """Status shows 'not registered' when no config exists."""
        # Remove any existing config
        config_path = edgekit_home / CONFIG_FILE
        if config_path.exists():
            config_path.unlink()

        result = runner.invoke(cli, ["status", "--no-check-connectivity"])

        assert result.exit_code != 0
        assert "Not registered" in result.output

    def test_status_shows_node_info(
        self,
        runner: CliRunner,
        edgekit_home: Path,
    ) -> None:
        """Status displays node ID, name, gateway, and status from config."""
        _, priv_pem, pub_pem = generate_keypair()
        save_keys(edgekit_home, priv_pem, pub_pem)
        save_config(
            edgekit_home,
            {
                "node_id": "test-node-id-123",
                "name": "my-test-node",
                "gateway_url": "http://gateway:8000",
                "jwt_token": "some-jwt-token",
                "status": "HEALTHY",
                "capabilities": ["gpu-render"],
            },
        )

        result = runner.invoke(cli, ["status", "--no-check-connectivity"])

        assert result.exit_code == 0
        assert "test-node-id-123" in result.output
        assert "my-test-node" in result.output
        assert "http://gateway:8000" in result.output
        assert "HEALTHY" in result.output
        assert "gpu-render" in result.output

    def test_status_shows_key_presence(
        self,
        runner: CliRunner,
        edgekit_home: Path,
    ) -> None:
        """Status reports presence/absence of key files."""
        _, priv_pem, pub_pem = generate_keypair()
        save_keys(edgekit_home, priv_pem, pub_pem)
        save_config(
            edgekit_home,
            {
                "node_id": "id",
                "name": "n",
                "gateway_url": "http://gw:8000",
                "jwt_token": "tok",
            },
        )

        result = runner.invoke(cli, ["status", "--no-check-connectivity"])

        assert result.exit_code == 0
        assert "Private key:" in result.output
        assert "Public key:" in result.output
        assert "JWT token:" in result.output
        assert "present" in result.output  # JWT token is present

    def test_status_missing_keys_shows_missing(
        self,
        runner: CliRunner,
        edgekit_home: Path,
    ) -> None:
        """Status shows MISSING when key files are absent."""
        save_config(
            edgekit_home,
            {
                "node_id": "id",
                "name": "n",
                "gateway_url": "http://gw:8000",
                "jwt_token": "tok",
            },
        )

        result = runner.invoke(cli, ["status", "--no-check-connectivity"])

        assert result.exit_code == 0
        assert "MISSING" in result.output

    def test_status_gateway_connectivity_ok(
        self,
        runner: CliRunner,
        edgekit_home: Path,
    ) -> None:
        """Status reports OK when gateway health endpoint responds 200."""
        save_config(
            edgekit_home,
            {
                "node_id": "id",
                "name": "n",
                "gateway_url": "http://localhost:8000",
                "jwt_token": "tok",
            },
        )
        _, priv_pem, pub_pem = generate_keypair()
        save_keys(edgekit_home, priv_pem, pub_pem)

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("edgekit.cli.status.httpx.get", return_value=mock_response):
            result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "OK" in result.output

    def test_status_gateway_unreachable(
        self,
        runner: CliRunner,
        edgekit_home: Path,
    ) -> None:
        """Status reports UNREACHABLE when gateway cannot be reached."""
        import httpx as _httpx

        save_config(
            edgekit_home,
            {
                "node_id": "id",
                "name": "n",
                "gateway_url": "http://dead-host:8000",
                "jwt_token": "tok",
            },
        )

        with patch(
            "edgekit.cli.status.httpx.get",
            side_effect=_httpx.ConnectError("Connection refused"),
        ):
            result = runner.invoke(cli, ["status"])

        assert result.exit_code != 0
        assert "UNREACHABLE" in result.output


# ---------------------------------------------------------------------------
# CLI entry point tests
# ---------------------------------------------------------------------------


class TestCLIEntryPoint:
    """Tests for the top-level CLI group."""

    def test_cli_help(self, runner: CliRunner) -> None:
        """CLI --help shows available commands."""
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "register" in result.output
        assert "status" in result.output

    def test_cli_version(self, runner: CliRunner) -> None:
        """CLI --version shows version string."""
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert "0.1.0" in result.output
