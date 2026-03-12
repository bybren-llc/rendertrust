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

"""
Tests for the proof verification API (REN-132).

Covers:
    - GET /api/v1/ledger/{entry_id}/proof -- Merkle inclusion proof retrieval
    - GET /api/v1/ledger/{entry_id}/verify -- On-chain verification
    - GET /api/v1/ledger/anchors -- Paginated anchor listing
    - 404 for non-existent and un-anchored entries
    - Pagination and date filtering for anchor list
    - Authentication requirement on all endpoints
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from core.ledger.anchor.chain import ChainVerification
from core.ledger.anchor.models import AnchorRecord, CreditLedgerEntry
from core.ledger.anchor.service import AnchoringService

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


# =====================================================================
# Helpers
# =====================================================================


def _make_entry(
    entry_id: int = 1,
    account_id: str = "user:alice",
    delta_usd: str = "10.00",
    created_at: datetime.datetime | None = None,
    anchor_id: uuid.UUID | None = None,
) -> CreditLedgerEntry:
    """Build a ``CreditLedgerEntry`` for testing."""
    entry = CreditLedgerEntry()
    entry.id = entry_id
    entry.account_id = account_id
    entry.delta_usd = delta_usd
    entry.created_at = created_at or datetime.datetime(
        2024, 6, 1, 12, 0, 0, tzinfo=datetime.UTC
    )
    entry.ref_event_id = None
    entry.anchor_id = anchor_id
    return entry


async def _seed_anchor_data(
    session: AsyncSession,
    entry_count: int = 4,
    tx_hash: str = "0xabcdef1234567890" + "0" * 48,
    block_number: int = 42,
) -> tuple[AnchorRecord, list[CreditLedgerEntry]]:
    """Create an anchor record and associated ledger entries in the database.

    Returns the anchor record and the list of entries.
    """
    # Build entries first to compute the Merkle root
    entries = []
    for i in range(1, entry_count + 1):
        entry = _make_entry(
            entry_id=i,
            account_id=f"user:{i}",
            delta_usd=f"{i * 5}.00",
        )
        entries.append(entry)

    # Compute the Merkle root from the entries
    root = AnchoringService.create_merkle_root(entries)

    # Create anchor record
    anchor_id = uuid.uuid4()
    anchor = AnchorRecord(
        id=anchor_id,
        merkle_root=root.hex(),
        tx_hash=tx_hash,
        block_number=block_number,
        entry_count=entry_count,
        anchored_at=datetime.datetime(2024, 6, 1, 13, 0, 0, tzinfo=datetime.UTC),
    )
    session.add(anchor)
    await session.flush()

    # Create entries linked to the anchor
    db_entries = []
    for i in range(1, entry_count + 1):
        entry = CreditLedgerEntry()
        entry.id = i
        entry.account_id = f"user:{i}"
        entry.delta_usd = f"{i * 5}.00"
        entry.created_at = datetime.datetime(
            2024, 6, 1, 12, 0, 0, tzinfo=datetime.UTC
        )
        entry.ref_event_id = None
        entry.anchor_id = anchor_id
        session.add(entry)
        db_entries.append(entry)

    await session.flush()
    return anchor, db_entries


async def _seed_unanchored_entry(
    session: AsyncSession,
    entry_id: int = 100,
) -> CreditLedgerEntry:
    """Create a single un-anchored ledger entry."""
    entry = CreditLedgerEntry()
    entry.id = entry_id
    entry.account_id = "user:unanchored"
    entry.delta_usd = "50.00"
    entry.created_at = datetime.datetime(
        2024, 6, 1, 12, 0, 0, tzinfo=datetime.UTC
    )
    entry.ref_event_id = None
    entry.anchor_id = None
    session.add(entry)
    await session.flush()
    return entry


def _mock_chain_client(
    verified: bool = True,
    on_chain_root: str = "",
) -> MagicMock:
    """Create a mock chain client for dependency injection."""
    mock = MagicMock()
    mock.verify_root.return_value = ChainVerification(
        verified=verified,
        on_chain_root=on_chain_root,
    )
    return mock


# =====================================================================
# GET /api/v1/ledger/{entry_id}/proof
# =====================================================================


class TestGetEntryProof:
    """Test the Merkle proof retrieval endpoint."""

    @pytest.mark.asyncio
    async def test_proof_returns_valid_proof_for_anchored_entry(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict
    ):
        """Proof endpoint returns valid proof data for an anchored entry."""
        anchor, _entries = await _seed_anchor_data(db_session, entry_count=4)

        response = await client.get(
            "/api/v1/ledger/1/proof",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["entry_id"] == 1
        assert data["merkle_root"] == anchor.merkle_root
        assert data["anchor_tx_hash"] == anchor.tx_hash
        assert data["block_number"] == anchor.block_number
        assert isinstance(data["proof_hashes"], list)
        assert isinstance(data["directions"], list)
        assert len(data["proof_hashes"]) == len(data["directions"])

    @pytest.mark.asyncio
    async def test_proof_contains_correct_directions(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict
    ):
        """Proof directions are valid 'left'/'right' strings."""
        await _seed_anchor_data(db_session, entry_count=4)

        response = await client.get(
            "/api/v1/ledger/2/proof",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        for direction in data["directions"]:
            assert direction in ("left", "right")

    @pytest.mark.asyncio
    async def test_proof_hashes_are_valid_hex(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict
    ):
        """Proof hashes should be valid hex strings (64 chars = 32 bytes)."""
        await _seed_anchor_data(db_session, entry_count=4)

        response = await client.get(
            "/api/v1/ledger/1/proof",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        for proof_hash in data["proof_hashes"]:
            assert len(proof_hash) == 64  # 32 bytes = 64 hex chars
            int(proof_hash, 16)  # Should not raise -- valid hex

    @pytest.mark.asyncio
    async def test_proof_404_for_nonexistent_entry(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Proof endpoint returns 404 for a non-existent entry."""
        response = await client.get(
            "/api/v1/ledger/99999/proof",
            headers=auth_headers,
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_proof_404_for_unanchored_entry(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict
    ):
        """Proof endpoint returns 404 for an un-anchored entry."""
        await _seed_unanchored_entry(db_session, entry_id=100)

        response = await client.get(
            "/api/v1/ledger/100/proof",
            headers=auth_headers,
        )

        assert response.status_code == 404
        assert "not been anchored" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_proof_requires_authentication(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Proof endpoint returns 401 without auth headers."""
        await _seed_anchor_data(db_session, entry_count=2)

        response = await client.get("/api/v1/ledger/1/proof")

        assert response.status_code in (401, 403)


# =====================================================================
# GET /api/v1/ledger/{entry_id}/verify
# =====================================================================


class TestVerifyEntryProof:
    """Test the on-chain verification endpoint."""

    @pytest.mark.asyncio
    async def test_verify_returns_verified_true(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict
    ):
        """Verify endpoint returns verified=true when chain data matches."""
        anchor, _ = await _seed_anchor_data(db_session, entry_count=4)

        # Override the anchoring deps to use a mock chain client
        from core.api.v1.ledger import _get_anchoring_deps

        mock_chain = _mock_chain_client(
            verified=True,
            on_chain_root=anchor.merkle_root,
        )

        def _mock_deps():
            svc = AnchoringService(chain_client=mock_chain, batch_size=100)
            return svc, mock_chain

        app = client._transport.app  # type: ignore[union-attr]
        app.dependency_overrides[_get_anchoring_deps] = _mock_deps

        try:
            response = await client.get(
                "/api/v1/ledger/1/verify",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["verified"] is True
            assert data["entry_id"] == 1
            assert data["merkle_root"] == anchor.merkle_root
            assert data["on_chain_root"] == anchor.merkle_root
            assert data["block_number"] == anchor.block_number
            assert data["tx_hash"] == anchor.tx_hash
        finally:
            app.dependency_overrides.pop(_get_anchoring_deps, None)

    @pytest.mark.asyncio
    async def test_verify_returns_verified_false_on_mismatch(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict
    ):
        """Verify endpoint returns verified=false when chain root doesn't match."""
        _anchor, _ = await _seed_anchor_data(db_session, entry_count=4)

        from core.api.v1.ledger import _get_anchoring_deps

        fake_on_chain_root = "aa" * 32  # Different from actual root
        mock_chain = _mock_chain_client(
            verified=False,
            on_chain_root=fake_on_chain_root,
        )

        def _mock_deps():
            svc = AnchoringService(chain_client=mock_chain, batch_size=100)
            return svc, mock_chain

        app = client._transport.app  # type: ignore[union-attr]
        app.dependency_overrides[_get_anchoring_deps] = _mock_deps

        try:
            response = await client.get(
                "/api/v1/ledger/1/verify",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["verified"] is False
            assert data["on_chain_root"] == fake_on_chain_root
        finally:
            app.dependency_overrides.pop(_get_anchoring_deps, None)

    @pytest.mark.asyncio
    async def test_verify_404_for_nonexistent_entry(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Verify endpoint returns 404 for a non-existent entry."""
        response = await client.get(
            "/api/v1/ledger/99999/verify",
            headers=auth_headers,
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_verify_404_for_unanchored_entry(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict
    ):
        """Verify endpoint returns 404 for an un-anchored entry."""
        await _seed_unanchored_entry(db_session, entry_id=200)

        response = await client.get(
            "/api/v1/ledger/200/verify",
            headers=auth_headers,
        )

        assert response.status_code == 404
        assert "not been anchored" in response.json()["detail"].lower()


# =====================================================================
# GET /api/v1/ledger/anchors
# =====================================================================


class TestListAnchors:
    """Test the anchor listing endpoint."""

    @pytest.mark.asyncio
    async def test_list_anchors_returns_records(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict
    ):
        """Anchors endpoint returns anchor records."""
        anchor, _ = await _seed_anchor_data(db_session, entry_count=3)

        response = await client.get(
            "/api/v1/ledger/anchors",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["page"] == 1
        assert data["per_page"] == 20
        assert len(data["anchors"]) == 1

        record = data["anchors"][0]
        assert record["merkle_root"] == anchor.merkle_root
        assert record["tx_hash"] == anchor.tx_hash
        assert record["block_number"] == anchor.block_number
        assert record["entry_count"] == 3

    @pytest.mark.asyncio
    async def test_list_anchors_empty(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Anchors endpoint returns empty list when no anchors exist."""
        response = await client.get(
            "/api/v1/ledger/anchors",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["anchors"] == []

    @pytest.mark.asyncio
    async def test_list_anchors_pagination(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict
    ):
        """Anchors endpoint supports page and per_page parameters."""
        # Create multiple anchor records
        for i in range(5):
            anchor_id = uuid.uuid4()
            anchor = AnchorRecord(
                id=anchor_id,
                merkle_root="ab" * 32,
                tx_hash=f"0x{'0' * 62}{i:02d}",
                block_number=100 + i,
                entry_count=2,
                anchored_at=datetime.datetime(
                    2024, 6, 1, 13, i, 0, tzinfo=datetime.UTC
                ),
            )
            db_session.add(anchor)
        await db_session.flush()

        # Request page 2 with per_page=2
        response = await client.get(
            "/api/v1/ledger/anchors?page=2&per_page=2",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert data["per_page"] == 2
        assert len(data["anchors"]) == 2

    @pytest.mark.asyncio
    async def test_list_anchors_since_filter(
        self, client: AsyncClient, db_session: AsyncSession, auth_headers: dict
    ):
        """Anchors endpoint filters by 'since' date."""
        # Create anchors with different dates
        for i, day in enumerate([1, 10, 20]):
            anchor_id = uuid.uuid4()
            anchor = AnchorRecord(
                id=anchor_id,
                merkle_root="cd" * 32,
                tx_hash=f"0x{'1' * 62}{i:02d}",
                block_number=200 + i,
                entry_count=1,
                anchored_at=datetime.datetime(
                    2024, 6, day, 12, 0, 0, tzinfo=datetime.UTC
                ),
            )
            db_session.add(anchor)
        await db_session.flush()

        # Filter to only get anchors from June 10th onwards
        response = await client.get(
            "/api/v1/ledger/anchors",
            params={"since": "2024-06-10T00:00:00+00:00"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2  # June 10 and June 20

    @pytest.mark.asyncio
    async def test_list_anchors_invalid_since_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Anchors endpoint returns 422 for invalid since format."""
        response = await client.get(
            "/api/v1/ledger/anchors?since=not-a-date",
            headers=auth_headers,
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_list_anchors_requires_authentication(
        self, client: AsyncClient,
    ):
        """Anchors endpoint returns 401 without auth headers."""
        response = await client.get("/api/v1/ledger/anchors")

        assert response.status_code in (401, 403)
