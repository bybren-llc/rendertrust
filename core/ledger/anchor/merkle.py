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
Pure Python Merkle tree implementation using SHA-256.

This module provides a standalone Merkle tree with no external dependencies
beyond the Python standard library.  It is used by the anchoring service
to compute roots and generate inclusion proofs for credit-ledger entries.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if sys.version_info >= (3, 11):  # noqa: UP036
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]  # noqa: UP042
        """Polyfill for Python < 3.11."""


if TYPE_CHECKING:
    from collections.abc import Sequence


class Direction(StrEnum):
    """Sibling direction relative to the current node in a Merkle proof."""

    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class MerkleProof:
    """Inclusion proof for a single leaf in a Merkle tree.

    Attributes:
        leaf: The original (unhashed) leaf value.
        leaf_hash: SHA-256 hash of the leaf.
        proof_hashes: Sibling hashes along the path to the root.
        directions: Direction of each sibling (LEFT or RIGHT).
        root: The expected Merkle root.
    """

    leaf: str
    leaf_hash: bytes
    proof_hashes: list[bytes] = field(default_factory=list)
    directions: list[Direction] = field(default_factory=list)
    root: bytes = b""


class MerkleTree:
    """SHA-256 Merkle tree built from a list of string leaves.

    The tree is constructed bottom-up.  When a level has an odd number of
    nodes the last node is duplicated so that every node has a sibling.

    Usage::

        tree = MerkleTree(["a", "b", "c", "d"])
        root = tree.root
        proof = tree.get_proof(0)
        assert MerkleTree.verify_proof(proof)
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, leaves: Sequence[str]) -> None:
        if not leaves:
            raise ValueError("Cannot build a Merkle tree from an empty list")
        self._leaves: list[str] = list(leaves)
        self._hashed_leaves: list[bytes] = [self._hash_leaf(leaf) for leaf in self._leaves]
        self._levels: list[list[bytes]] = self._build()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def root(self) -> bytes:
        """Return the Merkle root (top-level hash)."""
        return self._levels[-1][0]

    @property
    def root_hex(self) -> str:
        """Return the Merkle root as a hex string."""
        return self.root.hex()

    @property
    def leaf_count(self) -> int:
        """Return the number of leaves."""
        return len(self._leaves)

    def get_proof(self, index: int) -> MerkleProof:
        """Generate an inclusion proof for the leaf at *index*.

        Raises:
            IndexError: If *index* is out of range.
        """
        if index < 0 or index >= len(self._hashed_leaves):
            raise IndexError(f"Leaf index {index} out of range [0, {len(self._hashed_leaves)})")

        proof_hashes: list[bytes] = []
        directions: list[Direction] = []
        current_index = index

        for level in self._levels[:-1]:  # skip root level
            if current_index % 2 == 0:
                # Current node is on the left; sibling is to the right.
                sibling_index = current_index + 1
                direction = Direction.RIGHT
            else:
                # Current node is on the right; sibling is to the left.
                sibling_index = current_index - 1
                direction = Direction.LEFT

            if sibling_index < len(level):
                proof_hashes.append(level[sibling_index])
                directions.append(direction)
            else:
                # Odd-length level: the last node is duplicated during
                # tree construction, so the sibling is the node itself.
                proof_hashes.append(level[current_index])
                directions.append(direction)

            current_index //= 2

        return MerkleProof(
            leaf=self._leaves[index],
            leaf_hash=self._hashed_leaves[index],
            proof_hashes=proof_hashes,
            directions=directions,
            root=self.root,
        )

    # ------------------------------------------------------------------
    # Static verification
    # ------------------------------------------------------------------

    @staticmethod
    def verify_proof(proof: MerkleProof) -> bool:
        """Return ``True`` if *proof* is a valid inclusion proof.

        This is a standalone function that does not require the full tree.
        """
        computed = proof.leaf_hash
        for sibling, direction in zip(proof.proof_hashes, proof.directions, strict=True):
            if direction == Direction.RIGHT:
                computed = MerkleTree._hash_pair(computed, sibling)
            else:
                computed = MerkleTree._hash_pair(sibling, computed)
        return computed == proof.root

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_leaf(data: str) -> bytes:
        """SHA-256 hash of a single leaf value."""
        return hashlib.sha256(data.encode("utf-8")).digest()

    @staticmethod
    def _hash_pair(left: bytes, right: bytes) -> bytes:
        """SHA-256 hash of two concatenated child hashes."""
        return hashlib.sha256(left + right).digest()

    def _build(self) -> list[list[bytes]]:
        """Build all tree levels from the hashed leaves up to the root."""
        levels: list[list[bytes]] = [list(self._hashed_leaves)]
        current = levels[0]

        while len(current) > 1:
            next_level: list[bytes] = []
            for i in range(0, len(current), 2):
                left = current[i]
                right = current[i + 1] if i + 1 < len(current) else current[i]
                next_level.append(self._hash_pair(left, right))
            levels.append(next_level)
            current = next_level

        return levels
