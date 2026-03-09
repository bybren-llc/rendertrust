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

"""Redis-backed token blacklist for JWT revocation.

Uses Redis SET with TTL matching token remaining lifetime.
Fail-open: if Redis is unavailable, tokens are NOT blacklisted
(same pattern as rate_limit.py).

Usage::

    from core.auth.blacklist import token_blacklist

    # Revoke a token
    await token_blacklist.revoke(jti="abc-123", expires_at=token_exp)

    # Check if revoked
    if await token_blacklist.is_revoked(jti="abc-123"):
        raise HTTPException(401)
"""

from __future__ import annotations

import datetime

import structlog

from core.config import get_settings

logger = structlog.get_logger(__name__)

# Redis key prefix for blacklisted tokens
_KEY_PREFIX = "blacklist:"


class TokenBlacklist:
    """Redis-backed token blacklist for JWT revocation.

    Uses Redis SET with TTL matching token remaining lifetime.
    Fail-open: if Redis is unavailable, tokens are NOT blacklisted
    (same pattern as rate_limit.py).
    """

    async def revoke(self, jti: str, expires_at: datetime.datetime) -> bool:
        """Add token JTI to blacklist with TTL until token expiry.

        Args:
            jti: The JWT ID (unique token identifier).
            expires_at: The token's expiration timestamp.

        Returns:
            True if the token was successfully blacklisted, False if
            the token is already expired or Redis is unavailable.
        """
        import redis.asyncio as aioredis

        now = datetime.datetime.now(tz=datetime.UTC)

        # Ensure expires_at is timezone-aware for comparison
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=datetime.UTC)

        ttl_seconds = int((expires_at - now).total_seconds())

        if ttl_seconds <= 0:
            logger.debug("blacklist_skip_expired", jti=jti)
            return False

        settings = get_settings()
        key = f"{_KEY_PREFIX}{jti}"

        try:
            r = aioredis.from_url(settings.redis_url)
            try:
                await r.setex(key, ttl_seconds, "1")
                logger.info("token_blacklisted", jti=jti, ttl_seconds=ttl_seconds)
                return True
            finally:
                await r.aclose()
        except Exception:
            # Fail open -- Redis unavailable should not block logout.
            logger.warning("blacklist_redis_unavailable", jti=jti, operation="revoke")
            return False

    async def is_revoked(self, jti: str) -> bool:
        """Check if a token JTI is blacklisted.

        Args:
            jti: The JWT ID to check.

        Returns:
            True if the token is blacklisted, False if it is not or
            if Redis is unavailable (fail-open).
        """
        import redis.asyncio as aioredis

        settings = get_settings()
        key = f"{_KEY_PREFIX}{jti}"

        try:
            r = aioredis.from_url(settings.redis_url)
            try:
                exists: bool = bool(await r.exists(key))
                return exists
            finally:
                await r.aclose()
        except Exception:
            # Fail open -- Redis unavailable means token is NOT considered revoked.
            logger.warning("blacklist_redis_unavailable", jti=jti, operation="is_revoked")
            return False


# Module-level singleton
token_blacklist = TokenBlacklist()
