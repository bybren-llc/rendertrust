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

"""Tests for token blacklist (JWT revocation via Redis).

All Redis calls are mocked -- no live Redis server required.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from core.auth.blacklist import TokenBlacklist, token_blacklist
from core.auth.jwt import create_access_token, verify_token

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _future_expiry(minutes: int = 30) -> datetime.datetime:
    """Return a timezone-aware datetime ``minutes`` in the future."""
    return datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(minutes=minutes)


def _past_expiry(minutes: int = 5) -> datetime.datetime:
    """Return a timezone-aware datetime ``minutes`` in the past."""
    return datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# Unit tests -- TokenBlacklist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_token_adds_to_blacklist():
    """Revoking a token should call Redis SETEX and return True."""
    mock_redis = AsyncMock()
    mock_redis.setex = AsyncMock()
    mock_redis.aclose = AsyncMock()

    with patch("core.auth.blacklist.aioredis.from_url", return_value=mock_redis):
        bl = TokenBlacklist()
        result = await bl.revoke("test-jti-123", _future_expiry(30))

    assert result is True
    mock_redis.setex.assert_awaited_once()
    # Verify the key format
    call_args = mock_redis.setex.call_args
    assert call_args[0][0] == "blacklist:test-jti-123"
    assert call_args[0][2] == "1"
    # TTL should be roughly 30 minutes (1800 seconds), allow tolerance
    ttl = call_args[0][1]
    assert 1700 < ttl <= 1800


@pytest.mark.asyncio
async def test_is_revoked_returns_false_for_unknown():
    """Non-revoked JTI should return False."""
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=0)
    mock_redis.aclose = AsyncMock()

    with patch("core.auth.blacklist.aioredis.from_url", return_value=mock_redis):
        bl = TokenBlacklist()
        result = await bl.is_revoked("unknown-jti-456")

    assert result is False
    mock_redis.exists.assert_awaited_once_with("blacklist:unknown-jti-456")


@pytest.mark.asyncio
async def test_revoke_expired_token_skips():
    """Token already expired should skip Redis and return False."""
    bl = TokenBlacklist()
    # No Redis mock needed -- should not reach Redis
    result = await bl.revoke("expired-jti", _past_expiry(5))

    assert result is False


@pytest.mark.asyncio
async def test_blacklist_fail_open_revoke():
    """Redis unavailable during revoke should return False (fail-open)."""
    with patch(
        "core.auth.blacklist.aioredis.from_url",
        side_effect=ConnectionError("Redis down"),
    ):
        bl = TokenBlacklist()
        result = await bl.revoke("fail-jti", _future_expiry(30))

    assert result is False


@pytest.mark.asyncio
async def test_blacklist_fail_open_check():
    """Redis unavailable during is_revoked should return False (fail-open)."""
    with patch(
        "core.auth.blacklist.aioredis.from_url",
        side_effect=ConnectionError("Redis down"),
    ):
        bl = TokenBlacklist()
        result = await bl.is_revoked("fail-jti")

    assert result is False


# ---------------------------------------------------------------------------
# Integration-style tests (still mocked Redis)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_token_rejects_revoked():
    """A blacklisted token should cause verify_token to raise HTTPException."""
    token = create_access_token({"sub": "user-123"})

    # Mock is_revoked to return True for any JTI
    with (
        patch.object(token_blacklist, "is_revoked", new_callable=AsyncMock, return_value=True),
        pytest.raises(HTTPException) as exc_info,
    ):
        await verify_token(token)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_token(client, test_user):
    """POST /api/v1/auth/logout should revoke the Bearer token."""
    token = create_access_token({"sub": str(test_user.id)})
    headers = {"Authorization": f"Bearer {token}"}

    with (
        patch.object(
            token_blacklist,
            "is_revoked",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch.object(
            token_blacklist,
            "revoke",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_revoke,
    ):
        response = await client.post("/api/v1/auth/logout", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Logged out successfully"
    mock_revoke.assert_awaited_once()
