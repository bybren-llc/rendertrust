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

"""Redis-backed rate limiting for authentication endpoints.

Uses a sliding window counter pattern with Redis TTL keys.
Falls back to allowing requests if Redis is unavailable (fail-open
for availability, with warning logs).

Implements the rate-limiting pattern from patterns_library/security/rate-limiting.md,
adapted for FastAPI with redis.asyncio.

Usage as a FastAPI dependency::

    from core.auth.rate_limit import login_limiter

    @router.post("/auth/login", dependencies=[Depends(login_limiter)])
    async def login(credentials: LoginRequest):
        ...
"""

from __future__ import annotations

import os

import structlog
from fastapi import HTTPException, Request, status

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIS_URL: str = os.environ.get("REDIS_URL", "redis://redis:6379/0")


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------


class RateLimiter:
    """Configurable rate limiter using a Redis sliding window counter.

    Each instance defines a ``max_requests`` / ``window_seconds`` pair.
    It is designed to be used as a FastAPI *dependency* (via ``Depends``).

    The client IP address is used as the rate-limit key.  When the limit
    is exceeded the dependency raises ``HTTPException(429)`` with a
    ``Retry-After`` header.

    If Redis is unreachable the limiter **fails open** -- the request is
    allowed through and a warning is logged.  This keeps the service
    available even when Redis is temporarily down.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def __call__(self, request: Request) -> None:
        """Check the rate limit for the current request.

        Raises:
            HTTPException: 429 Too Many Requests when the limit is exceeded.
        """
        # Late import so the module can be loaded even without redis installed
        # in lightweight environments (e.g. pure lint / type-check passes).
        import redis.asyncio as aioredis

        client_ip: str = request.client.host if request.client else "unknown"
        key = f"rate_limit:{request.url.path}:{client_ip}"

        try:
            r = aioredis.from_url(REDIS_URL)
            try:
                current: int = await r.incr(key)
                if current == 1:
                    await r.expire(key, self.window_seconds)

                if current > self.max_requests:
                    ttl: int = await r.ttl(key)
                    logger.warning(
                        "rate_limit_exceeded",
                        path=request.url.path,
                        client_ip=client_ip,
                        current=current,
                        limit=self.max_requests,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Too many requests",
                        headers={"Retry-After": str(max(ttl, 1))},
                    )
            finally:
                await r.aclose()
        except HTTPException:
            raise
        except Exception:
            # Fail open -- Redis unavailable should not block requests.
            logger.warning(
                "rate_limiter_redis_unavailable",
                path=request.url.path,
                client_ip=client_ip,
            )


# ---------------------------------------------------------------------------
# Pre-configured limiters for authentication endpoints
# ---------------------------------------------------------------------------

login_limiter = RateLimiter(max_requests=5, window_seconds=60)
"""5 requests per 60 seconds -- protects login from brute-force."""

refresh_limiter = RateLimiter(max_requests=3, window_seconds=60)
"""3 requests per 60 seconds -- limits token refresh abuse."""

register_limiter = RateLimiter(max_requests=10, window_seconds=60)
"""10 requests per 60 seconds -- permits burst signups, blocks spam."""
