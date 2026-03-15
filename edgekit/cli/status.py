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

"""Edge node status command.

Shows current registration status, key presence, and gateway connectivity.
"""

from __future__ import annotations

import sys

import click
import httpx

from edgekit.cli.register import PRIVATE_KEY_FILE, PUBLIC_KEY_FILE, get_edgekit_dir, load_config


@click.command()
@click.option(
    "--check-connectivity/--no-check-connectivity",
    default=True,
    help="Whether to check gateway connectivity (default: yes).",
)
def status(check_connectivity: bool) -> None:
    """Show registration status and gateway connectivity.

    Reads the local configuration from ~/.edgekit/ and optionally pings
    the gateway health endpoint to verify connectivity.
    """
    edgekit_dir = get_edgekit_dir()
    config = load_config(edgekit_dir)

    if config is None:
        click.echo("Not registered. Run 'edgekit register' first.")
        sys.exit(1)

    private_key_path = edgekit_dir / PRIVATE_KEY_FILE
    public_key_path = edgekit_dir / PUBLIC_KEY_FILE

    click.echo("EdgeKit Node Status")
    click.echo("=" * 40)
    click.echo(f"  Node ID:      {config.get('node_id', 'unknown')}")
    click.echo(f"  Name:         {config.get('name', 'unknown')}")
    click.echo(f"  Gateway:      {config.get('gateway_url', 'unknown')}")
    click.echo(f"  Status:       {config.get('status', 'unknown')}")

    caps = config.get("capabilities", [])
    if caps:
        click.echo(f"  Capabilities: {', '.join(caps)}")

    click.echo("")
    click.echo("Key Files")
    click.echo("-" * 40)

    if private_key_path.exists():
        mode = oct(private_key_path.stat().st_mode & 0o777)
        click.echo(f"  Private key:  {private_key_path} (mode {mode})")
        if private_key_path.stat().st_mode & 0o077:
            click.echo("  WARNING: Private key has insecure permissions!")
    else:
        click.echo("  Private key:  MISSING")

    if public_key_path.exists():
        click.echo(f"  Public key:   {public_key_path}")
    else:
        click.echo("  Public key:   MISSING")

    has_token = bool(config.get("jwt_token"))
    click.echo(f"  JWT token:    {'present' if has_token else 'MISSING'}")

    # Connectivity check
    if check_connectivity:
        gateway_url = config.get("gateway_url", "")
        click.echo("")
        click.echo("Gateway Connectivity")
        click.echo("-" * 40)

        if not gateway_url:
            click.echo("  Gateway URL not configured.")
            sys.exit(1)

        health_url = f"{gateway_url.rstrip('/')}/api/v1/health"
        try:
            response = httpx.get(health_url, timeout=10.0)
            if response.status_code == 200:
                click.echo(f"  Health check:  OK ({health_url})")
            else:
                click.echo(f"  Health check:  DEGRADED (HTTP {response.status_code})")
        except httpx.ConnectError:
            click.echo(f"  Health check:  UNREACHABLE ({health_url})")
            sys.exit(1)
        except httpx.TimeoutException:
            click.echo(f"  Health check:  TIMEOUT ({health_url})")
            sys.exit(1)
