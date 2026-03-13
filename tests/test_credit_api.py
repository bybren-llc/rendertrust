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

"""Tests for the credit API endpoints (balance, history, deduct)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from core.auth.jwt import create_access_token
from core.ledger.service import allocate_credits, deduct_credits
from core.models.base import TransactionSource

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.models.base import User


# ---------------------------------------------------------------------------
# Mock the Redis-backed token blacklist for all tests in this module.
# verify_token() is async and checks the blacklist, so we must mock it.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_blacklist():
    with patch("core.auth.jwt.token_blacklist") as mock_bl:
        mock_bl.is_revoked = AsyncMock(return_value=False)
        yield mock_bl


# ---------------------------------------------------------------------------
# Helper: auth headers
# ---------------------------------------------------------------------------


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token({"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET /api/v1/credits/balance
# ---------------------------------------------------------------------------


async def test_get_balance_empty(
    client: AsyncClient,
    test_user: User,
) -> None:
    """New user with no ledger entries has a zero balance."""
    resp = await client.get(
        "/api/v1/credits/balance",
        headers=_auth_headers(test_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["balance"] == "0.0000"
    assert data["user_id"] == str(test_user.id)


async def test_get_balance_after_allocation(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Balance reflects credits allocated via the service layer."""
    await allocate_credits(
        session=db_session,
        user_id=test_user.id,
        amount=Decimal("250.5000"),
        source=TransactionSource.STRIPE,
        reference_id="test-alloc-balance-250",
    )
    await db_session.flush()

    resp = await client.get(
        "/api/v1/credits/balance",
        headers=_auth_headers(test_user),
    )
    assert resp.status_code == 200
    assert resp.json()["balance"] == "250.5000"


# ---------------------------------------------------------------------------
# GET /api/v1/credits/history
# ---------------------------------------------------------------------------


async def test_get_history_empty(
    client: AsyncClient,
    test_user: User,
) -> None:
    """Returns empty list for user with no ledger entries."""
    resp = await client.get(
        "/api/v1/credits/history",
        headers=_auth_headers(test_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["entries"] == []
    assert data["count"] == 0


async def test_get_history_with_entries(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Allocate + deduct, verify history order and count."""
    await allocate_credits(
        session=db_session,
        user_id=test_user.id,
        amount=Decimal("100.0000"),
        source=TransactionSource.STRIPE,
        reference_id="test-hist-alloc-100",
    )
    await deduct_credits(
        session=db_session,
        user_id=test_user.id,
        amount=Decimal("30.0000"),
        source=TransactionSource.USAGE,
        reference_id="test-hist-deduct-30",
    )
    await db_session.flush()

    resp = await client.get(
        "/api/v1/credits/history",
        headers=_auth_headers(test_user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2

    # Newest first
    entries = data["entries"]
    assert entries[0]["direction"] == "DEBIT"
    assert entries[0]["reference_id"] == "test-hist-deduct-30"
    assert entries[1]["direction"] == "CREDIT"
    assert entries[1]["reference_id"] == "test-hist-alloc-100"


async def test_get_history_pagination(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Verify limit and offset pagination params."""
    # Create 5 entries
    for i in range(5):
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("10.0000"),
            source=TransactionSource.STRIPE,
            reference_id=f"test-page-{i}",
        )
    await db_session.flush()

    headers = _auth_headers(test_user)

    # First page
    resp1 = await client.get(
        "/api/v1/credits/history?limit=2&offset=0",
        headers=headers,
    )
    assert resp1.status_code == 200
    page1 = resp1.json()
    assert page1["count"] == 2

    # Second page
    resp2 = await client.get(
        "/api/v1/credits/history?limit=2&offset=2",
        headers=headers,
    )
    assert resp2.status_code == 200
    page2 = resp2.json()
    assert page2["count"] == 2

    # No overlap
    page1_ids = {e["id"] for e in page1["entries"]}
    page2_ids = {e["id"] for e in page2["entries"]}
    assert page1_ids.isdisjoint(page2_ids)

    # Last page with only 1 remaining
    resp3 = await client.get(
        "/api/v1/credits/history?limit=2&offset=4",
        headers=headers,
    )
    assert resp3.status_code == 200
    assert resp3.json()["count"] == 1


# ---------------------------------------------------------------------------
# POST /api/v1/credits/deduct
# ---------------------------------------------------------------------------


async def test_deduct_credits_success(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Allocate 100, deduct 30 via endpoint, verify response."""
    await allocate_credits(
        session=db_session,
        user_id=test_user.id,
        amount=Decimal("100.0000"),
        source=TransactionSource.STRIPE,
        reference_id="test-deduct-api-alloc-100",
    )
    await db_session.flush()

    resp = await client.post(
        "/api/v1/credits/deduct",
        headers=_auth_headers(test_user),
        json={
            "amount": "30.0000",
            "reference_id": "test-deduct-api-30",
            "description": "Render job usage",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["amount"] == "30.0000"
    assert data["direction"] == "DEBIT"
    assert data["source"] == "USAGE"
    assert data["balance_after"] == "70.0000"
    assert data["reference_id"] == "test-deduct-api-30"
    assert data["description"] == "Render job usage"


async def test_deduct_insufficient(
    client: AsyncClient,
    test_user: User,
) -> None:
    """Returns 402 with available/requested when balance is insufficient."""
    resp = await client.post(
        "/api/v1/credits/deduct",
        headers=_auth_headers(test_user),
        json={
            "amount": "500.0000",
            "reference_id": "test-deduct-insuff-500",
        },
    )
    assert resp.status_code == 402
    data = resp.json()
    assert data["detail"] == "Insufficient credits"
    assert "available" in data
    assert data["requested"] == "500.0000"


# ---------------------------------------------------------------------------
# Authentication guard
# ---------------------------------------------------------------------------


async def test_unauthenticated_returns_401(
    client: AsyncClient,
) -> None:
    """Requests without an auth header return 401."""
    resp = await client.get("/api/v1/credits/balance")
    assert resp.status_code in (401, 403)
