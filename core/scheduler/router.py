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

"""Edge node scheduler API endpoints.

Provides node registration, heartbeat, and fleet management endpoints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from core.database import get_db_session
from core.scheduler.auth import get_current_node
from core.scheduler.service import process_heartbeat, register_node

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.scheduler.models import EdgeNode

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/nodes", tags=["scheduler"])


# --- Request/Response Schemas ---


class NodeRegisterRequest(BaseModel):
    """Request body for node registration."""

    name: str
    public_key: str
    capabilities: list[str] = []
    metadata: dict | None = None


class NodeRegisterResponse(BaseModel):
    """Response body for successful node registration."""

    node_id: str
    challenge: str
    token: str
    status: str


class HeartbeatRequest(BaseModel):
    """Request body for node heartbeat."""

    current_load: float = 0.0
    metadata: dict | None = None


class HeartbeatResponse(BaseModel):
    """Response body for successful heartbeat."""

    node_id: str
    status: str
    acknowledged: bool = True


# --- Endpoints ---


@router.post(
    "/register",
    response_model=NodeRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: NodeRegisterRequest,
    session: AsyncSession = Depends(get_db_session),
) -> NodeRegisterResponse:
    """Register a new edge node with Ed25519 public key.

    Returns a challenge string that must be signed by the node's private key
    to complete identity verification, along with a node JWT for subsequent
    authenticated requests (heartbeat, job dispatch).
    """
    node, challenge, token = await register_node(
        session=session,
        name=payload.name,
        public_key=payload.public_key,
        capabilities=payload.capabilities,
        metadata=payload.metadata,
    )
    await session.commit()

    return NodeRegisterResponse(
        node_id=str(node.id),
        challenge=challenge,
        token=token,
        status=node.status.value,
    )


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    payload: HeartbeatRequest,
    node: EdgeNode = Depends(get_current_node),
    session: AsyncSession = Depends(get_db_session),
) -> HeartbeatResponse:
    """Process heartbeat from authenticated edge node.

    Requires a valid node JWT in the Authorization header.
    Updates last_heartbeat timestamp, current_load, and transitions
    REGISTERED/UNHEALTHY nodes to HEALTHY.
    """
    updated_node = await process_heartbeat(
        session=session,
        node=node,
        current_load=payload.current_load,
        metadata=payload.metadata,
    )
    await session.commit()

    return HeartbeatResponse(
        node_id=str(updated_node.id),
        status=updated_node.status.value,
    )
