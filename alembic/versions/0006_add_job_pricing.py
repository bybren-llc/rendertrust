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

"""Add job_pricing table for per-job-type credit pricing.

Revision ID: 0006_job_pricing
Revises: 0005_dead_letter_queue
Create Date: 2026-03-12
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_job_pricing"
down_revision: str | None = "0005_dead_letter_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Default pricing seed data.
_SEED_PRICING = [
    {"job_type": "render", "credits_per_unit": Decimal("10.0000"), "unit_type": "per_job"},
    {"job_type": "inference", "credits_per_unit": Decimal("5.0000"), "unit_type": "per_job"},
    {"job_type": "echo", "credits_per_unit": Decimal("0.0000"), "unit_type": "per_job"},
    {"job_type": "cpu_benchmark", "credits_per_unit": Decimal("1.0000"), "unit_type": "per_job"},
]


def upgrade() -> None:
    """Create the job_pricing table and seed default pricing data."""
    job_pricing = op.create_table(
        "job_pricing",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("credits_per_unit", sa.Numeric(12, 4), nullable=False),
        sa.Column("unit_type", sa.String(50), nullable=False, server_default="per_job"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_type", name="uq_job_pricing_job_type"),
    )

    op.create_index("ix_job_pricing_job_type", "job_pricing", ["job_type"], unique=True)

    # Seed default pricing rows with Python-generated UUIDs for portability.
    op.bulk_insert(
        job_pricing,
        [
            {
                "id": uuid.uuid4(),
                "job_type": row["job_type"],
                "credits_per_unit": row["credits_per_unit"],
                "unit_type": row["unit_type"],
            }
            for row in _SEED_PRICING
        ],
    )


def downgrade() -> None:
    """Drop the job_pricing table."""
    op.drop_index("ix_job_pricing_job_type", table_name="job_pricing")
    op.drop_table("job_pricing")
