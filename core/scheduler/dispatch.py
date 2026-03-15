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

"""Job dispatch service with least-loaded scheduling and Redis queue.

Implements the scheduler algorithm:
1. Query HEALTHY nodes with matching job_type capability
2. Sort by current_load ascending (least-loaded first)
3. Select the first (least-loaded) node
4. Create JobDispatch record with status=DISPATCHED
5. Push job to Redis queue ``queue:node:{node_id}``

Redis uses a fail-open pattern: if Redis is unavailable, the DB record
is still created but a warning is logged (same pattern as token blacklist).
"""

from __future__ import annotations

import datetime
import json
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from core.auth.jwt import get_current_user
from core.config import get_settings
from core.database import get_db_session
from core.scheduler.models import EdgeNode, JobDispatch, JobStatus, NodeStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.models.base import User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["dispatch"])


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------


class DispatchRequest(BaseModel):
    """Request body for job dispatch."""

    job_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Job type (e.g. 'render', 'inference')",
    )
    payload_ref: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Reference to the job payload (S3 URI, etc.)",
    )


class DispatchResponse(BaseModel):
    """Response body for successful job dispatch."""

    job_id: str
    node_id: str
    status: str


# ---------------------------------------------------------------------------
# Scheduler Algorithm
# ---------------------------------------------------------------------------


async def find_best_node(
    session: AsyncSession,
    job_type: str,
) -> EdgeNode | None:
    """Find the least-loaded healthy node with the required capability.

    Queries HEALTHY nodes whose ``capabilities`` JSON list contains
    ``job_type``, ordered by ``current_load`` ascending (least-loaded first).

    Args:
        session: Async database session.
        job_type: The required capability (e.g. 'render').

    Returns:
        The least-loaded matching EdgeNode, or None if no match found.
    """
    result = await session.execute(
        select(EdgeNode)
        .where(EdgeNode.status == NodeStatus.HEALTHY)
        .order_by(EdgeNode.current_load.asc())
    )
    nodes = list(result.scalars().all())

    # Filter in Python for JSON contains (SQLite doesn't support JSON_CONTAINS)
    for node in nodes:
        caps = node.capabilities or []
        if isinstance(caps, list) and job_type in caps:
            return node

    return None


# ---------------------------------------------------------------------------
# Redis Queue
# ---------------------------------------------------------------------------


async def push_to_queue(node_id: str, job_id: str, job_type: str, payload_ref: str) -> bool:
    """Push a job to the node's Redis queue.

    Uses RPUSH to add the job to ``queue:node:{node_id}``.
    Fail-open: returns False if Redis is unavailable (logs warning).

    Args:
        node_id: The target node UUID as string.
        job_id: The job UUID as string.
        job_type: The job type.
        payload_ref: The payload reference.

    Returns:
        True if successfully pushed, False if Redis was unavailable.
    """
    settings = get_settings()
    key = f"queue:node:{node_id}"
    payload = json.dumps(
        {
            "job_id": job_id,
            "job_type": job_type,
            "payload_ref": payload_ref,
        }
    )

    try:
        r = aioredis.from_url(settings.redis_url)
        try:
            await r.rpush(key, payload)
            logger.info(
                "job_queued_redis",
                node_id=node_id,
                job_id=job_id,
                queue_key=key,
            )
            return True
        finally:
            await r.aclose()
    except Exception:
        # Fail open -- Redis unavailable should not block dispatch.
        logger.warning(
            "dispatch_redis_unavailable",
            node_id=node_id,
            job_id=job_id,
            operation="push_to_queue",
        )
        return False


# ---------------------------------------------------------------------------
# Dispatch Service
# ---------------------------------------------------------------------------


async def dispatch_job(
    session: AsyncSession,
    job_type: str,
    payload_ref: str,
) -> JobDispatch:
    """Dispatch a job to the best available node.

    1. Find least-loaded healthy node with matching capability
    2. Create JobDispatch record with status=DISPATCHED
    3. Push job to Redis queue (fail-open)

    Args:
        session: Async database session.
        job_type: The required job type/capability.
        payload_ref: Reference to the job payload.

    Returns:
        The created JobDispatch record.

    Raises:
        HTTPException: 503 if no healthy node is available for the job type.
    """
    node = await find_best_node(session, job_type)

    if node is None:
        logger.warning("no_healthy_nodes", job_type=job_type)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No healthy nodes available for job type: {job_type}",
        )

    now = datetime.datetime.now(tz=datetime.UTC)
    job = JobDispatch(
        node_id=node.id,
        job_type=job_type,
        payload_ref=payload_ref,
        status=JobStatus.DISPATCHED,
        queued_at=now,
        dispatched_at=now,
    )
    session.add(job)
    await session.flush()

    logger.info(
        "job_dispatched",
        job_id=str(job.id),
        node_id=str(node.id),
        job_type=job_type,
    )

    # Push to Redis queue (fail-open)
    await push_to_queue(
        node_id=str(node.id),
        job_id=str(job.id),
        job_type=job_type,
        payload_ref=payload_ref,
    )

    return job


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/dispatch",
    response_model=DispatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def dispatch(
    payload: DispatchRequest,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    session: AsyncSession = Depends(get_db_session),
) -> DispatchResponse:
    """Dispatch a job to the least-loaded healthy edge node.

    Requires a valid user JWT in the Authorization header.
    The scheduler selects the least-loaded HEALTHY node that has
    the required ``job_type`` in its capabilities list.

    Returns 201 with the job dispatch confirmation, or 503 if no
    suitable node is available.
    """
    job = await dispatch_job(
        session=session,
        job_type=payload.job_type,
        payload_ref=payload.payload_ref,
    )
    await session.commit()

    return DispatchResponse(
        job_id=str(job.id),
        node_id=str(job.node_id),
        status=job.status.value,
    )
