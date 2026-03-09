#!/usr/bin/env python3
"""
RenderTrust Ledger Bundler

This script bundles ledger entries into Merkle trees and anchors them to the blockchain.
It processes unanchored entries from the database, creates a Merkle tree, and submits
the root to the LedgerAnchor smart contract.
"""

import hashlib
import json
import os
import time
from typing import Any

import psycopg2
from web3 import Web3

# Configuration from environment variables
PG_DSN = os.environ.get("PG_DSN", "postgresql://localhost/rendertrust")
CONTRACT_ADDRESS = os.environ.get("CONTRACT", "0x5FbDB2315678afecb367f032d93F642f64180aa3")
RPC_URL = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
PRIVATE_KEY = os.environ.get("PRIVATE_KEY", "")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "200"))

# Load ABI
with open("LedgerAnchor.abi.json") as f:
    CONTRACT_ABI = json.load(f)

class MerkleTree:
    """Simple Merkle tree implementation for ledger entries"""

    def __init__(self, leaves: list[str]):
        self.leaves = [self._hash_leaf(leaf) for leaf in leaves]
        self.tree = self._build_tree()

    def _hash_leaf(self, leaf: str) -> str:
        """Hash a leaf node"""
        return hashlib.sha256(leaf.encode()).hexdigest()

    def _hash_pair(self, left: str, right: str) -> str:
        """Hash a pair of nodes"""
        combined = left + right
        return hashlib.sha256(combined.encode()).hexdigest()

    def _build_tree(self) -> list[list[str]]:
        """Build the Merkle tree from leaves"""
        tree = [self.leaves]
        level = self.leaves

        # Continue until we reach the root
        while len(level) > 1:
            next_level = []
            # Process pairs of nodes
            for i in range(0, len(level), 2):
                if i + 1 < len(level):
                    next_level.append(self._hash_pair(level[i], level[i+1]))
                else:
                    # Odd number of nodes, duplicate the last one
                    next_level.append(level[i])

            tree.append(next_level)
            level = next_level

        return tree

    def get_root(self) -> str:
        """Get the Merkle root"""
        if not self.tree or not self.tree[-1]:
            return ""
        return self.tree[-1][0]

    def get_proof(self, leaf_index: int) -> list[str]:
        """Generate a Merkle proof for a leaf"""
        if leaf_index < 0 or leaf_index >= len(self.leaves):
            return []

        proof = []
        for level_idx, level in enumerate(self.tree[:-1]):  # Skip the root level
            is_right = leaf_index % 2 == 1
            pair_idx = leaf_index - 1 if is_right else leaf_index + 1

            if pair_idx < len(level):
                proof.append(level[pair_idx])

            # Move to the parent node for the next level
            leaf_index = leaf_index // 2

        return proof

def get_unanchored_entries() -> list[dict[str, Any]]:
    """Fetch unanchored entries from the database"""
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, sha256 FROM ledger_entries WHERE anchored = FALSE ORDER BY id LIMIT %s",
                (BATCH_SIZE,)
            )
            entries = [{"id": row[0], "sha256": row[1]} for row in cur.fetchall()]
        return entries
    finally:
        conn.close()

def update_anchored_entries(entry_ids: list[int], tx_hash: str) -> None:
    """Mark entries as anchored in the database"""
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ledger_entries SET anchored = TRUE, anchor_tx = %s WHERE id = ANY(%s)",
                (tx_hash, entry_ids)
            )
            conn.commit()
    finally:
        conn.close()

def anchor_to_blockchain(merkle_root: str, entry_count: int) -> str:
    """Anchor the Merkle root to the blockchain"""
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    account = w3.eth.account.from_key(PRIVATE_KEY)

    # Create contract instance
    contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

    # Prepare transaction
    tx = contract.functions.anchorRoot(
        Web3.to_bytes(hexstr=merkle_root),
        entry_count
    ).build_transaction({
        'from': account.address,
        'nonce': w3.eth.get_transaction_count(account.address),
        'gas': 200000,
        'gasPrice': w3.eth.gas_price
    })

    # Sign and send transaction
    signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)

    # Wait for transaction receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

    return receipt.transactionHash.hex()

def main():
    """Main bundler process"""
    while True:
        # Get unanchored entries
        entries = get_unanchored_entries()

        if not entries:
            print("No unanchored entries found. Sleeping...")
            time.sleep(60)
            continue

        # Create Merkle tree
        merkle_tree = MerkleTree([entry["sha256"] for entry in entries])
        merkle_root = merkle_tree.get_root()

        # Anchor to blockchain
        try:
            tx_hash = anchor_to_blockchain(merkle_root, len(entries))

            # Update database
            entry_ids = [entry["id"] for entry in entries]
            update_anchored_entries(entry_ids, tx_hash)

            print(f"Anchored batch of {len(entries)} entries. Root: {merkle_root}, TX: {tx_hash}")
        except Exception as e:
            print(f"Error anchoring to blockchain: {e}")

        # Sleep before next batch
        time.sleep(300)  # 5 minutes

if __name__ == "__main__":
    main()
