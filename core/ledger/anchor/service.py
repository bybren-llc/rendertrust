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
High-level anchoring service.

``AnchoringService`` orchestrates:

1. Collecting un-anchored :class:`CreditLedgerEntry` rows.
2. Building a :class:`MerkleTree` from their deterministic hash inputs.
3. Submitting the Merkle root to the blockchain via a :class:`ChainClient`.
4. Recording the :class:`AnchorRecord` and linking entries back to it.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from core.ledger.anchor.merkle import MerkleProof, MerkleTree
from core.ledger.anchor.models import AnchorRecord, CreditLedgerEntry

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.ledger.anchor.chain import ChainClient, ChainReceipt

logger = logging.getLogger(__name__)


class AnchoringService:
    """Batch-anchoring service for credit-ledger entries.

    Parameters:
        chain_client: An object implementing :class:`ChainClient` to
            submit Merkle roots on-chain.
        batch_size: Maximum number of entries per anchor batch.
    """

    def __init__(
        self,
        chain_client: ChainClient,
        batch_size: int = 100,
    ) -> None:
        self._chain = chain_client
        self._batch_size = batch_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def create_merkle_root(entries: Sequence[CreditLedgerEntry]) -> bytes:
        """Compute the SHA-256 Merkle root for a list of entries.

        Returns:
            The raw 32-byte Merkle root.

        Raises:
            ValueError: If *entries* is empty.
        """
        if not entries:
            raise ValueError("Cannot compute a Merkle root from zero entries")
        leaves = [entry.hash_input for entry in entries]
        tree = MerkleTree(leaves)
        return tree.root

    def anchor_batch(
        self,
        entries: Sequence[CreditLedgerEntry],
    ) -> AnchorRecord:
        """Submit a batch of entries to the blockchain and return the anchor.

        Steps:
            1. Build a Merkle tree from *entries*.
            2. Submit the root via :attr:`_chain`.
            3. Create and return an :class:`AnchorRecord`.

        The caller is responsible for persisting the ``AnchorRecord`` and
        updating each entry's ``anchor_id`` within a database transaction.

        Raises:
            ValueError: If *entries* is empty.
            Exception: Any error from the chain client is propagated.
        """
        if not entries:
            raise ValueError("Cannot anchor an empty batch")

        leaves = [entry.hash_input for entry in entries]
        tree = MerkleTree(leaves)

        receipt: ChainReceipt = self._chain.submit_root(
            tree.root_hex, len(entries)
        )

        record = AnchorRecord(
            id=uuid.uuid4(),
            merkle_root=tree.root_hex,
            tx_hash=receipt.tx_hash,
            block_number=receipt.block_number,
            entry_count=len(entries),
        )

        logger.info(
            "Anchored batch of %d entries. root=%s tx=%s block=%d",
            len(entries),
            tree.root_hex[:16] + "...",
            receipt.tx_hash,
            receipt.block_number,
        )

        return record

    @staticmethod
    def get_proof(
        entry: CreditLedgerEntry,
        all_entries: Sequence[CreditLedgerEntry],
    ) -> MerkleProof:
        """Generate an inclusion proof for *entry* within *all_entries*.

        Parameters:
            entry: The specific entry to prove inclusion for.
            all_entries: The full ordered list of entries from the same
                anchor batch.

        Returns:
            A :class:`MerkleProof` that can be independently verified.

        Raises:
            ValueError: If *entry* is not found in *all_entries*.
        """
        leaves = [e.hash_input for e in all_entries]

        try:
            index = next(
                i for i, e in enumerate(all_entries) if e.id == entry.id
            )
        except StopIteration:
            raise ValueError(
                f"Entry id={entry.id} not found in the provided batch"
            ) from None

        tree = MerkleTree(leaves)
        return tree.get_proof(index)

    def get_batch_size(self) -> int:
        """Return the configured maximum batch size."""
        return self._batch_size
