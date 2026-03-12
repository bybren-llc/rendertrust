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

"""Async WebSocket client for the edge relay.

Connects to the gateway relay server, handles heartbeat pings automatically,
dispatches incoming job assignments to a callback, and provides methods for
sending job acknowledgements and status updates.

Reconnects automatically with exponential backoff when the connection drops.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING, Any

import structlog
import websockets

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from websockets.asyncio.client import ClientConnection

logger = structlog.get_logger(__name__)

# Default backoff parameters
_DEFAULT_INITIAL_BACKOFF_SECONDS = 1.0
_DEFAULT_MAX_BACKOFF_SECONDS = 30.0
_DEFAULT_BACKOFF_MULTIPLIER = 2.0


class RelayClient:
    """Async WebSocket client for edge relay communication.

    Connects to the relay server at ``{server_url}/relay/ws/{node_id}?token=...``,
    automatically responds to heartbeat pings, and dispatches job assignments
    to the ``on_job_assigned`` callback.

    Args:
        server_url: Base WebSocket URL of the relay server (e.g. ``ws://localhost:8000/api/v1``).
        node_id: UUID of this edge node.
        token: JWT authentication token for this node.
        on_job_assigned: Async callback invoked when a job assignment is received.
            Signature: ``async (job_data: dict) -> None``.
        initial_backoff: Initial reconnect delay in seconds (default 1.0).
        max_backoff: Maximum reconnect delay in seconds (default 30.0).
        backoff_multiplier: Multiplier applied to backoff on each retry (default 2.0).

    Example::

        async def handle_job(job_data: dict) -> None:
            print(f"Got job: {job_data['job_id']}")

        client = RelayClient(
            server_url="ws://gateway:8000/api/v1",
            node_id=my_node_id,
            token=my_token,
            on_job_assigned=handle_job,
        )
        await client.run()  # runs until cancelled
    """

    def __init__(
        self,
        server_url: str,
        node_id: uuid.UUID,
        token: str,
        on_job_assigned: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
        initial_backoff: float = _DEFAULT_INITIAL_BACKOFF_SECONDS,
        max_backoff: float = _DEFAULT_MAX_BACKOFF_SECONDS,
        backoff_multiplier: float = _DEFAULT_BACKOFF_MULTIPLIER,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._node_id = node_id
        self._token = token
        self._on_job_assigned = on_job_assigned
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff
        self._backoff_multiplier = backoff_multiplier

        self._ws: ClientConnection | None = None
        self._running = False
        self._connected = False

    @property
    def connected(self) -> bool:
        """Whether the client currently has an active WebSocket connection."""
        return self._connected

    @property
    def ws_url(self) -> str:
        """Full WebSocket URL including node_id and token query parameter."""
        return f"{self._server_url}/relay/ws/{self._node_id}?token={self._token}"

    async def connect(self) -> None:
        """Establish the WebSocket connection to the relay server.

        Raises:
            Exception: If the connection cannot be established.
        """
        logger.info(
            "relay_client_connecting",
            node_id=str(self._node_id),
            url=self._server_url,
        )
        self._ws = await websockets.connect(self.ws_url)
        self._connected = True
        logger.info("relay_client_connected", node_id=str(self._node_id))

    async def disconnect(self) -> None:
        """Close the WebSocket connection gracefully."""
        self._running = False
        self._connected = False
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
            logger.info("relay_client_disconnected", node_id=str(self._node_id))

    async def send_job_ack(self, job_id: uuid.UUID, accepted: bool = True) -> None:
        """Send a job acknowledgement message to the relay server.

        Args:
            job_id: The UUID of the job being acknowledged.
            accepted: Whether the node accepts the job (default True).

        Raises:
            RuntimeError: If not currently connected.
        """
        if self._ws is None:
            raise RuntimeError("Not connected to relay server")
        message = {
            "type": "job_ack",
            "job_id": str(job_id),
            "accepted": accepted,
        }
        await self._ws.send(json.dumps(message))
        logger.debug(
            "relay_client_sent_job_ack",
            node_id=str(self._node_id),
            job_id=str(job_id),
            accepted=accepted,
        )

    async def send_status_update(
        self,
        job_id: uuid.UUID,
        status: str,
        progress: float | None = None,
        detail: str | None = None,
    ) -> None:
        """Send a job status update to the relay server.

        Args:
            job_id: The UUID of the job.
            status: Current status (e.g. ``running``, ``completed``, ``failed``).
            progress: Optional progress as a float between 0.0 and 1.0.
            detail: Optional human-readable detail string.

        Raises:
            RuntimeError: If not currently connected.
        """
        if self._ws is None:
            raise RuntimeError("Not connected to relay server")
        message: dict[str, Any] = {
            "type": "status_update",
            "job_id": str(job_id),
            "status": status,
        }
        if progress is not None:
            message["progress"] = progress
        if detail is not None:
            message["detail"] = detail
        await self._ws.send(json.dumps(message))
        logger.debug(
            "relay_client_sent_status_update",
            node_id=str(self._node_id),
            job_id=str(job_id),
            status=status,
        )

    async def _handle_message(self, raw: str) -> None:
        """Parse and dispatch an incoming WebSocket message.

        Handles:
        - ``heartbeat_ping`` -- responds with ``heartbeat_pong`` automatically.
        - ``job_assign`` -- sends ``job_ack`` and invokes the ``on_job_assigned`` callback.

        Args:
            raw: Raw JSON string received from the WebSocket.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("relay_client_invalid_json", raw=raw[:200])
            return

        msg_type = data.get("type")
        logger.debug("relay_client_message_received", type=msg_type)

        if msg_type == "heartbeat_ping":
            # Respond to heartbeat ping with pong
            if self._ws is not None:
                await self._ws.send(json.dumps({"type": "heartbeat_pong", "payload": {}}))
                logger.debug("relay_client_sent_heartbeat_pong")

        elif msg_type == "job_assign":
            # Auto-acknowledge the job assignment
            job_id_str = data.get("job_id")
            if job_id_str:
                try:
                    job_id = uuid.UUID(job_id_str)
                    await self.send_job_ack(job_id)
                except ValueError:
                    logger.warning("relay_client_invalid_job_id", job_id=job_id_str)

            # Invoke the callback
            if self._on_job_assigned is not None:
                try:
                    await self._on_job_assigned(data)
                except Exception:
                    logger.exception(
                        "relay_client_job_callback_error",
                        job_id=data.get("job_id"),
                    )
        else:
            logger.debug("relay_client_unhandled_message", type=msg_type)

    async def _receive_loop(self) -> None:
        """Read messages from the WebSocket until disconnected.

        Raises:
            websockets.ConnectionClosed: When the connection is closed.
        """
        if self._ws is None:
            return
        async for message in self._ws:
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            await self._handle_message(message)

    async def run(self) -> None:
        """Connect and run the message loop with automatic reconnection.

        This method runs indefinitely until :meth:`disconnect` is called or
        the task is cancelled. On connection failure or unexpected disconnect,
        it will reconnect with exponential backoff.
        """
        self._running = True
        backoff = self._initial_backoff

        while self._running:
            try:
                await self.connect()
                backoff = self._initial_backoff  # Reset on successful connect
                await self._receive_loop()
            except asyncio.CancelledError:
                logger.info("relay_client_cancelled", node_id=str(self._node_id))
                break
            except Exception:
                logger.warning(
                    "relay_client_connection_lost",
                    node_id=str(self._node_id),
                    reconnect_in=backoff,
                )
            finally:
                self._connected = False
                self._ws = None

            if not self._running:
                break

            # Exponential backoff before reconnect
            logger.info(
                "relay_client_reconnecting",
                node_id=str(self._node_id),
                backoff=backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * self._backoff_multiplier, self._max_backoff)

        logger.info("relay_client_stopped", node_id=str(self._node_id))
