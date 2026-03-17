# Blockchain Anchoring

**Parent**: [RenderTrust System Documentation](00-system-documentation-home.md)

---

## Overview

RenderTrust anchors credit ledger entries on-chain using Merkle trees, providing tamper-evident auditability. Batches of ledger entries are hashed into a Merkle tree, and the root is submitted to the LedgerAnchor smart contract on Ethereum/L2. Users can verify any ledger entry's inclusion via Merkle proofs.

---

## How It Works

```
                Credit Ledger Entries
                ┌───┬───┬───┬───┐
                │ A │ B │ C │ D │    (batch of entries)
                └─┬─┴─┬─┴─┬─┴─┬─┘
                  │   │   │   │
                  ▼   ▼   ▼   ▼
                ┌───────┐ ┌───────┐
                │H(A,B) │ │H(C,D) │   (internal nodes)
                └───┬───┘ └───┬───┘
                    │         │
                    ▼         ▼
                ┌─────────────┐
                │  Merkle Root │        (single hash)
                └──────┬──────┘
                       │
                       ▼
              ┌────────────────┐
              │ LedgerAnchor   │
              │ Smart Contract │       (on-chain)
              │ anchorRoot()   │
              └────────────────┘
```

---

## Merkle Tree Implementation

### Hash Function

SHA-256 is used for all hashing:

```python
# core/ledger/anchor/merkle.py
def _hash_leaf(entry: CreditLedgerEntry) -> bytes:
    input_str = f"{entry.id}:{entry.account_id}:{entry.delta_usd}:{entry.created_at}"
    return hashlib.sha256(input_str.encode()).digest()

def _hash_pair(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(left + right).digest()
```

### Tree Construction

```python
class MerkleTree:
    def __init__(self, entries: list[CreditLedgerEntry]):
        # 1. Hash each entry to create leaves
        # 2. If odd number of leaves, duplicate last leaf
        # 3. Build tree bottom-up by hashing pairs
        # 4. Root = top-level hash

    @property
    def root(self) -> bytes:  # 32-byte SHA-256 hash

    def get_proof(self, leaf_index: int) -> MerkleProof:
        # Returns sibling hashes + directions needed to reconstruct root
```

### Merkle Proof Structure

```python
@dataclass
class MerkleProof:
    proof_hashes: list[str]    # Hex-encoded sibling hashes
    directions: list[str]      # "left" or "right" for each sibling
```

**Verification**: Given a leaf hash and its proof, reconstruct the root by hashing pairs in order. If the reconstructed root matches the on-chain root, the entry is verified.

---

## Anchoring Service

### Bundle & Anchor

```python
# core/ledger/anchor/service.py
class AnchoringService:
    def __init__(self, chain_client, batch_size=100):
        ...

    async def bundle_and_anchor(self, entries: list[CreditLedgerEntry]) -> AnchorRecord:
        # 1. Build Merkle tree from entries
        # 2. Submit root to chain: chain_client.submit_root(root_hex)
        # 3. Create AnchorRecord in database
        # 4. Link entries to anchor (set anchor_id FK)
        # 5. Return AnchorRecord with tx_hash, block_number
```

### Background Bundler Task

The bundler runs periodically (e.g., every hour) to batch unanchored ledger entries:

```python
# core/ledger/anchor/bundler.py
async def bundler_task(interval_seconds=3600):
    while True:
        # 1. Query unanchored entries (anchor_id IS NULL)
        # 2. If count >= batch_size, bundle and anchor
        # 3. Sleep for interval
```

---

## Chain Client

### Interface

```python
class ChainClient(ABC):
    @abstractmethod
    async def submit_root(self, merkle_root: str) -> SubmitResult:
        # Returns: { tx_hash, block_number }

    @abstractmethod
    def verify_root(self, tx_hash: str, merkle_root: str) -> VerificationResult:
        # Returns: { verified, on_chain_root }
```

### Implementations

| Client | Usage | Description |
|--------|-------|-------------|
| `Web3ChainClient` | Production | Submits to LedgerAnchor.sol via Web3.py |
| `NoOpChainClient` | Development | Returns mock tx_hash, no actual chain interaction |

---

## Smart Contract

### LedgerAnchor.sol

```solidity
// rollup_anchor/contracts/LedgerAnchor.sol
// SPDX-License-Identifier: MIT
// Solidity ^0.8.20

contract LedgerAnchor {
    uint256 public lastBatch;
    mapping(uint256 => bytes32) public batchRoots;
    mapping(uint256 => uint256) public batchSizes;
    mapping(uint256 => uint256) public batchTimestamps;

    function anchorRoot(bytes32 root, uint256 entryCount) external {
        lastBatch++;
        batchRoots[lastBatch] = root;
        batchSizes[lastBatch] = entryCount;
        batchTimestamps[lastBatch] = block.timestamp;
    }

    function verifyProof(
        uint256 batchId,
        bytes32[] calldata proof,
        bytes32 leaf
    ) external view returns (bool) {
        bytes32 computedHash = leaf;
        for (uint256 i = 0; i < proof.length; i++) {
            computedHash = keccak256(abi.encodePacked(computedHash, proof[i]));
        }
        return computedHash == batchRoots[batchId];
    }

    function getBatchInfo(uint256 batchId)
        external view returns (bytes32 root, uint256 entryCount, uint256 timestamp)
    {
        return (batchRoots[batchId], batchSizes[batchId], batchTimestamps[batchId]);
    }
}
```

### Development with Hardhat

```bash
cd rollup_anchor/
npm install
npx hardhat compile
npx hardhat test
npx hardhat deploy --network localhost
```

---

## Proof Verification API

### GET /api/v1/ledger/{entry_id}/proof

Returns the Merkle proof for a specific ledger entry.

**Response:**
```json
{
  "entry_id": 42,
  "merkle_root": "a1b2c3d4...",
  "proof_hashes": ["e5f6a7b8...", "c9d0e1f2..."],
  "directions": ["left", "right"],
  "anchor_tx_hash": "0xabc...",
  "block_number": 12345
}
```

**Errors:**
- `404` — Entry not found or not yet anchored

### GET /api/v1/ledger/{entry_id}/verify

Verifies a ledger entry's Merkle proof against the on-chain root.

**Response:**
```json
{
  "verified": true,
  "entry_id": 42,
  "merkle_root": "a1b2c3d4...",
  "on_chain_root": "a1b2c3d4...",
  "block_number": 12345,
  "tx_hash": "0xabc..."
}
```

### GET /api/v1/ledger/anchors

Lists all anchor records with pagination.

**Query Parameters:**
- `page` (>=1, default 1)
- `per_page` (1-100, default 20)
- `since` (ISO 8601, optional filter)

**Response:**
```json
{
  "anchors": [
    {
      "id": "uuid",
      "merkle_root": "a1b2c3d4...",
      "tx_hash": "0xabc...",
      "block_number": 12345,
      "entry_count": 100,
      "anchored_at": "2026-03-13T12:00:00Z"
    }
  ],
  "count": 5,
  "page": 1,
  "per_page": 20
}
```

---

## Verification Workflow (User Perspective)

```
1. User views credit history
2. Clicks "Verify" on a transaction
3. App calls GET /api/v1/ledger/{entry_id}/verify
4. Gateway:
   a. Finds entry's anchor record (tx_hash, merkle_root)
   b. Rebuilds Merkle proof from batch entries
   c. Calls chain_client.verify_root(tx_hash, merkle_root)
   d. Compares on-chain root with computed root
5. Returns { verified: true/false }
6. User sees "Verified on-chain" badge
```

---

*MIT License | Copyright (c) 2026 ByBren, LLC*
