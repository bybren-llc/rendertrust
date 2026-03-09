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

"""Authentication API endpoints.

Provides user registration, login, token refresh, and logout.
Rate-limited via Redis-backed sliding window (REN-70).
Audit-logged via structlog -- passwords and tokens are NEVER logged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from passlib.hash import bcrypt
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.jwt import (
    TokenType,
    create_access_token,
    create_refresh_token,
    verify_token,
)
from core.auth.rate_limit import login_limiter, refresh_limiter, register_limiter
from core.database import get_db_session
from core.models.base import User

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    """Registration payload."""

    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    """Login credentials payload."""

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Token refresh payload."""

    refresh_token: str


class TokenResponse(BaseModel):
    """JWT token pair returned on successful authentication."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105


class UserResponse(BaseModel):
    """Public user representation (no sensitive fields)."""

    id: str
    email: str
    name: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class RegisterResponse(BaseModel):
    """Registration response containing user info and tokens."""

    user: UserResponse
    tokens: TokenResponse


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/auth")


def _issue_tokens(user_id: str) -> TokenResponse:
    """Create an access + refresh token pair for the given user ID.

    Args:
        user_id: The user's UUID as a string.

    Returns:
        TokenResponse with both tokens and token_type.
    """
    return TokenResponse(
        access_token=create_access_token({"sub": user_id}),
        refresh_token=create_refresh_token({"sub": user_id}),
    )


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(register_limiter)],
)
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RegisterResponse:
    """Create a new user account and return JWT tokens.

    Raises:
        HTTPException 409: If the email is already registered.
    """
    # Check for existing email
    result = await session.execute(
        select(User).where(User.email == payload.email),
    )
    if result.scalar_one_or_none() is not None:
        logger.info("registration_email_conflict", email_domain=payload.email.split("@")[1])
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Create user
    hashed = bcrypt.hash(payload.password)
    user = User(
        email=payload.email,
        name=payload.name,
        hashed_password=hashed,
        is_active=True,
        is_admin=False,
    )
    session.add(user)
    await session.flush()

    logger.info("user_registered", user_id=str(user.id))

    tokens = _issue_tokens(str(user.id))
    return RegisterResponse(
        user=UserResponse(
            id=str(user.id),
            email=user.email,
            name=user.name,
            is_active=user.is_active,
        ),
        tokens=tokens,
    )


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(login_limiter)],
)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """Authenticate with email and password, returning JWT tokens.

    Raises:
        HTTPException 401: Invalid credentials or inactive account.
    """
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Look up user by email
    result = await session.execute(
        select(User).where(User.email == payload.email),
    )
    user = result.scalar_one_or_none()

    if user is None:
        logger.info("login_failed", reason="user_not_found")
        raise invalid_credentials

    # Verify password
    if not bcrypt.verify(payload.password, user.hashed_password):
        logger.info("login_failed", reason="invalid_password", user_id=str(user.id))
        raise invalid_credentials

    # Check active status
    if not user.is_active:
        logger.warning("login_failed", reason="inactive_account", user_id=str(user.id))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.info("login_success", user_id=str(user.id))
    return _issue_tokens(str(user.id))


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(refresh_limiter)],
)
async def refresh(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """Exchange a valid refresh token for a new access + refresh token pair.

    Raises:
        HTTPException 401: Invalid, expired, or wrong-type token.
    """
    token_data = verify_token(payload.refresh_token)

    # Ensure this is actually a refresh token, not an access token
    if token_data.token_type != TokenType.REFRESH:
        logger.warning("refresh_wrong_token_type", token_type=token_data.token_type)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type: expected refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify user still exists and is active
    result = await session.execute(
        select(User).where(User.id == token_data.sub),
    )
    user = result.scalar_one_or_none()

    if user is None:
        logger.warning("refresh_user_not_found", user_id=token_data.sub)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        logger.warning("refresh_inactive_user", user_id=token_data.sub)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.info("token_refreshed", user_id=str(user.id))
    return _issue_tokens(str(user.id))


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------


@router.post(
    "/logout",
    response_model=MessageResponse,
)
async def logout() -> MessageResponse:
    """Log out the current user.

    .. note::
        This is a placeholder. Actual token revocation (server-side
        blocklist) will be implemented in REN-72.

    Returns:
        Confirmation message.
    """
    # TODO(REN-72): Implement token revocation via Redis blocklist.
    # Accept the Authorization header, decode the token, and add its
    # ``jti`` to a Redis set with TTL matching the token's remaining
    # lifetime. ``verify_token`` should then check the blocklist.
    logger.info("logout_placeholder_called")
    return MessageResponse(message="Logged out successfully")
