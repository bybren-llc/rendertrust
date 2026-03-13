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

"""FastAPI dependencies for edge node authentication.

Provides get_current_node dependency that extracts and validates
node identity from the Authorization header.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.database import get_db_session
from core.scheduler.crypto import verify_node_token

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_node_bearer = HTTPBearer()


async def get_current_node(
    credentials: HTTPAuthorizationCredentials = Depends(_node_bearer),
    session: AsyncSession = Depends(get_db_session),
):
    """Extract and validate the current node from the Authorization header.

    Verifies the Bearer token is a valid node JWT, then loads the
    corresponding EdgeNode from the database.

    Raises:
        HTTPException: 401 if authentication fails or node not found.
    """
    # Deferred import -- EdgeNode model may not exist yet (REN-90).
    from core.scheduler.models import EdgeNode, NodeStatus

    payload = verify_node_token(credentials.credentials)

    try:
        node_id = uuid.UUID(payload["sub"])
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid node ID",
        ) from None

    from sqlalchemy import select

    result = await session.execute(
        select(EdgeNode).where(EdgeNode.id == node_id)
    )
    node = result.scalar_one_or_none()

    if node is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Node not found",
        )

    if node.status == NodeStatus.OFFLINE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Node is offline",
        )

    return node
