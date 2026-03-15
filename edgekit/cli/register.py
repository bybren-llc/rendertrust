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

"""Edge node registration command.

Generates Ed25519 keypair, registers with the gateway, and stores
credentials locally in ``~/.edgekit/``.

Key files:
- ``~/.edgekit/node_key``       -- Ed25519 private key (PEM, 0o600)
- ``~/.edgekit/node_key.pub``   -- Ed25519 public key (PEM)
- ``~/.edgekit/config.json``    -- Node configuration (node_id, name, gateway_url, jwt_token)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import click
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

# Default config directory
EDGEKIT_DIR = Path.home() / ".edgekit"
PRIVATE_KEY_FILE = "node_key"
PUBLIC_KEY_FILE = "node_key.pub"
CONFIG_FILE = "config.json"

# File permission for private key (owner read/write only)
PRIVATE_KEY_MODE = 0o600


def get_edgekit_dir() -> Path:
    """Return the edgekit config directory, respecting EDGEKIT_HOME override."""
    return Path(os.environ.get("EDGEKIT_HOME", str(EDGEKIT_DIR)))


def generate_keypair() -> tuple[Ed25519PrivateKey, bytes, bytes]:
    """Generate an Ed25519 keypair.

    Returns:
        Tuple of (private_key_object, private_key_pem_bytes, public_key_pem_bytes).
    """
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, private_pem, public_pem


def save_keys(
    edgekit_dir: Path,
    private_pem: bytes,
    public_pem: bytes,
) -> tuple[Path, Path]:
    """Save Ed25519 keypair to disk with secure permissions.

    Args:
        edgekit_dir: Directory to store key files.
        private_pem: PEM-encoded private key bytes.
        public_pem: PEM-encoded public key bytes.

    Returns:
        Tuple of (private_key_path, public_key_path).
    """
    edgekit_dir.mkdir(parents=True, exist_ok=True)

    private_path = edgekit_dir / PRIVATE_KEY_FILE
    private_path.write_bytes(private_pem)
    private_path.chmod(PRIVATE_KEY_MODE)

    public_path = edgekit_dir / PUBLIC_KEY_FILE
    public_path.write_bytes(public_pem)

    return private_path, public_path


def save_config(
    edgekit_dir: Path,
    config: dict[str, Any],
) -> Path:
    """Save node configuration to config.json.

    Args:
        edgekit_dir: Directory to store config file.
        config: Configuration dict with node_id, name, gateway_url, jwt_token.

    Returns:
        Path to the saved config file.
    """
    edgekit_dir.mkdir(parents=True, exist_ok=True)
    config_path = edgekit_dir / CONFIG_FILE
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    return config_path


def load_config(edgekit_dir: Path) -> dict[str, Any] | None:
    """Load node configuration from config.json.

    Returns:
        Config dict, or None if the file does not exist.
    """
    config_path = edgekit_dir / CONFIG_FILE
    if not config_path.exists():
        return None
    return json.loads(config_path.read_text())


def register_with_gateway(
    gateway_url: str,
    name: str,
    public_key_pem: str,
    capabilities: list[str],
) -> dict[str, Any]:
    """POST to the gateway node registration endpoint.

    Args:
        gateway_url: Base URL of the RenderTrust gateway (e.g., http://localhost:8000).
        name: Human-readable node name.
        public_key_pem: PEM-encoded Ed25519 public key.
        capabilities: List of node capabilities.

    Returns:
        Response JSON dict with node_id, challenge, token, status.

    Raises:
        click.ClickException: If the request fails.
    """
    url = f"{gateway_url.rstrip('/')}/api/v1/nodes/register"
    payload = {
        "name": name,
        "public_key": public_key_pem,
        "capabilities": capabilities,
    }

    try:
        response = httpx.post(url, json=payload, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except httpx.ConnectError as exc:
        raise click.ClickException(f"Cannot connect to gateway at {gateway_url}: {exc}") from exc
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:
            detail = exc.response.text
        raise click.ClickException(
            f"Registration failed (HTTP {exc.response.status_code}): {detail}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise click.ClickException(f"Request to gateway timed out: {exc}") from exc


@click.command()
@click.option(
    "--gateway-url",
    required=True,
    envvar="EDGEKIT_GATEWAY_URL",
    help="RenderTrust gateway URL (e.g., http://localhost:8000). Also reads EDGEKIT_GATEWAY_URL.",
)
@click.option(
    "--name",
    required=True,
    envvar="EDGEKIT_NODE_NAME",
    help="Human-readable name for this node. Also reads EDGEKIT_NODE_NAME.",
)
@click.option(
    "--capabilities",
    default="",
    help="Comma-separated list of capabilities (e.g., gpu-render,cpu-inference).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing keys and registration.",
)
def register(
    gateway_url: str,
    name: str,
    capabilities: str,
    force: bool,
) -> None:
    """Generate Ed25519 keys and register this node with the gateway.

    Creates a keypair in ~/.edgekit/, sends the public key to the gateway's
    registration endpoint, and stores the received node JWT for relay auth.
    """
    edgekit_dir = get_edgekit_dir()
    private_key_path = edgekit_dir / PRIVATE_KEY_FILE

    # Check for existing registration
    existing_config = load_config(edgekit_dir)
    if existing_config and private_key_path.exists() and not force:
        click.echo(
            f"Node already registered as '{existing_config.get('name', 'unknown')}' "
            f"(ID: {existing_config.get('node_id', 'unknown')})."
        )
        click.echo("Use --force to re-register with new keys.")
        sys.exit(1)

    # Parse capabilities
    caps: list[str] = [c.strip() for c in capabilities.split(",") if c.strip()]

    # Generate keypair
    click.echo("Generating Ed25519 keypair...")
    _private_key, private_pem, public_pem = generate_keypair()
    public_key_str = public_pem.decode("utf-8")

    # Save keys to disk
    priv_path, pub_path = save_keys(edgekit_dir, private_pem, public_pem)
    click.echo(f"Private key saved: {priv_path} (mode 0600)")
    click.echo(f"Public key saved:  {pub_path}")

    # Register with gateway
    click.echo(f"Registering with gateway at {gateway_url}...")
    result = register_with_gateway(gateway_url, name, public_key_str, caps)

    # Save config
    config = {
        "node_id": result["node_id"],
        "name": name,
        "gateway_url": gateway_url,
        "jwt_token": result["token"],
        "status": result.get("status", "REGISTERED"),
        "capabilities": caps,
    }
    config_path = save_config(edgekit_dir, config)
    click.echo(f"Config saved:      {config_path}")

    click.echo("")
    click.echo(f"Node registered successfully!")
    click.echo(f"  Node ID:      {result['node_id']}")
    click.echo(f"  Name:         {name}")
    click.echo(f"  Status:       {result.get('status', 'REGISTERED')}")
    click.echo(f"  Gateway:      {gateway_url}")
    if caps:
        click.echo(f"  Capabilities: {', '.join(caps)}")
