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

"""Core domain models for RenderTrust.

Defines the foundational User, Project, and CreditLedgerEntry models.
All models use UUID primary keys and include created_at/updated_at timestamps.
"""

import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import BaseModel


class User(BaseModel):
    """User account model.

    Attributes:
        email: Unique email address (used for login).
        name: Display name.
        hashed_password: Bcrypt-hashed password. Never store or log plaintext.
        is_active: Whether the user account is enabled.
        is_admin: Whether the user has administrator privileges.
        projects: Relationship to owned projects.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    projects: Mapped[list["Project"]] = relationship(
        "Project",
        back_populates="owner",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email})>"


class Project(BaseModel):
    """Project model representing a computational trust project.

    Attributes:
        name: Project display name.
        description: Optional project description.
        owner_id: FK to the owning User.
        owner: Relationship to the User who owns this project.
    """

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    owner: Mapped["User"] = relationship(
        "User",
        back_populates="projects",
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name})>"


class TransactionDirection(enum.Enum):
    """Direction of a credit ledger transaction."""

    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class TransactionSource(enum.Enum):
    """Source/reason for a credit ledger transaction."""

    STRIPE = "STRIPE"
    USAGE = "USAGE"
    ADJUSTMENT = "ADJUSTMENT"
    REFUND = "REFUND"


class CreditLedgerEntry(BaseModel):
    """Credit ledger entry tracking user credit transactions.

    Implements double-entry style tracking with idempotency via
    UNIQUE(reference_id, direction) constraint.

    Attributes:
        user_id: FK to the owning User.
        amount: Transaction amount (positive value).
        direction: CREDIT or DEBIT.
        source: Origin of the transaction (STRIPE, USAGE, ADJUSTMENT, REFUND).
        reference_id: External reference for idempotency (e.g. Stripe charge ID).
        balance_after: User's credit balance after this transaction.
        description: Optional human-readable description.
        user: Relationship to the User who owns this entry.
    """

    __tablename__ = "credit_ledger_entries"
    __table_args__ = (
        UniqueConstraint(
            "reference_id",
            "direction",
            name="uq_ledger_reference_direction",
        ),
        CheckConstraint(
            "balance_after >= 0",
            name="ck_ledger_balance_non_negative",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
    )
    direction: Mapped[TransactionDirection] = mapped_column(
        Enum(TransactionDirection, name="transaction_direction"),
        nullable=False,
    )
    source: Mapped[TransactionSource] = mapped_column(
        Enum(TransactionSource, name="transaction_source"),
        nullable=False,
    )
    reference_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    user: Mapped["User"] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<CreditLedgerEntry(id={self.id}, user_id={self.user_id}, "
            f"amount={self.amount}, direction={self.direction.value})>"
        )
