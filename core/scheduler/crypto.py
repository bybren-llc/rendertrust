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

"""Ed25519 cryptographic utilities for edge node identity.

Provides key generation (for testing), signature verification,
challenge-response protocol, and node JWT token management.
Node private keys NEVER touch the gateway -- only public keys are stored.
"""

from __future__ import annotations

import datetime
import secrets
import uuid
from typing import Any

import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import HTTPException, status
from jose import JWTError, jwt

from core.config import get_settings

logger = structlog.get_logger(__name__)

# Challenge is 32 random bytes, hex-encoded (64 chars)
_CHALLENGE_BYTES = 32


def generate_challenge() -> str:
    """Generate a random challenge string for node registration.

    Returns:
        Hex-encoded random bytes (64 characters).
    """
    return secrets.token_hex(_CHALLENGE_BYTES)


def verify_signature(public_key_pem: str, challenge: str, signature: bytes) -> bool:
    """Verify an Ed25519 signature against a challenge.

    Args:
        public_key_pem: PEM-encoded Ed25519 public key.
        challenge: The challenge string that was signed.
        signature: The raw signature bytes.

    Returns:
        True if signature is valid, False otherwise.
    """
    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode())
        if not isinstance(public_key, Ed25519PublicKey):
            logger.warning("invalid_key_type", key_type=type(public_key).__name__)
            return False
        public_key.verify(signature, challenge.encode())
        return True
    except InvalidSignature:
        logger.warning("invalid_signature")
        return False
    except Exception:
        logger.warning("signature_verification_error")
        return False


def create_node_token(node_id: uuid.UUID, capabilities: list[str] | None = None) -> str:
    """Create a JWT for an authenticated edge node.

    Args:
        node_id: The UUID of the registered node.
        capabilities: List of node capabilities (e.g., ["gpu-render", "cpu-inference"]).

    Returns:
        Encoded JWT string with node_id and capabilities claims.
    """
    settings = get_settings()
    now = datetime.datetime.now(tz=datetime.UTC)
    # Node tokens are long-lived (24h) -- nodes re-register on expiry
    expires = now + datetime.timedelta(hours=24)
    payload: dict[str, Any] = {
        "sub": str(node_id),
        "exp": expires,
        "iat": now,
        "token_type": "node",
        "capabilities": capabilities or [],
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_node_token(token: str) -> dict[str, Any]:
    """Verify and decode a node JWT.

    Args:
        token: The encoded JWT string.

    Returns:
        Decoded payload dict with sub, token_type, capabilities.

    Raises:
        HTTPException: 401 if token is invalid, expired, or not a node token.
    """
    settings = get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid node credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        if payload.get("token_type") != "node":
            logger.warning("non_node_token_used", token_type=payload.get("token_type"))
            raise credentials_exception
        if not payload.get("sub"):
            raise credentials_exception
        return payload
    except JWTError as err:
        logger.warning("node_jwt_verification_failed")
        raise credentials_exception from err
