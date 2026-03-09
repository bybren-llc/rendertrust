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

"""Tests for the Stripe webhook handler (REN-79).

Verifies credit allocation wiring between the Stripe checkout.session.completed
event and the credit ledger service. All tests mock
``stripe.Webhook.construct_event`` since real Stripe signatures cannot be
generated in tests.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import stripe

from core.models.base import CreditLedgerEntry, TransactionDirection, TransactionSource

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.models.base import User

WEBHOOK_URL = "/api/v1/webhooks/stripe"


def _checkout_event(
    *,
    event_id: str = "evt_test_123",
    session_id: str = "cs_test_abc",
    client_reference_id: str | None = "00000000-0000-0000-0000-000000000001",
    sku: str | None = "cred10",
) -> dict:
    """Build a minimal checkout.session.completed event payload."""
    metadata = {}
    if sku is not None:
        metadata["sku"] = sku

    session_obj: dict = {
        "id": session_id,
        "client_reference_id": client_reference_id,
        "metadata": metadata,
    }

    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {"object": session_obj},
    }


# ---------------------------------------------------------------------------
# Happy path: credit allocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_completed_allocates_credits(
    client: AsyncClient,
    test_user: User,
    db_session: AsyncSession,
) -> None:
    """A valid checkout.session.completed event allocates credits."""
    event = _checkout_event(
        client_reference_id=str(test_user.id),
        sku="cred10",
        session_id="cs_alloc_001",
    )

    with patch("stripe.Webhook.construct_event", return_value=event):
        response = await client.post(
            WEBHOOK_URL,
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=sig"},
        )

    assert response.status_code == 200
    assert response.json() == {"received": True}

    # Verify a ledger entry was created with the correct values.
    from sqlalchemy import select

    result = await db_session.execute(
        select(CreditLedgerEntry).where(
            CreditLedgerEntry.reference_id == "cs_alloc_001",
        )
    )
    entry = result.scalar_one_or_none()
    assert entry is not None
    assert entry.user_id == test_user.id
    assert entry.amount == Decimal("100")
    assert entry.direction == TransactionDirection.CREDIT
    assert entry.source == TransactionSource.STRIPE
    assert entry.description == "Stripe checkout: cred10"


# ---------------------------------------------------------------------------
# Idempotency: same event twice
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_completed_idempotent(
    client: AsyncClient,
    test_user: User,
    db_session: AsyncSession,
) -> None:
    """Replaying the same event does not create a duplicate ledger entry."""
    event = _checkout_event(
        client_reference_id=str(test_user.id),
        sku="cred10",
        session_id="cs_idemp_001",
    )

    with patch("stripe.Webhook.construct_event", return_value=event):
        r1 = await client.post(
            WEBHOOK_URL,
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=sig"},
        )
        r2 = await client.post(
            WEBHOOK_URL,
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=sig"},
        )

    assert r1.status_code == 200
    assert r2.status_code == 200

    # Only one ledger entry should exist for this reference_id.
    from sqlalchemy import func, select

    result = await db_session.execute(
        select(func.count()).where(
            CreditLedgerEntry.reference_id == "cs_idemp_001",
        )
    )
    assert result.scalar_one() == 1


# ---------------------------------------------------------------------------
# Unknown SKU
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_completed_unknown_sku(
    client: AsyncClient,
    test_user: User,
    db_session: AsyncSession,
) -> None:
    """An unknown SKU logs a warning but still returns received: True."""
    event = _checkout_event(
        client_reference_id=str(test_user.id),
        sku="cred_unknown",
        session_id="cs_unknown_001",
    )

    with patch("stripe.Webhook.construct_event", return_value=event):
        response = await client.post(
            WEBHOOK_URL,
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=sig"},
        )

    assert response.status_code == 200
    assert response.json() == {"received": True}

    # No ledger entry should have been created.
    from sqlalchemy import func, select

    result = await db_session.execute(
        select(func.count()).where(
            CreditLedgerEntry.reference_id == "cs_unknown_001",
        )
    )
    assert result.scalar_one() == 0


# ---------------------------------------------------------------------------
# Missing metadata / SKU
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_completed_missing_metadata(
    client: AsyncClient,
    test_user: User,
    db_session: AsyncSession,
) -> None:
    """Missing metadata/sku logs a warning but still returns received: True."""
    event = _checkout_event(
        client_reference_id=str(test_user.id),
        sku=None,
        session_id="cs_nometa_001",
    )

    with patch("stripe.Webhook.construct_event", return_value=event):
        response = await client.post(
            WEBHOOK_URL,
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=sig"},
        )

    assert response.status_code == 200
    assert response.json() == {"received": True}

    # No ledger entry should have been created.
    from sqlalchemy import func, select

    result = await db_session.execute(
        select(func.count()).where(
            CreditLedgerEntry.reference_id == "cs_nometa_001",
        )
    )
    assert result.scalar_one() == 0


# ---------------------------------------------------------------------------
# Missing stripe-signature header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_signature_returns_400(client: AsyncClient) -> None:
    """A request without a stripe-signature header is rejected with 400."""
    response = await client.post(
        WEBHOOK_URL,
        content=b"{}",
    )
    assert response.status_code == 400
    assert "Missing stripe-signature" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Invalid signature
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_signature_returns_400(client: AsyncClient) -> None:
    """An invalid Stripe signature is rejected with 400."""
    with patch(
        "stripe.Webhook.construct_event",
        side_effect=stripe.error.SignatureVerificationError("bad sig", "sig_header"),
    ):
        response = await client.post(
            WEBHOOK_URL,
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=badsig"},
        )

    assert response.status_code == 400
    assert "Invalid signature" in response.json()["detail"]
