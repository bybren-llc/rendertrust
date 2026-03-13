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

"""Add edge_nodes and job_dispatches tables.

Revision ID: 0003_scheduler
Revises: 0002_credit_ledger
Create Date: 2026-03-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_scheduler"
down_revision: str | None = "0002_credit_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create edge_nodes and job_dispatches tables."""
    # -- edge_nodes ------------------------------------------------------------
    op.create_table(
        "edge_nodes",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "public_key",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "capabilities",
            sa.JSON(),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="REGISTERED",
            nullable=False,
        ),
        sa.Column(
            "last_heartbeat",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "current_load",
            sa.Float(),
            server_default=sa.text("0.0"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            sa.JSON(),
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
    )
    op.create_index("ix_edge_nodes_status", "edge_nodes", ["status"])
    op.create_index("ix_edge_nodes_last_heartbeat", "edge_nodes", ["last_heartbeat"])

    # -- job_dispatches --------------------------------------------------------
    op.create_table(
        "job_dispatches",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "node_id",
            sa.Uuid(),
            sa.ForeignKey("edge_nodes.id"),
            nullable=False,
        ),
        sa.Column(
            "job_type",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "payload_ref",
            sa.String(length=500),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="QUEUED",
            nullable=False,
        ),
        sa.Column(
            "queued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "dispatched_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
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
    )
    op.create_index("ix_job_dispatches_node_id", "job_dispatches", ["node_id"])
    op.create_index("ix_job_dispatches_status", "job_dispatches", ["status"])


def downgrade() -> None:
    """Drop job_dispatches and edge_nodes tables (job_dispatches first due to FK)."""
    op.drop_index("ix_job_dispatches_status", table_name="job_dispatches")
    op.drop_index("ix_job_dispatches_node_id", table_name="job_dispatches")
    op.drop_table("job_dispatches")
    op.drop_index("ix_edge_nodes_last_heartbeat", table_name="edge_nodes")
    op.drop_index("ix_edge_nodes_status", table_name="edge_nodes")
    op.drop_table("edge_nodes")
