# Copyright 2025 ByBren, LLC
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

"""Fleet overview endpoint.

Provides fleet status for authenticated users. Requires a valid JWT
Bearer token; unauthenticated requests receive a 401 response.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text

from core.auth.jwt import get_current_user
from core.database import get_db_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.models.base import User

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/fleet")
async def fleet(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get fleet overview. Requires authentication.

    Returns a list of records from the ``fleet_overview`` view/table.
    Access is logged for audit purposes.

    Note:
        Uses raw SQL for ``fleet_overview`` which may be a database view
        or table. Migration to a proper SQLAlchemy model is tracked for
        a future story.
    """
    logger.info("fleet_overview_requested", user_id=str(current_user.id))
    result = await session.execute(text("SELECT * FROM fleet_overview"))
    rows = result.mappings().all()
    return [dict(r) for r in rows]
