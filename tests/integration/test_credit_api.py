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

"""Integration tests for credit API cross-user isolation (OWASP A01) and edge cases.

Supplements the unit-level tests in ``tests/test_credit_api.py`` with:
- Cross-user balance, history, and deduct isolation (A01)
- Admin balance access
- Boundary conditions (exact balance deduct, zero/negative/invalid amounts)
- Multi-allocation summation
- History ordering after mixed operations
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from passlib.hash import bcrypt

from core.auth.jwt import create_access_token
from core.ledger.service import allocate_credits
from core.models.base import TransactionSource, User

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


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
# Helper: per-user auth headers
# ---------------------------------------------------------------------------


def _auth_headers(user: User) -> dict[str, str]:
    """Create Authorization headers for the given user."""
    token = create_access_token({"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures: second (non-admin) user for cross-user tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def second_user(db_session: AsyncSession) -> User:
    """Insert and return a second regular user for isolation tests."""
    user = User(
        email="user2@rendertrust.com",
        name="Second User",
        hashed_password=bcrypt.hash("testpass123"),
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# =========================================================================
# OWASP A01 -- Cross-user isolation tests
# =========================================================================


class TestCrossUserBalanceIsolation:
    """Verify that one user's balance is invisible to another user."""

    async def test_user_b_sees_zero_after_user_a_allocates(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        second_user: User,
    ) -> None:
        """User A allocates credits; User B queries balance and sees zero."""
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("500.0000"),
            source=TransactionSource.STRIPE,
            reference_id="cross-user-alloc-a-500",
        )
        await db_session.flush()

        # User A should see their balance
        resp_a = await client.get(
            "/api/v1/credits/balance",
            headers=_auth_headers(test_user),
        )
        assert resp_a.status_code == 200
        assert resp_a.json()["balance"] == "500.0000"

        # User B must see zero -- NOT User A's balance
        resp_b = await client.get(
            "/api/v1/credits/balance",
            headers=_auth_headers(second_user),
        )
        assert resp_b.status_code == 200
        data_b = resp_b.json()
        assert data_b["balance"] == "0.0000"
        assert data_b["user_id"] == str(second_user.id)


class TestCrossUserHistoryIsolation:
    """Verify that one user's ledger history is invisible to another user."""

    async def test_user_b_sees_empty_history_after_user_a_transacts(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        second_user: User,
    ) -> None:
        """User A has ledger entries; User B queries history and sees nothing."""
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("100.0000"),
            source=TransactionSource.STRIPE,
            reference_id="cross-hist-alloc-a-100",
        )
        await db_session.flush()

        # User A should see 1 entry
        resp_a = await client.get(
            "/api/v1/credits/history",
            headers=_auth_headers(test_user),
        )
        assert resp_a.status_code == 200
        assert resp_a.json()["count"] == 1

        # User B must see empty history
        resp_b = await client.get(
            "/api/v1/credits/history",
            headers=_auth_headers(second_user),
        )
        assert resp_b.status_code == 200
        data_b = resp_b.json()
        assert data_b["count"] == 0
        assert data_b["entries"] == []


class TestCrossUserDeductIsolation:
    """Verify that one user cannot deduct from another user's balance."""

    async def test_user_b_gets_402_when_user_a_has_credits(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        second_user: User,
    ) -> None:
        """User A has credits; User B tries to deduct and gets 402 (insufficient)."""
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("1000.0000"),
            source=TransactionSource.STRIPE,
            reference_id="cross-deduct-alloc-a-1000",
        )
        await db_session.flush()

        # User B attempts deduction -- must fail with 402 (no balance)
        resp_b = await client.post(
            "/api/v1/credits/deduct",
            headers=_auth_headers(second_user),
            json={
                "amount": "50.0000",
                "reference_id": "cross-deduct-b-50",
                "description": "Attempted cross-user deduction",
            },
        )
        assert resp_b.status_code == 402
        data_b = resp_b.json()
        assert data_b["detail"] == "Insufficient credits"
        assert data_b["available"] == "0.0000"
        assert data_b["requested"] == "50.0000"

        # Verify User A's balance is unaffected
        resp_a = await client.get(
            "/api/v1/credits/balance",
            headers=_auth_headers(test_user),
        )
        assert resp_a.status_code == 200
        assert resp_a.json()["balance"] == "1000.0000"


# =========================================================================
# Admin balance access
# =========================================================================


