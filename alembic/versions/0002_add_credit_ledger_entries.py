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

"""Add credit_ledger_entries table.

Revision ID: 0002_credit_ledger
Revises: 0001_baseline
Create Date: 2026-03-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_credit_ledger"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# PostgreSQL native ENUM types
# create_type=False prevents SQLAlchemy from auto-creating the enum during
# create_table — we handle creation ourselves via _create_enum_if_not_exists
# to avoid "type already exists" errors with asyncpg.
transaction_direction = sa.Enum(
    "CREDIT",
    "DEBIT",
    name="transaction_direction",
    create_type=False,
)
transaction_source = sa.Enum(
    "STRIPE",
    "USAGE",
    "ADJUSTMENT",
    "REFUND",
    name="transaction_source",
    create_type=False,
)


def _create_enum_if_not_exists(name: str, values: Sequence[str]) -> None:
    """Create a PostgreSQL ENUM type only if it does not already exist.

    Works around SQLAlchemy Enum.create(checkfirst=True) failing with asyncpg,
    and PostgreSQL < 16.4 not supporting CREATE TYPE IF NOT EXISTS.
    """
    bind = op.get_bind()
    result = bind.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :name"),
        {"name": name},
    )
    if not result.scalar():
        vals = ", ".join(f"'{v}'" for v in values)
        bind.execute(sa.text(f"CREATE TYPE {name} AS ENUM ({vals})"))


def upgrade() -> None:
    """Create credit_ledger_entries table with enum types and constraints."""
    # -- enum types -----------------------------------------------------------
    _create_enum_if_not_exists("transaction_direction", ["CREDIT", "DEBIT"])
    _create_enum_if_not_exists("transaction_source", ["STRIPE", "USAGE", "ADJUSTMENT", "REFUND"])

    # -- credit_ledger_entries ------------------------------------------------
    op.create_table(
        "credit_ledger_entries",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "amount",
            sa.Numeric(precision=12, scale=4),
            nullable=False,
        ),
        sa.Column(
            "direction",
            transaction_direction,
            nullable=False,
        ),
        sa.Column(
            "source",
            transaction_source,
            nullable=False,
        ),
        sa.Column(
            "reference_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "balance_after",
            sa.Numeric(precision=12, scale=4),
            nullable=False,
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "reference_id",
            "direction",
            name="uq_ledger_reference_direction",
        ),
        sa.CheckConstraint(
            "balance_after >= 0",
            name="ck_ledger_balance_non_negative",
        ),
    )
    op.create_index(
        "ix_credit_ledger_entries_user_id",
        "credit_ledger_entries",
        ["user_id"],
    )
    op.create_index(
        "ix_credit_ledger_entries_reference_id",
        "credit_ledger_entries",
        ["reference_id"],
    )


def downgrade() -> None:
    """Drop credit_ledger_entries table and enum types."""
    op.drop_index(
        "ix_credit_ledger_entries_reference_id",
        table_name="credit_ledger_entries",
    )
    op.drop_index(
        "ix_credit_ledger_entries_user_id",
        table_name="credit_ledger_entries",
    )
    op.drop_table("credit_ledger_entries")
    transaction_source.drop(op.get_bind(), checkfirst=True)
    transaction_direction.drop(op.get_bind(), checkfirst=True)
