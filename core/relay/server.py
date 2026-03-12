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

"""WebSocket relay server for edge node communication.

Provides an authenticated WebSocket endpoint at ``/relay/ws/{node_id}``
that edge nodes connect to for receiving job assignments, sending status
updates, and maintaining heartbeat connectivity.

Authentication uses a JWT query parameter (``?token=...``) because
WebSocket connections cannot easily carry HTTP Authorization headers.
The token is verified against :func:`core.scheduler.crypto.verify_node_token`
and the ``sub`` claim must match the ``node_id`` path parameter.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.relay.manager import relay_manager
from core.relay.protocol import RelayMessageType
from core.scheduler.crypto import verify_node_token

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/relay", tags=["relay"])

# Heartbeat configuration
_HEARTBEAT_INTERVAL_SECONDS = 30
_HEARTBEAT_TIMEOUT_SECONDS = 90

# WebSocket close codes
_WS_CLOSE_AUTH_FAILED = 4001
_WS_CLOSE_HEARTBEAT_TIMEOUT = 4002


async def _authenticate_websocket(
    websocket: WebSocket, node_id: uuid.UUID
) -> bool:
    """Validate the JWT token from WebSocket query params.

    Args:
        websocket: The incoming WebSocket connection (not yet accepted).
        node_id: The node UUID from the URL path.

    Returns:
        True if authentication succeeded, False if the connection was closed.
    """
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=_WS_CLOSE_AUTH_FAILED)
        logger.warning("ws_auth_missing_token", node_id=str(node_id))
        return False

    try:
        payload = verify_node_token(token)
        if str(node_id) != payload.get("sub"):
            await websocket.close(code=_WS_CLOSE_AUTH_FAILED)
            logger.warning(
                "ws_auth_node_id_mismatch",
                node_id=str(node_id),
                token_sub=payload.get("sub"),
            )
            return False
    except Exception:
        await websocket.close(code=_WS_CLOSE_AUTH_FAILED)
        logger.warning("ws_auth_token_invalid", node_id=str(node_id))
        return False

    return True


async def _heartbeat_loop(
    websocket: WebSocket, node_id: uuid.UUID, last_pong: asyncio.Event
) -> None:
    """Send periodic heartbeat pings and close on timeout.

    Runs as a background task alongside the message receive loop.

    Args:
        websocket: The active WebSocket connection.
        node_id: UUID of the connected node (for logging).
        last_pong: Event that is set each time a pong is received.
    """
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
        try:
            await websocket.send_json(
                {"type": RelayMessageType.HEARTBEAT_PING.value, "payload": {}}
            )
            # Wait for pong within the timeout window
            last_pong.clear()
            try:
                await asyncio.wait_for(
                    last_pong.wait(),
                    timeout=_HEARTBEAT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning("heartbeat_timeout", node_id=str(node_id))
                await websocket.close(code=_WS_CLOSE_HEARTBEAT_TIMEOUT)
                return
        except Exception:
            # Connection already closed
            return


async def _handle_message(
    node_id: uuid.UUID, data: dict
) -> None:
    """Process an incoming WebSocket message from a node.

    Args:
        node_id: UUID of the sending node.
        data: Parsed JSON message dictionary.
    """
    msg_type = data.get("type")
    logger.debug("ws_message_received", node_id=str(node_id), type=msg_type)

    if msg_type == RelayMessageType.JOB_ACK.value:
        logger.info(
            "job_acknowledged",
            node_id=str(node_id),
            job_id=data.get("job_id"),
            accepted=data.get("accepted"),
        )
    elif msg_type == RelayMessageType.STATUS_UPDATE.value:
        logger.info(
            "status_update_received",
            node_id=str(node_id),
            job_id=data.get("job_id"),
            status=data.get("status"),
        )
    else:
        logger.debug("unhandled_message_type", node_id=str(node_id), type=msg_type)


@router.websocket("/ws/{node_id}")
async def relay_websocket(websocket: WebSocket, node_id: uuid.UUID) -> None:
    """WebSocket endpoint for edge node relay communication.

    Authentication flow:
        1. Extract ``token`` from query parameters.
        2. Validate with :func:`verify_node_token`.
        3. Confirm ``node_id`` matches the token's ``sub`` claim.
        4. Accept the WebSocket connection.

    Once connected:
        - A background heartbeat loop sends periodic pings.
        - The main loop receives JSON messages and dispatches by type.
        - On disconnect, the node is removed from the connection manager.

    Args:
        websocket: The incoming WebSocket connection.
        node_id: UUID of the edge node (from URL path).
    """
    # Authenticate before accepting the connection
    if not await _authenticate_websocket(websocket, node_id):
        return

    # Accept and register
    await websocket.accept()
    await relay_manager.connect(node_id, websocket)

    # Heartbeat synchronization
    last_pong = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(websocket, node_id, last_pong)
    )

    try:
        while True:
            data = await websocket.receive_json()

            # Handle heartbeat pong
            if data.get("type") == RelayMessageType.HEARTBEAT_PONG.value:
                last_pong.set()
                continue

            await _handle_message(node_id, data)

    except WebSocketDisconnect:
        logger.info("ws_client_disconnected", node_id=str(node_id))
    except Exception:
        logger.exception("ws_unexpected_error", node_id=str(node_id))
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        await relay_manager.disconnect(node_id)
