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
Blockchain interaction layer for the anchoring service.

The :class:`ChainClient` protocol defines the interface used by the
anchoring service to submit Merkle roots on-chain.  The default
:class:`Web3ChainClient` uses ``web3.py`` for Ethereum interaction,
while :class:`NoOpChainClient` can be used in tests or when anchoring
is disabled.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from core.ledger.anchor.config import AnchorConfig

logger = logging.getLogger(__name__)

# Path to the ABI file shipped with the rollup_anchor package.
_ABI_PATH = Path(__file__).parent.parent.parent.parent / "rollup_anchor" / "LedgerAnchor.abi.json"


@dataclass(frozen=True)
class ChainReceipt:
    """Minimal receipt returned after a successful on-chain submission."""

    tx_hash: str
    block_number: int


@dataclass(frozen=True)
class ChainVerification:
    """Result of verifying a Merkle root against on-chain data."""

    verified: bool
    on_chain_root: str


class ChainClient(Protocol):
    """Protocol for submitting and verifying Merkle roots on the blockchain."""

    def submit_root(self, merkle_root_hex: str, entry_count: int) -> ChainReceipt:
        """Submit *merkle_root_hex* for *entry_count* entries.

        Returns a :class:`ChainReceipt` on success, or raises on failure.
        """
        ...

    def verify_root(self, tx_hash: str, expected_root_hex: str) -> ChainVerification:
        """Verify that *expected_root_hex* matches the root stored on-chain for *tx_hash*.

        Returns a :class:`ChainVerification` with the comparison result.
        """
        ...


class Web3ChainClient:
    """Production chain client backed by ``web3.py``.

    This implementation calls ``anchorRoot(bytes32, uint256)`` on the
    deployed ``LedgerAnchor`` contract.
    """

    def __init__(self, config: AnchorConfig) -> None:
        # Import web3 lazily so the rest of the package works without it.
        from web3 import Web3  # type: ignore[import-untyped]

        self._w3 = Web3(Web3.HTTPProvider(config.rpc_url))
        self._account = self._w3.eth.account.from_key(config.private_key)

        abi_path = _ABI_PATH
        if not abi_path.is_file():
            raise FileNotFoundError(f"LedgerAnchor ABI not found at {abi_path}")
        with abi_path.open() as fh:
            abi = json.load(fh)

        self._contract = self._w3.eth.contract(address=config.contract_address, abi=abi)

    def submit_root(self, merkle_root_hex: str, entry_count: int) -> ChainReceipt:
        """Build, sign, and send an ``anchorRoot`` transaction."""
        from web3 import Web3  # type: ignore[import-untyped]

        root_bytes = Web3.to_bytes(hexstr=merkle_root_hex)
        # Pad to 32 bytes if necessary.
        root_bytes = root_bytes.rjust(32, b"\x00")

        tx = self._contract.functions.anchorRoot(root_bytes, entry_count).build_transaction(
            {
                "from": self._account.address,
                "nonce": self._w3.eth.get_transaction_count(self._account.address),
                "gas": 200_000,
                "gasPrice": self._w3.eth.gas_price,
            }
        )

        signed = self._w3.eth.account.sign_transaction(tx, self._account.key)
        tx_hash = self._w3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash)

        return ChainReceipt(
            tx_hash=receipt.transactionHash.hex(),
            block_number=receipt.blockNumber,
        )

    def verify_root(self, tx_hash: str, expected_root_hex: str) -> ChainVerification:
        """Read the anchored root from the transaction and compare."""
        from web3 import Web3  # type: ignore[import-untyped]

        tx_receipt = self._w3.eth.get_transaction_receipt(tx_hash)
        # Decode the anchorRoot event log to extract the stored root.
        logs = self._contract.events.RootAnchored().process_receipt(tx_receipt)
        if not logs:
            return ChainVerification(verified=False, on_chain_root="")

        on_chain_root = Web3.to_hex(logs[0]["args"]["merkleRoot"])[2:]  # strip 0x
        return ChainVerification(
            verified=on_chain_root == expected_root_hex,
            on_chain_root=on_chain_root,
        )


class NoOpChainClient:
    """Chain client that does nothing -- useful for tests and dry runs."""

    def submit_root(self, merkle_root_hex: str, entry_count: int) -> ChainReceipt:
        logger.info(
            "NoOpChainClient.submit_root called (root=%s, count=%d) -- skipping",
            merkle_root_hex[:16],
            entry_count,
        )
        return ChainReceipt(
            tx_hash="0x" + "0" * 64,
            block_number=0,
        )

    def verify_root(self, tx_hash: str, expected_root_hex: str) -> ChainVerification:
        logger.info(
            "NoOpChainClient.verify_root called (tx=%s, root=%s) -- returning verified=True",
            tx_hash[:16],
            expected_root_hex[:16],
        )
        return ChainVerification(
            verified=True,
            on_chain_root=expected_root_hex,
        )
