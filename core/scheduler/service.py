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

"""Edge node registration and heartbeat service.

Handles node lifecycle: registration with Ed25519 identity verification,
heartbeat processing, and stale node detection.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from core.scheduler.crypto import create_node_token, generate_challenge
from core.scheduler.models import EdgeNode, NodeStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# Node is UNHEALTHY after missing 3 heartbeats (3 * 30s = 90s)
HEARTBEAT_INTERVAL_SECONDS = 30
UNHEALTHY_THRESHOLD_SECONDS = HEARTBEAT_INTERVAL_SECONDS * 3


async def register_node(
    session: AsyncSession,
    name: str,
    public_key: str,
    capabilities: list[str] | None = None,
    metadata: dict | None = None,
) -> tuple[EdgeNode, str, str]:
    """Register a new edge node.

    Idempotent: if a node with the same public_key already exists, returns
    the existing node with a fresh challenge and token (re-registration).

    Args:
        session: Async database session.
        name: Human-readable display name for the node.
        public_key: PEM-encoded Ed25519 public key.
        capabilities: List of supported compute capabilities.
        metadata: Arbitrary JSON metadata about the node.

    Returns:
        Tuple of (node, challenge, node_token).
        The challenge must be signed by the node's private key to complete
        verification.
    """
    caps = capabilities or []

    # Check for duplicate public key (idempotent re-registration)
    result = await session.execute(
        select(EdgeNode).where(EdgeNode.public_key == public_key)
    )
    existing_node = result.scalar_one_or_none()

    if existing_node is not None:
        challenge = generate_challenge()
        token = create_node_token(existing_node.id, caps or list(existing_node.capabilities or []))
        logger.info(
            "node_re_registered",
            node_id=str(existing_node.id),
            name=existing_node.name,
        )
        return existing_node, challenge, token

    node = EdgeNode(
        name=name,
        public_key=public_key,
        capabilities=caps,
        status=NodeStatus.REGISTERED,
        current_load=0.0,
        metadata_=metadata or {},
    )
    session.add(node)
    await session.flush()

    challenge = generate_challenge()
    token = create_node_token(node.id, caps)

    logger.info("node_registered", node_id=str(node.id), name=name)
    return node, challenge, token


async def process_heartbeat(
    session: AsyncSession,
    node: EdgeNode,
    current_load: float = 0.0,
    metadata: dict | None = None,
) -> EdgeNode:
    """Process a heartbeat from an edge node.

    Updates last_heartbeat, current_load, and transitions to HEALTHY if
    the node was previously REGISTERED or UNHEALTHY.

    Args:
        session: Async database session.
        node: The EdgeNode sending the heartbeat.
        current_load: Current load factor (clamped to 0.0-1.0).
        metadata: Optional metadata update.

    Returns:
        The updated EdgeNode.
    """
    now = datetime.datetime.now(tz=datetime.UTC)
    node.last_heartbeat = now
    node.current_load = max(0.0, min(1.0, current_load))  # Clamp 0-1
    if metadata:
        node.metadata_ = metadata

    # Transition to HEALTHY on first heartbeat or recovery
    if node.status in (NodeStatus.REGISTERED, NodeStatus.UNHEALTHY):
        node.status = NodeStatus.HEALTHY
        logger.info("node_healthy", node_id=str(node.id))

    session.add(node)
    await session.flush()

    logger.debug("heartbeat_processed", node_id=str(node.id), load=current_load)
    return node


async def mark_stale_nodes(session: AsyncSession) -> int:
    """Mark nodes that haven't sent a heartbeat as UNHEALTHY.

    Nodes are considered stale if their last_heartbeat is older than
    UNHEALTHY_THRESHOLD_SECONDS (default 90s).

    Args:
        session: Async database session.

    Returns:
        The number of nodes marked unhealthy.
    """
    threshold = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(
        seconds=UNHEALTHY_THRESHOLD_SECONDS
    )

    result = await session.execute(
        select(EdgeNode).where(
            EdgeNode.status == NodeStatus.HEALTHY,
            EdgeNode.last_heartbeat < threshold,
        )
    )
    stale_nodes = list(result.scalars().all())

    for node in stale_nodes:
        node.status = NodeStatus.UNHEALTHY
        session.add(node)
        logger.warning(
            "node_unhealthy",
            node_id=str(node.id),
            last_heartbeat=str(node.last_heartbeat),
        )

    if stale_nodes:
        await session.flush()

    return len(stale_nodes)
