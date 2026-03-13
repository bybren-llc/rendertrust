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

"""Edge node entrypoint -- starts the relay client, worker executor, and health server.

Reads configuration from environment variables, initialises the
:class:`~edgekit.relay.client.RelayClient` and
:class:`~edgekit.workers.executor.WorkerExecutor` with built-in plugins,
starts the health check micro-server, and runs the relay message loop
until terminated.

Environment variables
---------------------
GATEWAY_URL : str (required)
    WebSocket URL of the gateway relay server
    (e.g. ``ws://gateway:8000/api/v1``).
NODE_JWT : str (required)
    JWT authentication token for this edge node.
NODE_ID : str (optional)
    UUID for this node.  A random UUID is generated when omitted.
LOG_LEVEL : str (optional, default ``INFO``)
    Python log level name (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``).
HEALTH_PORT : int (optional, default ``8081``)
    Port for the health check HTTP server.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import uuid
from typing import Any

import structlog


def parse_env() -> dict[str, Any]:
    """Parse and validate required environment variables.

    Returns:
        A dict with keys ``gateway_url``, ``node_jwt``, ``node_id``,
        ``log_level``, and ``health_port``.

    Raises:
        SystemExit: When a required variable is missing.
    """
    gateway_url = os.environ.get("GATEWAY_URL")
    if not gateway_url:
        raise SystemExit("GATEWAY_URL environment variable is required")

    node_jwt = os.environ.get("NODE_JWT")
    if not node_jwt:
        raise SystemExit("NODE_JWT environment variable is required")

    raw_node_id = os.environ.get("NODE_ID")
    if raw_node_id:
        try:
            node_id = uuid.UUID(raw_node_id)
        except ValueError as exc:
            raise SystemExit(f"NODE_ID is not a valid UUID: {raw_node_id}") from exc
    else:
        node_id = uuid.uuid4()

    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    health_port = int(os.environ.get("HEALTH_PORT", "8081"))

    return {
        "gateway_url": gateway_url,
        "node_jwt": node_jwt,
        "node_id": node_id,
        "log_level": log_level,
        "health_port": health_port,
    }


def configure_logging(level: str) -> None:
    """Configure structlog with the given level."""
    numeric_level = getattr(logging, level, logging.INFO)
    logging.basicConfig(format="%(message)s", level=numeric_level)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )


def build_plugins() -> list:
    """Instantiate and return the default set of worker plugins."""
    from edgekit.workers.plugins.cpu import CpuBenchmarkPlugin, EchoPlugin

    return [EchoPlugin(), CpuBenchmarkPlugin()]


def build_executor(relay_client, plugins) -> Any:
    """Create a :class:`WorkerExecutor` wired to the relay client."""
    from edgekit.workers.executor import WorkerExecutor

    return WorkerExecutor(relay_client=relay_client, plugins=plugins)


def build_relay_client(gateway_url: str, node_id: uuid.UUID, node_jwt: str, on_job_assigned):
    """Create a :class:`RelayClient` configured from env."""
    from edgekit.relay.client import RelayClient

    return RelayClient(
        server_url=gateway_url,
        node_id=node_id,
        token=node_jwt,
        on_job_assigned=on_job_assigned,
    )


_shutdown_event: asyncio.Event | None = None


def register_shutdown_handlers(loop: asyncio.AbstractEventLoop) -> asyncio.Event:
    """Register SIGTERM/SIGINT handlers and return a shutdown event.

    The event is set when either signal is received, which unblocks the
    main loop so it can perform a graceful teardown.
    """
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        structlog.get_logger().info("edge_node_shutdown_signal_received")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    global _shutdown_event
    _shutdown_event = shutdown_event
    return shutdown_event


async def run_edge_node() -> None:
    """Main async entry point that orchestrates startup and shutdown."""
    env = parse_env()
    configure_logging(env["log_level"])
    log = structlog.get_logger("edgekit.entrypoint")

    log.info(
        "edge_node_starting",
        gateway_url=env["gateway_url"],
        node_id=str(env["node_id"]),
        log_level=env["log_level"],
        health_port=env["health_port"],
    )

    # Build the component graph: plugins -> relay client -> executor
    plugins = build_plugins()

    # We need a two-phase init because RelayClient needs the executor
    # callback and the executor needs the relay client reference.
    # Approach: create relay client with no callback first, then create
    # executor, then wire the callback.
    from edgekit.relay.client import RelayClient

    relay_client = RelayClient(
        server_url=env["gateway_url"],
        node_id=env["node_id"],
        token=env["node_jwt"],
        on_job_assigned=None,
    )

    executor = build_executor(relay_client, plugins)
    relay_client._on_job_assigned = executor.handle_job

    log.info(
        "edge_node_plugins_registered",
        job_types=executor.registered_job_types,
    )

    # Start health check server
    from edgekit.health import create_health_app, set_relay_client

    set_relay_client(relay_client)
    health_app = create_health_app()

    import uvicorn

    health_config = uvicorn.Config(
        health_app,
        host="0.0.0.0",
        port=env["health_port"],
        log_level=env["log_level"].lower(),
    )
    health_server = uvicorn.Server(health_config)

    # Register signal handlers
    loop = asyncio.get_running_loop()
    shutdown_event = register_shutdown_handlers(loop)

    # Run relay client and health server concurrently
    relay_task = asyncio.create_task(relay_client.run())
    health_task = asyncio.create_task(health_server.serve())

    # Wait for shutdown signal
    await shutdown_event.wait()

    log.info("edge_node_shutting_down")

    # Graceful shutdown
    await relay_client.disconnect()
    health_server.should_exit = True

    # Give tasks a moment to finish
    await asyncio.gather(relay_task, health_task, return_exceptions=True)
    log.info("edge_node_stopped")


def main() -> None:
    """Synchronous entry point for the edge node."""
    asyncio.run(run_edge_node())


if __name__ == "__main__":
    main()
