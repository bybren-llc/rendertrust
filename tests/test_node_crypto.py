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

"""Unit tests for Ed25519 node identity crypto utilities.

Tests cover challenge generation, signature verification, and node JWT
token creation/verification. No database or Redis required -- all
external dependencies are mocked.
"""

from __future__ import annotations

import datetime
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from fastapi import HTTPException
from jose import jwt

from core.scheduler.crypto import (
    create_node_token,
    generate_challenge,
    verify_node_token,
    verify_signature,
)

# Constant for assertions to avoid S105 false positives
_NODE_TOKEN_TYPE = "node"  # noqa: S105


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_blacklist():
    """Mock the token blacklist so verify_token doesn't hit Redis."""
    with patch("core.auth.jwt.token_blacklist") as mock_bl:
        mock_bl.is_revoked = AsyncMock(return_value=False)
        yield mock_bl


@pytest.fixture
def ed25519_keypair():
    """Generate an Ed25519 keypair for testing."""
    private_key = Ed25519PrivateKey.generate()
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_key, public_key_pem


@pytest.fixture
def second_ed25519_keypair():
    """Generate a second Ed25519 keypair (different from the first)."""
    private_key = Ed25519PrivateKey.generate()
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_key, public_key_pem


# ---------------------------------------------------------------------------
# Challenge generation tests
# ---------------------------------------------------------------------------


def test_generate_challenge_returns_hex_string():
    """Challenge should be a 64-character hex string (32 bytes)."""
    challenge = generate_challenge()
    assert isinstance(challenge, str)
    assert len(challenge) == 64
    # Verify it's valid hex by converting to int
    int(challenge, 16)


def test_generate_challenge_unique():
    """Two consecutive challenges must be different."""
    c1 = generate_challenge()
    c2 = generate_challenge()
    assert c1 != c2


# ---------------------------------------------------------------------------
# Signature verification tests
# ---------------------------------------------------------------------------


def test_verify_signature_valid(ed25519_keypair):
    """Valid Ed25519 signature should return True."""
    private_key, public_key_pem = ed25519_keypair
    challenge = generate_challenge()
    signature = private_key.sign(challenge.encode())

    result = verify_signature(public_key_pem, challenge, signature)
    assert result is True


def test_verify_signature_invalid(ed25519_keypair):
    """Tampered signature bytes should return False."""
    _private_key, public_key_pem = ed25519_keypair
    challenge = generate_challenge()
    # Create garbage signature (64 bytes for Ed25519 signature size)
    bad_signature = b"\x00" * 64

    result = verify_signature(public_key_pem, challenge, bad_signature)
    assert result is False


def test_verify_signature_wrong_key(ed25519_keypair, second_ed25519_keypair):
    """Signature from a different key should return False."""
    private_key_a, _public_key_pem_a = ed25519_keypair
    _private_key_b, public_key_pem_b = second_ed25519_keypair
    challenge = generate_challenge()
    # Sign with key A, verify with key B
    signature = private_key_a.sign(challenge.encode())

    result = verify_signature(public_key_pem_b, challenge, signature)
    assert result is False


def test_verify_signature_non_ed25519_key():
    """RSA key passed as public_key_pem should return False."""
    rsa_private = generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    rsa_public_pem = (
        rsa_private.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    challenge = generate_challenge()
    fake_sig = b"\x00" * 64

    result = verify_signature(rsa_public_pem, challenge, fake_sig)
    assert result is False


# ---------------------------------------------------------------------------
# Node JWT token tests
# ---------------------------------------------------------------------------


def test_create_node_token_returns_string():
    """create_node_token should return a non-empty JWT string."""
    node_id = uuid.uuid4()
    token = create_node_token(node_id)
    assert isinstance(token, str)
    assert len(token) > 0
    # Should have 3 parts separated by dots (JWT format)
    assert token.count(".") == 2


def test_create_node_token_contains_claims():
    """Node token should contain sub, token_type, capabilities, jti claims."""
    node_id = uuid.uuid4()
    capabilities = ["gpu-render", "cpu-inference"]
    token = create_node_token(node_id, capabilities=capabilities)

    # Decode without verification to inspect claims
    from core.config import get_settings

    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])

    assert payload["sub"] == str(node_id)
    assert payload["token_type"] == _NODE_TOKEN_TYPE
    assert payload["capabilities"] == ["gpu-render", "cpu-inference"]
    assert "jti" in payload
    assert "exp" in payload
    assert "iat" in payload


def test_create_node_token_default_capabilities():
    """Node token with no capabilities should default to empty list."""
    node_id = uuid.uuid4()
    token = create_node_token(node_id)

    from core.config import get_settings

    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])

    assert payload["capabilities"] == []


# ---------------------------------------------------------------------------
# Node JWT verification tests
# ---------------------------------------------------------------------------


def test_verify_node_token_valid():
    """Create then verify a node token -- round trip should succeed."""
    node_id = uuid.uuid4()
    token = create_node_token(node_id, capabilities=["gpu-render"])
    payload = verify_node_token(token)

    assert payload["sub"] == str(node_id)
    assert payload["token_type"] == _NODE_TOKEN_TYPE
    assert payload["capabilities"] == ["gpu-render"]


def test_verify_node_token_wrong_type():
    """A user access token should be rejected by verify_node_token."""
    from core.auth.jwt import create_access_token

    # Create a standard user access token (token_type == "access")
    token = create_access_token({"sub": str(uuid.uuid4())})

    with pytest.raises(HTTPException) as exc_info:
        verify_node_token(token)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid node credentials"


def test_verify_node_token_expired():
    """An expired node token should raise HTTPException 401."""
    from core.config import get_settings

    settings = get_settings()
    now = datetime.datetime.now(tz=datetime.UTC)
    # Create a token that expired 1 hour ago
    payload = {
        "sub": str(uuid.uuid4()),
        "exp": now - datetime.timedelta(hours=1),
        "iat": now - datetime.timedelta(hours=25),
        "token_type": "node",
        "capabilities": [],
        "jti": str(uuid.uuid4()),
    }
    expired_token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    with pytest.raises(HTTPException) as exc_info:
        verify_node_token(expired_token)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid node credentials"