class TestAdminBalance:
    """Verify that admin users can query their own balance."""

    async def test_admin_queries_own_balance(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        """Admin user queries their own balance correctly."""
        await allocate_credits(
            session=db_session,
            user_id=admin_user.id,
            amount=Decimal("200.0000"),
            source=TransactionSource.ADJUSTMENT,
            reference_id="admin-alloc-200",
        )
        await db_session.flush()

        resp = await client.get(
            "/api/v1/credits/balance",
            headers=_auth_headers(admin_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["balance"] == "200.0000"
        assert data["user_id"] == str(admin_user.id)


# =========================================================================
# Edge cases -- boundary deductions
# =========================================================================


class TestDeductBoundaryConditions:
    """Test deduction edge cases: exact balance, zero, negative, invalid."""

    async def test_deduct_exact_balance_to_zero(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Allocate 100 then deduct exactly 100 -- balance becomes 0."""
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("100.0000"),
            source=TransactionSource.STRIPE,
            reference_id="exact-alloc-100",
        )
        await db_session.flush()

        resp = await client.post(
            "/api/v1/credits/deduct",
            headers=_auth_headers(test_user),
            json={
                "amount": "100.0000",
                "reference_id": "exact-deduct-100",
                "description": "Drain entire balance",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["balance_after"] == "0.0000"
        assert data["direction"] == "DEBIT"
        assert data["amount"] == "100.0000"

        # Confirm balance is actually zero via GET
        balance_resp = await client.get(
            "/api/v1/credits/balance",
            headers=_auth_headers(test_user),
        )
        assert balance_resp.status_code == 200
        assert balance_resp.json()["balance"] == "0.0000"

    async def test_deduct_zero_amount_returns_422(
        self,
        client: AsyncClient,
        test_user: User,
    ) -> None:
        """POST deduct with amount '0' returns 422 validation error."""
        resp = await client.post(
            "/api/v1/credits/deduct",
            headers=_auth_headers(test_user),
            json={
                "amount": "0",
                "reference_id": "zero-deduct",
            },
        )
        assert resp.status_code == 422

    async def test_deduct_negative_amount_returns_422(
        self,
        client: AsyncClient,
        test_user: User,
    ) -> None:
        """POST deduct with amount '-10' returns 422 validation error."""
        resp = await client.post(
            "/api/v1/credits/deduct",
            headers=_auth_headers(test_user),
            json={
                "amount": "-10",
                "reference_id": "negative-deduct",
            },
        )
        assert resp.status_code == 422

    async def test_deduct_non_numeric_amount_returns_422(
        self,
        client: AsyncClient,
        test_user: User,
    ) -> None:
        """POST deduct with amount 'not-a-number' returns 422 validation error."""
        resp = await client.post(
            "/api/v1/credits/deduct",
            headers=_auth_headers(test_user),
            json={
                "amount": "not-a-number",
                "reference_id": "invalid-deduct",
            },
        )
        assert resp.status_code == 422


# =========================================================================
# Multiple allocations sum correctly
# =========================================================================


class TestMultipleAllocations:
    """Verify that multiple allocations accumulate correctly."""

    async def test_three_allocations_sum_to_150(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Allocate 50 three times; balance should be 150."""
        for i in range(3):
            await allocate_credits(
                session=db_session,
                user_id=test_user.id,
                amount=Decimal("50.0000"),
                source=TransactionSource.STRIPE,
                reference_id=f"multi-alloc-{i}",
            )
        await db_session.flush()

        resp = await client.get(
            "/api/v1/credits/balance",
            headers=_auth_headers(test_user),
        )
        assert resp.status_code == 200
        assert resp.json()["balance"] == "150.0000"


# =========================================================================
# History ordering after mixed operations
# =========================================================================


class TestHistoryOrdering:
    """Verify history returns entries newest-first after mixed operations."""

    async def test_mixed_operations_history_order(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Allocate, deduct, allocate -- history returns newest first."""
        # Operation 1: allocate 100
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("100.0000"),
            source=TransactionSource.STRIPE,
            reference_id="mixed-alloc-1",
        )
        await db_session.flush()

        # Operation 2: deduct 30 via API
        resp_deduct = await client.post(
            "/api/v1/credits/deduct",
            headers=_auth_headers(test_user),
            json={
                "amount": "30.0000",
                "reference_id": "mixed-deduct-1",
                "description": "Usage charge",
            },
        )
        assert resp_deduct.status_code == 200

        # Operation 3: allocate 50
        await allocate_credits(
            session=db_session,
            user_id=test_user.id,
            amount=Decimal("50.0000"),
            source=TransactionSource.STRIPE,
            reference_id="mixed-alloc-2",
        )
        await db_session.flush()

        # Query history -- should be newest first
        resp = await client.get(
            "/api/v1/credits/history",
            headers=_auth_headers(test_user),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3

        entries = data["entries"]
        # Newest first: alloc-2, deduct-1, alloc-1
        assert entries[0]["reference_id"] == "mixed-alloc-2"
        assert entries[0]["direction"] == "CREDIT"
        assert entries[0]["balance_after"] == "120.0000"

        assert entries[1]["reference_id"] == "mixed-deduct-1"
        assert entries[1]["direction"] == "DEBIT"
        assert entries[1]["balance_after"] == "70.0000"

        assert entries[2]["reference_id"] == "mixed-alloc-1"
        assert entries[2]["direction"] == "CREDIT"
        assert entries[2]["balance_after"] == "100.0000"
