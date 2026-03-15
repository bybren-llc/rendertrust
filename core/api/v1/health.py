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

"""Health check endpoints.

Provides liveness (/health) and readiness (/health/ready) probes.
The readiness probe verifies database and Redis connectivity.
"""

from typing import Any

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.database import get_db_session

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness probe. Returns healthy if the process is running."""
    settings = get_settings()
    return {
        "status": "healthy",
        "version": "0.1.0",
        "environment": settings.app_env,
    }


@router.get("/health/ready")
async def readiness_check(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Readiness probe. Checks database and Redis connectivity.

    Returns 200 with component status if all services are reachable.
    Returns 200 with degraded status if any service is unreachable
    (allows the application to start even if dependencies are slow).
    """
    checks: dict[str, str] = {}

    # Check database
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception:
        logger.warning("readiness_check_db_failed")
        checks["database"] = "unavailable"

    # Check Redis
    try:
        settings = get_settings()
        r = aioredis.from_url(settings.redis_url)
        await r.ping()  # type: ignore[misc]
        await r.aclose()
        checks["redis"] = "connected"
    except Exception:
        logger.warning("readiness_check_redis_failed")
        checks["redis"] = "unavailable"

    all_healthy = all(v == "connected" for v in checks.values())
    return {
        "status": "ready" if all_healthy else "degraded",
        "checks": checks,
    }
