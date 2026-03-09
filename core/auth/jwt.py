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

"""JWT token creation and verification.

Handles access and refresh token lifecycle with proper error handling.
Tokens are never logged or exposed in error messages.
"""

import datetime
from enum import StrEnum
from typing import Any

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.database import get_db_session
from core.models.base import User

logger = structlog.get_logger(__name__)

# Security scheme for OpenAPI docs
_bearer_scheme = HTTPBearer()


class TokenType(StrEnum):
    """JWT token type discriminator."""

    ACCESS = "access"
    REFRESH = "refresh"


class TokenPayload(BaseModel):
    """Validated JWT token payload.

    Attributes:
        sub: Subject (user ID as string).
        exp: Expiration timestamp.
        iat: Issued-at timestamp.
        token_type: Discriminator for access vs. refresh tokens.
    """

    sub: str
    exp: datetime.datetime
    iat: datetime.datetime
    token_type: TokenType


def create_access_token(data: dict[str, Any]) -> str:
    """Create a short-lived JWT access token.

    Args:
        data: Claims to embed in the token. Must include 'sub' (subject/user ID).

    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    now = datetime.datetime.now(tz=datetime.UTC)
    expires = now + datetime.timedelta(minutes=settings.jwt_access_token_expire_minutes)
    to_encode = {
        **data,
        "exp": expires,
        "iat": now,
        "token_type": TokenType.ACCESS.value,
    }
    encoded: str = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return encoded


def create_refresh_token(data: dict[str, Any]) -> str:
    """Create a long-lived JWT refresh token.

    Args:
        data: Claims to embed in the token. Must include 'sub' (subject/user ID).

    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    now = datetime.datetime.now(tz=datetime.UTC)
    expires = now + datetime.timedelta(days=settings.jwt_refresh_token_expire_days)
    to_encode = {
        **data,
        "exp": expires,
        "iat": now,
        "token_type": TokenType.REFRESH.value,
    }
    encoded: str = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return encoded


def verify_token(token: str) -> TokenPayload:
    """Verify and decode a JWT token.

    Args:
        token: The encoded JWT string.

    Returns:
        Validated TokenPayload.

    Raises:
        HTTPException: If the token is invalid, expired, or malformed.
    """
    settings = get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        sub: str | None = payload.get("sub")
        if sub is None:
            logger.warning("jwt_verification_failed", reason="missing_sub")
            raise credentials_exception
        return TokenPayload(
            sub=sub,
            exp=payload["exp"],
            iat=payload["iat"],
            token_type=payload.get("token_type", TokenType.ACCESS.value),
        )
    except JWTError as err:
        logger.warning("jwt_verification_failed", reason="decode_error")
        raise credentials_exception from err


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """FastAPI dependency that extracts and validates the current user.

    Verifies the Bearer token, then loads the corresponding User from
    the database. Returns 401 if the token is invalid or the user
    does not exist / is inactive.

    Args:
        credentials: Bearer token from the Authorization header.
        session: Async database session (injected).

    Returns:
        The authenticated User model instance.

    Raises:
        HTTPException: 401 if authentication fails.
    """
    token_data = verify_token(credentials.credentials)

    result = await session.execute(
        select(User).where(User.id == token_data.sub),
    )
    user = result.scalar_one_or_none()

    if user is None:
        logger.warning("user_not_found", user_id=token_data.sub)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        logger.warning("inactive_user_access_attempt", user_id=token_data.sub)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
