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

"""WebSocket connection manager for edge relay.

Manages active WebSocket connections to edge nodes, supporting
unicast (send to a specific node) and broadcast operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import uuid

    from fastapi import WebSocket

logger = structlog.get_logger(__name__)


class ConnectionManager:
    """Tracks active WebSocket connections keyed by node UUID.

    Thread-safety note: This manager is designed for single-process use
    with asyncio. For multi-process deployments, connections should be
    coordinated via Redis pub/sub (future enhancement).
    """

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, WebSocket] = {}

    async def connect(self, node_id: uuid.UUID, websocket: WebSocket) -> None:
        """Register an active WebSocket connection for a node.

        If the node already has a connection, the old one is replaced
        (the caller is responsible for closing the previous socket).

        Args:
            node_id: UUID of the connecting edge node.
            websocket: The accepted WebSocket connection.
        """
        self._connections[node_id] = websocket
        logger.info("node_connected", node_id=str(node_id), total=len(self._connections))

    async def disconnect(self, node_id: uuid.UUID) -> None:
        """Remove a node's WebSocket connection from the manager.

        Args:
            node_id: UUID of the disconnecting edge node.
        """
        self._connections.pop(node_id, None)
        logger.info("node_disconnected", node_id=str(node_id), total=len(self._connections))

    async def send_to_node(self, node_id: uuid.UUID, message: dict[str, object]) -> bool:
        """Send a JSON message to a specific connected node.

        Args:
            node_id: UUID of the target edge node.
            message: Dictionary payload to send as JSON.

        Returns:
            True if the message was sent, False if the node is not connected.
        """
        websocket = self._connections.get(node_id)
        if websocket is None:
            logger.warning("send_to_unconnected_node", node_id=str(node_id))
            return False
        await websocket.send_json(message)
        return True

    async def broadcast(self, message: dict[str, object]) -> None:
        """Send a JSON message to all connected nodes.

        Disconnected or errored sockets are silently skipped (cleanup
        happens in the per-connection message loop).

        Args:
            message: Dictionary payload to broadcast as JSON.
        """
        for node_id, websocket in list(self._connections.items()):
            try:
                await websocket.send_json(message)
            except Exception:
                logger.warning("broadcast_send_failed", node_id=str(node_id))

    def is_connected(self, node_id: uuid.UUID) -> bool:
        """Check whether a node has an active WebSocket connection.

        Args:
            node_id: UUID of the edge node to check.

        Returns:
            True if the node has an active connection.
        """
        return node_id in self._connections

    def connected_count(self) -> int:
        """Return the number of currently connected nodes.

        Returns:
            Integer count of active connections.
        """
        return len(self._connections)


# Module-level singleton used by the relay server and other services.
relay_manager = ConnectionManager()
