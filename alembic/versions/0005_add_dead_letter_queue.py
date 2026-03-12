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

"""Add dead_letter_queue table for permanently failed jobs.

Revision ID: 0005_dead_letter_queue
Revises: 0004_job_results
Create Date: 2026-03-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_dead_letter_queue"
down_revision: str | None = "0004_job_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create dead_letter_queue table for archiving exhausted-retry jobs."""
    op.create_table(
        "dead_letter_queue",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("job_dispatches.id"), nullable=False),
        sa.Column("original_payload", sa.String(500), nullable=False),
        sa.Column("error_history", sa.JSON(), nullable=False),
        sa.Column(
            "failed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dead_letter_queue_job_id", "dead_letter_queue", ["job_id"])


def downgrade() -> None:
    """Drop dead_letter_queue table."""
    op.drop_index("ix_dead_letter_queue_job_id", table_name="dead_letter_queue")
    op.drop_table("dead_letter_queue")
