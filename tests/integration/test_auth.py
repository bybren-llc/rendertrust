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

"""Integration tests for JWT authentication lifecycle.

Covers:
- Token creation (access and refresh)
- Token verification (valid, expired, malformed, missing sub, wrong secret)
- Endpoint authentication via get_current_user dependency
  (missing header, invalid token, expired token, refresh-as-access,
   nonexistent user, inactive user, valid access)
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from fastapi import APIRouter, Depends, HTTPException
from jose import jwt as jose_jwt

from core.auth.jwt import (
    TokenType,
    create_access_token,
    create_refresh_token,
    get_current_user,
    verify_token,
)
from core.config import get_settings

if TYPE_CHECKING:
    from httpx import AsyncClient

    from core.models.base import User

# ---------------------------------------------------------------------------
# Test-only authenticated endpoint
# ---------------------------------------------------------------------------
# The fleet router is not mounted in create_app(), so we create a minimal
# endpoint to exercise the get_current_user dependency end-to-end.
_test_router = APIRouter()


@_test_router.get("/test-auth")
async def _test_auth_endpoint(
    current_user: User = Depends(get_current_user),
):
    return {"user_id": str(current_user.id), "email": current_user.email}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
async def auth_client(client: AsyncClient) -> AsyncClient:
    """Return the test client with the test-only auth endpoint mounted."""
    app = client._transport.app
    app.include_router(_test_router)
    return client


# ═══════════════════════════════════════════════════════════════════════════
# Token creation
# ═══════════════════════════════════════════════════════════════════════════
class TestTokenCreation:
    """Test JWT token creation functions."""

    def test_create_access_token_returns_string(self):
        token = create_access_token({"sub": "test-user-id"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_access_token_contains_correct_claims(self):
        token = create_access_token({"sub": "user-123"})
        settings = get_settings()
        payload = jose_jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        assert payload["sub"] == "user-123"
        assert payload["token_type"] == TokenType.ACCESS.value
        assert "exp" in payload
        assert "iat" in payload

    def test_refresh_token_has_refresh_type(self):
        token = create_refresh_token({"sub": "user-123"})
        settings = get_settings()
        payload = jose_jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        assert payload["token_type"] == TokenType.REFRESH.value

    def test_access_token_expires_within_expected_window(self):
        token = create_access_token({"sub": "user-123"})
        settings = get_settings()
        payload = jose_jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        iat = payload["iat"]
        exp = payload["exp"]
        # Should expire within configured minutes (default 30)
        assert exp - iat == settings.jwt_access_token_expire_minutes * 60


# ═══════════════════════════════════════════════════════════════════════════
# Token verification
# ═══════════════════════════════════════════════════════════════════════════
class TestTokenVerification:
    """Test JWT token verification."""

    def test_verify_valid_access_token(self):
        token = create_access_token({"sub": "user-123"})
        payload = verify_token(token)
        assert payload.sub == "user-123"
        assert payload.token_type == TokenType.ACCESS

    def test_verify_valid_refresh_token(self):
        token = create_refresh_token({"sub": "user-123"})
        payload = verify_token(token)
        assert payload.sub == "user-123"
        assert payload.token_type == TokenType.REFRESH

    def test_verify_expired_token_raises_401(self):
        settings = get_settings()
        expired_payload = {
            "sub": "user-123",
            "exp": datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(hours=1),
            "iat": datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(hours=2),
            "token_type": TokenType.ACCESS.value,
        }
        token = jose_jwt.encode(
            expired_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
        )
        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)
        assert exc_info.value.status_code == 401

    def test_verify_malformed_token_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            verify_token("not-a-valid-jwt")
        assert exc_info.value.status_code == 401

    def test_verify_token_missing_sub_raises_401(self):
        settings = get_settings()
        payload = {
            "exp": datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(hours=1),
            "iat": datetime.datetime.now(tz=datetime.UTC),
            "token_type": TokenType.ACCESS.value,
        }
        token = jose_jwt.encode(
            payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
        )
        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)
        assert exc_info.value.status_code == 401

    def test_verify_token_wrong_secret_raises_401(self):
        payload = {
            "sub": "user-123",
            "exp": datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(hours=1),
            "iat": datetime.datetime.now(tz=datetime.UTC),
            "token_type": TokenType.ACCESS.value,
        }
        token = jose_jwt.encode(payload, "wrong-secret-key", algorithm="HS256")
        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)
        assert exc_info.value.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# Endpoint authentication (get_current_user dependency)
# ═══════════════════════════════════════════════════════════════════════════
class TestAuthenticatedEndpoints:
    """Test endpoint authentication via get_current_user dependency."""

    async def test_missing_auth_header_returns_403(self, auth_client: AsyncClient):
        """HTTPBearer returns 403 when no Authorization header is present."""
        response = await auth_client.get("/test-auth")
        assert response.status_code == 403

    async def test_invalid_token_returns_401(self, auth_client: AsyncClient):
        response = await auth_client.get(
            "/test-auth", headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401

    async def test_expired_token_returns_401(self, auth_client: AsyncClient):
        settings = get_settings()
        expired_payload = {
            "sub": "user-123",
            "exp": datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(hours=1),
            "iat": datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(hours=2),
            "token_type": TokenType.ACCESS.value,
        }
        token = jose_jwt.encode(
            expired_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
        )
        response = await auth_client.get(
            "/test-auth", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401

    async def test_refresh_token_rejected_as_access(
        self, auth_client: AsyncClient, test_user: User
    ):
        """OWASP A01 fix: refresh tokens cannot be used as access tokens."""
        token = create_refresh_token({"sub": str(test_user.id)})
        response = await auth_client.get(
            "/test-auth", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401

    async def test_nonexistent_user_returns_401(self, auth_client: AsyncClient):
        """Token for non-existent user returns 401."""
        token = create_access_token({"sub": "00000000-0000-0000-0000-000000000000"})
        response = await auth_client.get(
            "/test-auth", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401

    async def test_inactive_user_returns_401(
        self, auth_client: AsyncClient, db_session, test_user: User
    ):
        """Inactive user with valid token returns 401."""
        test_user.is_active = False
        db_session.add(test_user)
        await db_session.flush()
        token = create_access_token({"sub": str(test_user.id)})
        response = await auth_client.get(
            "/test-auth", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401

    async def test_valid_token_active_user_returns_200(
        self, auth_client: AsyncClient, test_user: User, auth_headers: dict
    ):
        """Valid access token for active user succeeds."""
        response = await auth_client.get("/test-auth", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == str(test_user.id)
        assert data["email"] == "test@rendertrust.com"

    async def test_admin_user_returns_200(
        self, auth_client: AsyncClient, admin_user: User, admin_auth_headers: dict
    ):
        """Admin user can also access authenticated endpoints."""
        response = await auth_client.get("/test-auth", headers=admin_auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == str(admin_user.id)
