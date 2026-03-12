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

"""Proof verification and anchor listing API endpoints (REN-132).

Provides endpoints for:
- Retrieving Merkle inclusion proofs for anchored ledger entries
- Verifying proofs against on-chain data
- Listing anchor records with pagination
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.auth.jwt import get_current_user
from core.database import get_db_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from core.models.base import User

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class MerkleProofResponse(BaseModel):
    """Merkle inclusion proof for a single ledger entry."""

    entry_id: int
    merkle_root: str
    proof_hashes: list[str]
    directions: list[str]
    anchor_tx_hash: str
    block_number: int


class VerificationResponse(BaseModel):
    """Result of verifying a Merkle proof against on-chain data."""

    verified: bool
    entry_id: int
    merkle_root: str
    on_chain_root: str
    block_number: int
    tx_hash: str


class AnchorRecordResponse(BaseModel):
    """Summary of a single anchor record."""

    id: str
    merkle_root: str
    tx_hash: str
    block_number: int
    entry_count: int
    anchored_at: str


class AnchorListResponse(BaseModel):
    """Paginated list of anchor records."""

    anchors: list[AnchorRecordResponse]
    count: int
    page: int
    per_page: int


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/ledger")


# ---------------------------------------------------------------------------
# Dependency: AnchoringService + ChainClient
# ---------------------------------------------------------------------------


def _get_anchoring_deps():
    """Build the anchoring service and chain client for dependency injection.

    Returns a tuple of (AnchoringService, ChainClient).
    In production, this reads from AnchorConfig; in tests it can be
    overridden via FastAPI dependency_overrides.
    """
    from core.ledger.anchor.chain import NoOpChainClient
    from core.ledger.anchor.config import AnchorConfig
    from core.ledger.anchor.service import AnchoringService

    config = AnchorConfig.from_env()

    if config.enabled and config.rpc_url:
        from core.ledger.anchor.chain import Web3ChainClient

        chain_client = Web3ChainClient(config)
    else:
        chain_client = NoOpChainClient()

    service = AnchoringService(chain_client=chain_client, batch_size=config.batch_size)
    return service, chain_client


# ---------------------------------------------------------------------------
# GET /ledger/{entry_id}/proof
# ---------------------------------------------------------------------------


@router.get("/{entry_id}/proof", response_model=MerkleProofResponse)
async def get_entry_proof(
    entry_id: int,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    session: AsyncSession = Depends(get_db_session),
) -> MerkleProofResponse:
    """Return the Merkle inclusion proof for a ledger entry.

    The entry must have been anchored (i.e., included in an anchor batch).
    Returns 404 if the entry does not exist or has not yet been anchored.
    """
    from sqlalchemy import select

    from core.ledger.anchor.models import AnchorRecord, CreditLedgerEntry
    from core.ledger.anchor.service import AnchoringService

    # Fetch the target entry
    result = await session.execute(
        select(CreditLedgerEntry).where(CreditLedgerEntry.id == entry_id)
    )
    entry = result.scalar_one_or_none()

    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ledger entry not found",
        )

    if entry.anchor_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entry has not been anchored yet",
        )

    # Fetch the anchor record
    anchor_result = await session.execute(
        select(AnchorRecord).where(AnchorRecord.id == entry.anchor_id)
    )
    anchor = anchor_result.scalar_one_or_none()

    if anchor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Anchor record not found",
        )

    # Fetch all entries in the same anchor batch (ordered by id for determinism)
    batch_result = await session.execute(
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.anchor_id == anchor.id)
        .order_by(CreditLedgerEntry.id)
    )
    batch_entries = list(batch_result.scalars().all())

    # Generate the proof
    proof = AnchoringService.get_proof(entry, batch_entries)

    logger.info(
        "proof_generated",
        entry_id=entry_id,
        anchor_id=str(anchor.id),
        merkle_root=anchor.merkle_root[:16] + "...",
    )

    return MerkleProofResponse(
        entry_id=entry_id,
        merkle_root=anchor.merkle_root,
        proof_hashes=[h.hex() for h in proof.proof_hashes],
        directions=[d.value for d in proof.directions],
        anchor_tx_hash=anchor.tx_hash,
        block_number=anchor.block_number,
    )


# ---------------------------------------------------------------------------
# GET /ledger/{entry_id}/verify
# ---------------------------------------------------------------------------


@router.get("/{entry_id}/verify", response_model=VerificationResponse)
async def verify_entry_proof(
    entry_id: int,
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    session: AsyncSession = Depends(get_db_session),
    deps: tuple = Depends(_get_anchoring_deps),
) -> VerificationResponse:
    """Verify that a ledger entry's Merkle proof matches on-chain data.

    Calls the blockchain to retrieve the anchored root and compares it
    against the locally stored Merkle root. Returns 404 if the entry
    does not exist or has not been anchored.
    """
    from sqlalchemy import select

    from core.ledger.anchor.models import AnchorRecord, CreditLedgerEntry

    _, chain_client = deps

    # Fetch the target entry
    result = await session.execute(
        select(CreditLedgerEntry).where(CreditLedgerEntry.id == entry_id)
    )
    entry = result.scalar_one_or_none()

    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ledger entry not found",
        )

    if entry.anchor_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entry has not been anchored yet",
        )

    # Fetch the anchor record
    anchor_result = await session.execute(
        select(AnchorRecord).where(AnchorRecord.id == entry.anchor_id)
    )
    anchor = anchor_result.scalar_one_or_none()

    if anchor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Anchor record not found",
        )

    # Verify against chain
    verification = chain_client.verify_root(anchor.tx_hash, anchor.merkle_root)

    logger.info(
        "proof_verified",
        entry_id=entry_id,
        verified=verification.verified,
        tx_hash=anchor.tx_hash,
    )

    return VerificationResponse(
        verified=verification.verified,
        entry_id=entry_id,
        merkle_root=anchor.merkle_root,
        on_chain_root=verification.on_chain_root,
        block_number=anchor.block_number,
        tx_hash=anchor.tx_hash,
    )


# ---------------------------------------------------------------------------
# GET /ledger/anchors
# ---------------------------------------------------------------------------


@router.get("/anchors", response_model=AnchorListResponse)
async def list_anchors(
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=20, ge=1, le=100, description="Items per page"),
    since: str | None = Query(
        default=None,
        description="ISO 8601 date filter (returns anchors from this date onwards)",
    ),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
    session: AsyncSession = Depends(get_db_session),
) -> AnchorListResponse:
    """List anchor records with pagination and optional date filtering.

    Returns a paginated list of anchor record summaries ordered by
    anchored_at descending (most recent first).
    """
    from sqlalchemy import select

    from core.ledger.anchor.models import AnchorRecord

    # Build the base query
    query = select(AnchorRecord)

    # Apply date filter if provided
    if since is not None:
        try:
            since_dt = datetime.datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid ISO date format: {since}",
            ) from None
        query = query.where(AnchorRecord.anchored_at >= since_dt)

    # Order by most recent first
    query = query.order_by(AnchorRecord.anchored_at.desc())

    # Apply pagination
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await session.execute(query)
    anchors = list(result.scalars().all())

    anchor_responses = [
        AnchorRecordResponse(
            id=str(anchor.id),
            merkle_root=anchor.merkle_root,
            tx_hash=anchor.tx_hash,
            block_number=anchor.block_number,
            entry_count=anchor.entry_count,
            anchored_at=anchor.anchored_at.isoformat(),
        )
        for anchor in anchors
    ]

    logger.info(
        "anchors_listed",
        count=len(anchor_responses),
        page=page,
        per_page=per_page,
        since=since,
    )

    return AnchorListResponse(
        anchors=anchor_responses,
        count=len(anchor_responses),
        page=page,
        per_page=per_page,
    )
