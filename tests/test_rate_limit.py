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

"""Unit tests for core.auth.rate_limit.

All Redis interactions are mocked so these tests run without a live
Redis instance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from core.auth.rate_limit import RateLimiter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(path: str = "/auth/login", host: str = "127.0.0.1") -> MagicMock:
    """Build a minimal mock of ``fastapi.Request``."""
    request = MagicMock()
    request.url.path = path
    request.client.host = host
    return request


def _make_redis_mock(
    incr_value: int = 1,
    ttl_value: int = 45,
) -> AsyncMock:
    """Return an ``AsyncMock`` that behaves like ``redis.asyncio.Redis``."""
    redis_instance = AsyncMock()
    redis_instance.incr.return_value = incr_value
    redis_instance.expire.return_value = True
    redis_instance.ttl.return_value = ttl_value
    redis_instance.aclose.return_value = None
    return redis_instance


# ---------------------------------------------------------------------------
# Tests -- requests under the limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allows_request_under_limit() -> None:
    """A request within the limit should pass without raising."""
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    redis_mock = _make_redis_mock(incr_value=1)

    with patch("redis.asyncio.from_url", return_value=redis_mock):
        # Should NOT raise
        await limiter(_make_request())

    redis_mock.incr.assert_awaited_once()
    redis_mock.expire.assert_awaited_once_with(
        "rate_limit:/auth/login:127.0.0.1",
        60,
    )
    redis_mock.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_allows_request_at_exact_limit() -> None:
    """The Nth request (where N == max_requests) should still be allowed."""
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    redis_mock = _make_redis_mock(incr_value=5)

    with patch("redis.asyncio.from_url", return_value=redis_mock):
        await limiter(_make_request())

    # No exception means success.
    redis_mock.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests -- requests exceeding the limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocks_request_over_limit() -> None:
    """The (N+1)th request should raise a 429 HTTPException."""
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    redis_mock = _make_redis_mock(incr_value=6, ttl_value=42)

    with (
        patch("redis.asyncio.from_url", return_value=redis_mock),
        pytest.raises(HTTPException) as exc_info,
    ):
        await limiter(_make_request())

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Too many requests"
    assert exc_info.value.headers is not None
    assert exc_info.value.headers["Retry-After"] == "42"
    redis_mock.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_after_minimum_is_one() -> None:
    """Retry-After should be at least 1 even if TTL returns 0 or -1."""
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    redis_mock = _make_redis_mock(incr_value=4, ttl_value=-1)

    with (
        patch("redis.asyncio.from_url", return_value=redis_mock),
        pytest.raises(HTTPException) as exc_info,
    ):
        await limiter(_make_request())

    assert exc_info.value.headers is not None
    assert exc_info.value.headers["Retry-After"] == "1"


# ---------------------------------------------------------------------------
# Tests -- fail-open behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fails_open_when_redis_unavailable() -> None:
    """If Redis connection fails, the request should be allowed (fail-open)."""
    limiter = RateLimiter(max_requests=5, window_seconds=60)

    with patch(
        "redis.asyncio.from_url",
        side_effect=ConnectionError("Redis is down"),
    ):
        # Should NOT raise -- fail open
        await limiter(_make_request())


@pytest.mark.asyncio
async def test_fails_open_on_redis_command_error() -> None:
    """If a Redis command fails mid-flow, the request should still pass."""
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    redis_mock = AsyncMock()
    redis_mock.incr.side_effect = OSError("connection reset")
    redis_mock.aclose.return_value = None

    with patch("redis.asyncio.from_url", return_value=redis_mock):
        await limiter(_make_request())


# ---------------------------------------------------------------------------
# Tests -- edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_client_when_no_client_info() -> None:
    """When request.client is None the key should use 'unknown'."""
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    redis_mock = _make_redis_mock(incr_value=1)

    request = MagicMock()
    request.url.path = "/auth/login"
    request.client = None

    with patch("redis.asyncio.from_url", return_value=redis_mock):
        await limiter(request)

    redis_mock.incr.assert_awaited_once_with("rate_limit:/auth/login:unknown")


@pytest.mark.asyncio
async def test_different_paths_use_different_keys() -> None:
    """Rate limit keys should be scoped to the request path."""
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    redis_mock = _make_redis_mock(incr_value=1)

    with patch("redis.asyncio.from_url", return_value=redis_mock):
        await limiter(_make_request(path="/auth/login"))

    call_args = redis_mock.incr.call_args[0][0]
    assert "/auth/login" in call_args


@pytest.mark.asyncio
async def test_expire_only_called_on_first_request() -> None:
    """expire() should only be called when the counter is at 1 (new key)."""
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    redis_mock = _make_redis_mock(incr_value=3)

    with patch("redis.asyncio.from_url", return_value=redis_mock):
        await limiter(_make_request())

    redis_mock.expire.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests -- pre-configured limiter instances
# ---------------------------------------------------------------------------


def test_preconfigured_login_limiter() -> None:
    """login_limiter should be configured for 5 req / 60 sec."""
    from core.auth.rate_limit import login_limiter

    assert login_limiter.max_requests == 5
    assert login_limiter.window_seconds == 60


def test_preconfigured_refresh_limiter() -> None:
    """refresh_limiter should be configured for 3 req / 60 sec."""
    from core.auth.rate_limit import refresh_limiter

    assert refresh_limiter.max_requests == 3
    assert refresh_limiter.window_seconds == 60


def test_preconfigured_register_limiter() -> None:
    """register_limiter should be configured for 10 req / 60 sec."""
    from core.auth.rate_limit import register_limiter

    assert register_limiter.max_requests == 10
    assert register_limiter.window_seconds == 60
