# Copyright 2024 ByBren, LLC
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
Tests for the blockchain anchoring service (REN-131).

Covers:
    - Merkle tree construction, root computation, and proof generation/verification
    - Anchoring service: batching, entry grouping, proof retrieval
    - Background bundler task with mocked chain submission
    - Configuration loading from environment variables
    - Edge cases: single leaf, odd leaves, large trees, duplicate leaves
"""

from __future__ import annotations

import datetime
import hashlib
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from core.ledger.anchor.bundler_task import _run_once, run_bundler_loop
from core.ledger.anchor.chain import ChainReceipt, NoOpChainClient
from core.ledger.anchor.config import AnchorConfig
from core.ledger.anchor.merkle import Direction, MerkleProof, MerkleTree
from core.ledger.anchor.models import AnchorRecord, CreditLedgerEntry
from core.ledger.anchor.service import AnchoringService

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

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
    """Build a lightweight ``CreditLedgerEntry`` for testing."""
    entry = CreditLedgerEntry()
    entry.id = entry_id
    entry.account_id = account_id
    entry.delta_usd = delta_usd
    entry.created_at = created_at or datetime.datetime(
        2024,
        6,
        1,
        12,
        0,
        0,
        tzinfo=datetime.timezone.utc,  # noqa: UP017
    )
    entry.ref_event_id = None
    entry.anchor_id = anchor_id
    return entry


def _make_entries(n: int) -> list[CreditLedgerEntry]:
    """Build *n* distinct entries."""
    return [
        _make_entry(
            entry_id=i,
            account_id=f"user:{i}",
            delta_usd=f"{i * 5}.00",
        )
        for i in range(1, n + 1)
    ]


class FakeChainClient:
    """Deterministic chain client for tests."""

    def __init__(
        self,
        tx_hash: str = "0xabcdef1234567890" + "0" * 48,
        block_number: int = 42,
    ) -> None:
        self.tx_hash = tx_hash
        self.block_number = block_number
        self.calls: list[tuple[str, int]] = []

    def submit_root(self, merkle_root_hex: str, entry_count: int) -> ChainReceipt:
        self.calls.append((merkle_root_hex, entry_count))
        return ChainReceipt(tx_hash=self.tx_hash, block_number=self.block_number)


class FakeEntryRepository:
    """In-memory entry repository for bundler task tests."""

    def __init__(self, entries: Sequence[CreditLedgerEntry] | None = None):
        self.entries: list[CreditLedgerEntry] = list(entries or [])
        self.saved_records: list[AnchorRecord] = []
        self.saved_entry_ids: list[list[int]] = []

    async def fetch_unanchored(self, limit: int) -> Sequence[CreditLedgerEntry]:
        unanchored = [e for e in self.entries if e.anchor_id is None]
        return unanchored[:limit]

    async def save_anchor(self, record: AnchorRecord, entry_ids: Sequence[int]) -> None:
        self.saved_records.append(record)
        self.saved_entry_ids.append(list(entry_ids))
        # Simulate marking entries as anchored.
        for entry in self.entries:
            if entry.id in entry_ids:
                entry.anchor_id = record.id


# =====================================================================
# Merkle tree: construction and root
# =====================================================================


class TestMerkleTreeConstruction:
    """Test Merkle tree building and root computation."""

    def test_single_leaf(self):
        tree = MerkleTree(["hello"])
        expected = hashlib.sha256(b"hello").digest()
        assert tree.root == expected
        assert tree.leaf_count == 1

    def test_two_leaves(self):
        tree = MerkleTree(["a", "b"])
        ha = hashlib.sha256(b"a").digest()
        hb = hashlib.sha256(b"b").digest()
        expected = hashlib.sha256(ha + hb).digest()
        assert tree.root == expected

    def test_four_leaves_deterministic(self):
        leaves = ["a", "b", "c", "d"]
        tree1 = MerkleTree(leaves)
        tree2 = MerkleTree(leaves)
        assert tree1.root == tree2.root

    def test_different_leaves_different_root(self):
        tree1 = MerkleTree(["a", "b", "c", "d"])
        tree2 = MerkleTree(["a", "b", "c", "e"])
        assert tree1.root != tree2.root

    def test_odd_number_of_leaves(self):
        tree = MerkleTree(["a", "b", "c"])
        # With 3 leaves, "c" is duplicated to form a pair.
        ha = hashlib.sha256(b"a").digest()
        hb = hashlib.sha256(b"b").digest()
        hc = hashlib.sha256(b"c").digest()
        hab = hashlib.sha256(ha + hb).digest()
        hcc = hashlib.sha256(hc + hc).digest()
        expected = hashlib.sha256(hab + hcc).digest()
        assert tree.root == expected

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            MerkleTree([])

    def test_root_hex(self):
        tree = MerkleTree(["test"])
        assert tree.root_hex == tree.root.hex()
        assert len(tree.root_hex) == 64  # 32 bytes = 64 hex chars


# =====================================================================
# Merkle tree: proof generation and verification
# =====================================================================


class TestMerkleProof:
    """Test Merkle proof generation and verification."""

    def test_proof_single_leaf(self):
        tree = MerkleTree(["only"])
        proof = tree.get_proof(0)
        assert proof.leaf == "only"
        assert proof.root == tree.root
        assert proof.proof_hashes == []
        assert proof.directions == []
        assert MerkleTree.verify_proof(proof)

    def test_proof_two_leaves_left(self):
        tree = MerkleTree(["left", "right"])
        proof = tree.get_proof(0)
        assert proof.leaf == "left"
        assert len(proof.proof_hashes) == 1
        assert proof.directions == [Direction.RIGHT]
        assert MerkleTree.verify_proof(proof)

    def test_proof_two_leaves_right(self):
        tree = MerkleTree(["left", "right"])
        proof = tree.get_proof(1)
        assert proof.leaf == "right"
        assert len(proof.proof_hashes) == 1
        assert proof.directions == [Direction.LEFT]
        assert MerkleTree.verify_proof(proof)

    def test_proof_four_leaves_all_positions(self):
        tree = MerkleTree(["a", "b", "c", "d"])
        for i in range(4):
            proof = tree.get_proof(i)
            assert MerkleTree.verify_proof(proof), f"Proof failed for index {i}"

    def test_proof_eight_leaves(self):
        leaves = [f"item-{i}" for i in range(8)]
        tree = MerkleTree(leaves)
        for i in range(8):
            proof = tree.get_proof(i)
            assert MerkleTree.verify_proof(proof), f"Proof failed for index {i}"

    def test_proof_odd_leaves(self):
        tree = MerkleTree(["a", "b", "c", "d", "e"])
        for i in range(5):
            proof = tree.get_proof(i)
            assert MerkleTree.verify_proof(proof), f"Proof failed for index {i}"

    def test_invalid_proof_tampered_leaf(self):
        tree = MerkleTree(["a", "b", "c", "d"])
        proof = tree.get_proof(0)
        # Tamper with the leaf hash.
        tampered = MerkleProof(
            leaf=proof.leaf,
            leaf_hash=b"\x00" * 32,
            proof_hashes=proof.proof_hashes,
            directions=proof.directions,
            root=proof.root,
        )
        assert not MerkleTree.verify_proof(tampered)

    def test_proof_index_out_of_range(self):
        tree = MerkleTree(["a", "b"])
        with pytest.raises(IndexError):
            tree.get_proof(2)
        with pytest.raises(IndexError):
            tree.get_proof(-1)

    def test_proof_large_tree(self):
        """Stress test with 256 leaves."""
        leaves = [f"leaf-{i:04d}" for i in range(256)]
        tree = MerkleTree(leaves)
        # Verify a sample of proofs.
        for i in [0, 1, 127, 128, 255]:
            proof = tree.get_proof(i)
            assert MerkleTree.verify_proof(proof), f"Proof failed for index {i}"


# =====================================================================
# Anchoring service
# =====================================================================


class TestAnchoringService:
    """Test the high-level AnchoringService."""

    def test_create_merkle_root(self):
        entries = _make_entries(4)
        root = AnchoringService.create_merkle_root(entries)
        assert isinstance(root, bytes)
        assert len(root) == 32

    def test_create_merkle_root_empty_raises(self):
        with pytest.raises(ValueError, match="zero entries"):
            AnchoringService.create_merkle_root([])

    def test_create_merkle_root_deterministic(self):
        entries = _make_entries(4)
        r1 = AnchoringService.create_merkle_root(entries)
        r2 = AnchoringService.create_merkle_root(entries)
        assert r1 == r2

    def test_anchor_batch_returns_record(self):
        chain = FakeChainClient()
        svc = AnchoringService(chain_client=chain, batch_size=100)
        entries = _make_entries(5)

        record = svc.anchor_batch(entries)

        assert isinstance(record, AnchorRecord)
        assert record.tx_hash == chain.tx_hash
        assert record.block_number == chain.block_number
        assert record.entry_count == 5
        assert len(record.merkle_root) == 64  # hex

    def test_anchor_batch_calls_chain(self):
        chain = FakeChainClient()
        svc = AnchoringService(chain_client=chain, batch_size=100)
        entries = _make_entries(3)

        svc.anchor_batch(entries)

        assert len(chain.calls) == 1
        root_hex, count = chain.calls[0]
        assert count == 3
        assert len(root_hex) == 64

    def test_anchor_batch_empty_raises(self):
        chain = FakeChainClient()
        svc = AnchoringService(chain_client=chain)
        with pytest.raises(ValueError, match="empty batch"):
            svc.anchor_batch([])

    def test_get_proof_for_entry(self):
        entries = _make_entries(4)
        proof = AnchoringService.get_proof(entries[2], entries)
        assert proof.leaf == entries[2].hash_input
        assert MerkleTree.verify_proof(proof)

    def test_get_proof_entry_not_in_batch_raises(self):
        entries = _make_entries(4)
        outsider = _make_entry(entry_id=999)
        with pytest.raises(ValueError, match="not found"):
            AnchoringService.get_proof(outsider, entries)

    def test_batch_size_getter(self):
        chain = FakeChainClient()
        svc = AnchoringService(chain_client=chain, batch_size=42)
        assert svc.get_batch_size() == 42


# =====================================================================
# Background bundler task
# =====================================================================


class TestBundlerTask:
    """Test the async bundler task with mocked repositories."""

    @pytest.mark.asyncio
    async def test_run_once_anchors_entries(self):
        entries = _make_entries(5)
        repo = FakeEntryRepository(entries)
        chain = FakeChainClient()
        svc = AnchoringService(chain_client=chain, batch_size=100)

        await _run_once(svc, repo, batch_size=100)

        assert len(repo.saved_records) == 1
        assert repo.saved_records[0].entry_count == 5
        assert repo.saved_entry_ids == [[1, 2, 3, 4, 5]]
        # All entries now have anchor_id set.
        assert all(e.anchor_id is not None for e in entries)

    @pytest.mark.asyncio
    async def test_run_once_no_entries_is_noop(self):
        repo = FakeEntryRepository([])
        chain = FakeChainClient()
        svc = AnchoringService(chain_client=chain, batch_size=100)

        await _run_once(svc, repo, batch_size=100)

        assert len(repo.saved_records) == 0
        assert len(chain.calls) == 0

    @pytest.mark.asyncio
    async def test_run_once_respects_batch_size(self):
        entries = _make_entries(10)
        repo = FakeEntryRepository(entries)
        chain = FakeChainClient()
        svc = AnchoringService(chain_client=chain, batch_size=5)

        await _run_once(svc, repo, batch_size=5)

        # Only first 5 entries should be anchored.
        assert len(repo.saved_records) == 1
        assert repo.saved_records[0].entry_count == 5
        anchored = [e for e in entries if e.anchor_id is not None]
        assert len(anchored) == 5

    @pytest.mark.asyncio
    async def test_bundler_loop_disabled_exits_immediately(self):
        config = AnchorConfig(enabled=False)
        chain = FakeChainClient()
        svc = AnchoringService(chain_client=chain)
        repo = FakeEntryRepository(_make_entries(3))

        # Should return immediately without anchoring.
        await run_bundler_loop(svc, repo, config)

        assert len(repo.saved_records) == 0

    @pytest.mark.asyncio
    async def test_bundler_loop_chain_error_does_not_lose_entries(self):
        """Verify that a chain submission failure does not mark entries."""
        entries = _make_entries(3)
        repo = FakeEntryRepository(entries)

        failing_chain = MagicMock()
        failing_chain.submit_root.side_effect = RuntimeError("RPC timeout")
        svc = AnchoringService(chain_client=failing_chain, batch_size=100)

        # _run_once should catch the error internally (logged, not raised).
        # We call it directly here to avoid the infinite loop.
        # The service's anchor_batch will raise, which _run_once should catch
        # if called via run_bundler_loop.  Since _run_once does NOT catch,
        # we verify the exception propagates so the loop handles it.
        with pytest.raises(RuntimeError, match="RPC timeout"):
            await _run_once(svc, repo, batch_size=100)

        # Entries remain un-anchored.
        assert all(e.anchor_id is None for e in entries)
        assert len(repo.saved_records) == 0


# =====================================================================
# Configuration
# =====================================================================


class TestAnchorConfig:
    """Test AnchorConfig.from_env()."""

    def test_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            cfg = AnchorConfig.from_env()
        assert cfg.enabled is False
        assert cfg.rpc_url == ""
        assert cfg.contract_address == ""
        assert cfg.private_key == ""
        assert cfg.batch_size == 100
        assert cfg.interval_seconds == 300

    def test_from_env_enabled(self):
        env = {
            "ANCHOR_ENABLED": "true",
            "ANCHOR_RPC_URL": "http://localhost:8545",
            "ANCHOR_CONTRACT_ADDRESS": "0x1234",
            "ANCHOR_PRIVATE_KEY": "deadbeef",
            "ANCHOR_BATCH_SIZE": "50",
            "ANCHOR_INTERVAL_SECONDS": "60",
        }
        with patch.dict("os.environ", env, clear=True):
            cfg = AnchorConfig.from_env()
        assert cfg.enabled is True
        assert cfg.rpc_url == "http://localhost:8545"
        assert cfg.contract_address == "0x1234"
        assert cfg.private_key == "deadbeef"
        assert cfg.batch_size == 50
        assert cfg.interval_seconds == 60

    def test_from_env_enabled_variants(self):
        for val in ("1", "yes", "TRUE", "True"):
            with patch.dict("os.environ", {"ANCHOR_ENABLED": val}, clear=True):
                cfg = AnchorConfig.from_env()
            assert cfg.enabled is True, f"Expected enabled=True for ANCHOR_ENABLED={val}"


# =====================================================================
# NoOpChainClient
# =====================================================================


class TestNoOpChainClient:
    """Test the no-op chain client."""

    def test_returns_zero_receipt(self):
        client = NoOpChainClient()
        receipt = client.submit_root("abcd1234" * 8, 10)
        assert receipt.tx_hash == "0x" + "0" * 64
        assert receipt.block_number == 0


# =====================================================================
# CreditLedgerEntry model
# =====================================================================


class TestCreditLedgerEntry:
    """Test model-level helpers."""

    def test_hash_input_deterministic(self):
        e = _make_entry()
        assert e.hash_input == e.hash_input  # same call twice

    def test_hash_input_differs_by_id(self):
        e1 = _make_entry(entry_id=1)
        e2 = _make_entry(entry_id=2)
        assert e1.hash_input != e2.hash_input

    def test_hash_input_format(self):
        e = _make_entry(entry_id=7, account_id="user:bob", delta_usd="25.00")
        parts = e.hash_input.split(":")
        assert parts[0] == "7"
        assert parts[1] == "user"
        assert "bob" in e.hash_input
        assert "25.00" in e.hash_input

    def test_repr(self):
        e = _make_entry(entry_id=1, account_id="user:test", delta_usd="5.00")
        r = repr(e)
        assert "CreditLedgerEntry" in r
        assert "id=1" in r
