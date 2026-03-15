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

"""Fleet management endpoints for edge node monitoring.

Provides admin-only fleet listing and per-node health detail.
Mounted at ``/api/v1/fleet`` to avoid prefix collision with
REN-92's node registration router at ``/api/v1/nodes``.
"""

from __future__ import annotations

import datetime
import uuid as _uuid
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from core.auth.jwt import get_current_user
from core.database import get_db_session
from core.scheduler.models import EdgeNode, NodeStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.models.base import User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/fleet", tags=["fleet"])


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class NodeSummary(BaseModel):
    """Summary representation of an edge node for fleet listings."""

    id: str
    name: str
    status: str
    capabilities: list[str]
    current_load: float
    last_heartbeat: str | None


class FleetListResponse(BaseModel):
    """Paginated fleet listing response."""

    nodes: list[NodeSummary]
    total: int
    limit: int
    offset: int


class NodeHealthResponse(BaseModel):
    """Detailed health information for a single edge node."""

    id: str
    name: str
    status: str
    capabilities: list[str]
    current_load: float
    last_heartbeat: str | None
    uptime_seconds: float | None
    metadata: dict | None
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=FleetListResponse)
async def list_nodes(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> FleetListResponse:
    """List all registered edge nodes (admin only).

    Supports filtering by status and pagination via ``limit``/``offset``.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    query = select(EdgeNode)
    count_query = select(func.count(EdgeNode.id))

    if status_filter:
        try:
            node_status = NodeStatus(status_filter)
            query = query.where(EdgeNode.status == node_status)
            count_query = count_query.where(EdgeNode.status == node_status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Invalid status: {status_filter}. "
                    f"Valid values: {[s.value for s in NodeStatus]}"
                ),
            ) from None

    # Total count (respects any status filter)
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Paginated node list
    query = query.order_by(EdgeNode.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(query)
    nodes = list(result.scalars().all())

    logger.info(
        "fleet_listed",
        admin_id=str(current_user.id),
        total=total,
        returned=len(nodes),
        status_filter=status_filter,
    )

    return FleetListResponse(
        nodes=[
            NodeSummary(
                id=str(n.id),
                name=n.name,
                status=n.status.value,
                capabilities=list(n.capabilities or []),
                current_load=n.current_load,
                last_heartbeat=(n.last_heartbeat.isoformat() if n.last_heartbeat else None),
            )
            for n in nodes
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{node_id}/health", response_model=NodeHealthResponse)
async def node_health(
    node_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> NodeHealthResponse:
    """Get health details for a specific edge node.

    Authenticated users may query any node's health. The ``uptime_seconds``
    field reports elapsed time since the node was first registered.
    """
    try:
        parsed_id = _uuid.UUID(node_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid node ID format",
        ) from None

    result = await session.execute(select(EdgeNode).where(EdgeNode.id == parsed_id))
    node = result.scalar_one_or_none()

    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Node not found",
        )

    # Calculate uptime (elapsed time since registration)
    now = datetime.datetime.now(tz=datetime.UTC)
    created = node.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=datetime.UTC)
    uptime = (now - created).total_seconds() if created else None

    logger.info(
        "node_health_queried",
        node_id=str(node.id),
        queried_by=str(current_user.id),
        status=node.status.value,
    )

    return NodeHealthResponse(
        id=str(node.id),
        name=node.name,
        status=node.status.value,
        capabilities=list(node.capabilities or []),
        current_load=node.current_load,
        last_heartbeat=(node.last_heartbeat.isoformat() if node.last_heartbeat else None),
        uptime_seconds=uptime,
        metadata=node.metadata_,
        created_at=node.created_at.isoformat(),
    )
