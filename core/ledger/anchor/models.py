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
SQLAlchemy models for blockchain anchoring.

Extends the existing ``ledger_entries`` table with an ``anchor_id`` foreign
key and introduces the ``anchor_records`` table to store on-chain transaction
metadata.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for anchor models.

    In production this should be replaced with the project-wide ``Base``
    from the shared ``db`` module so that all models share a single
    metadata instance.  It is defined here to keep the anchor package
    self-contained for initial development and testing.
    """

    pass


class AnchorRecord(Base):
    """Represents a single on-chain anchoring transaction.

    Each record stores the Merkle root that was submitted to the
    ``LedgerAnchor`` smart contract, along with the resulting
    transaction hash and block number.
    """

    __tablename__ = "anchor_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    merkle_root: Mapped[str] = mapped_column(
        String(66),  # 64 hex chars + optional "0x" prefix
        nullable=False,
        index=True,
        comment="Hex-encoded SHA-256 Merkle root submitted to chain",
    )
    tx_hash: Mapped[str] = mapped_column(
        String(66),
        nullable=False,
        unique=True,
        comment="Ethereum transaction hash (0x-prefixed)",
    )
    block_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Block in which the anchor transaction was mined",
    )
    entry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Number of ledger entries included in this anchor batch",
    )
    anchored_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.datetime.now,
        comment="Timestamp when the anchor was recorded",
    )

    # Relationship back to ledger entries (one-to-many)
    entries: Mapped[list[CreditLedgerEntry]] = relationship(
        "CreditLedgerEntry",
        back_populates="anchor_record",
    )

    def __repr__(self) -> str:
        return f"<AnchorRecord id={self.id!s} tx_hash={self.tx_hash!r} entries={self.entry_count}>"


class CreditLedgerEntry(Base):
    """Lightweight mirror of the existing ``ledger_entries`` table.

    Only the columns required by the anchoring service are declared here.
    In production, the ``anchor_id`` column and relationship should be
    added to the canonical ``Ledger`` / ``CreditLedgerEntry`` model in the
    billing module rather than maintained as a separate model.
    """

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.datetime.now,
    )
    account_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    delta_usd: Mapped[str] = mapped_column(
        # Stored as NUMERIC in Postgres; mapped to str to avoid float issues.
        Text,
        nullable=False,
    )
    ref_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    # ----- NEW: anchor linkage -----
    anchor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("anchor_records.id"),
        nullable=True,
        index=True,
        comment="FK to the anchor batch that includes this entry",
    )

    anchor_record: Mapped[AnchorRecord | None] = relationship(
        "AnchorRecord",
        back_populates="entries",
    )

    # Convenience property used by the Merkle tree to compute the leaf hash.
    @property
    def hash_input(self) -> str:
        """Deterministic string representation used as Merkle leaf input."""
        return (
            f"{self.id}:"
            f"{self.account_id}:"
            f"{self.delta_usd}:"
            f"{self.created_at.isoformat() if self.created_at else ''}"
        )

    def __repr__(self) -> str:
        return (
            f"<CreditLedgerEntry id={self.id} account={self.account_id!r} delta={self.delta_usd}>"
        )
