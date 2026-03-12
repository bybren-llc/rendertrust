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

"""Add result_ref, error_message, retry_count to job_dispatches.

Revision ID: 0004_job_results
Revises: 0003_scheduler
Create Date: 2026-03-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_job_results"
down_revision: str | None = "0003_scheduler"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add result_ref, error_message, and retry_count columns to job_dispatches."""
    op.add_column("job_dispatches", sa.Column("result_ref", sa.String(500), nullable=True))
    op.add_column("job_dispatches", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column(
        "job_dispatches",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    """Remove result_ref, error_message, and retry_count columns from job_dispatches."""
    op.drop_column("job_dispatches", "retry_count")
    op.drop_column("job_dispatches", "error_message")
    op.drop_column("job_dispatches", "result_ref")
