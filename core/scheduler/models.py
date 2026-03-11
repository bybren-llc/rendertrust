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

"""Edge node scheduler data models.

Provides EdgeNode (compute node registry) and JobDispatch (job tracking)
models for the distributed scheduler system.
"""

import datetime
import enum
import uuid

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import BaseModel


class NodeStatus(enum.StrEnum):
    """Edge node lifecycle status."""

    REGISTERED = "REGISTERED"
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"
    OFFLINE = "OFFLINE"


class JobStatus(enum.StrEnum):
    """Job dispatch lifecycle status."""

    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EdgeNode(BaseModel):
    """Registered compute node in the RenderTrust network.

    Attributes:
        public_key: Cryptographic public key for node identity verification.
        name: Human-readable display name for the node.
        capabilities: JSON list of supported compute capabilities.
        status: Current lifecycle status (REGISTERED, HEALTHY, UNHEALTHY, OFFLINE).
        last_heartbeat: Timestamp of the most recent heartbeat from this node.
        current_load: Current load factor (0.0 = idle, 1.0 = fully loaded).
        metadata_: Arbitrary JSON metadata about the node (column name: metadata).
        jobs: Relationship to dispatched jobs assigned to this node.
    """

    __tablename__ = "edge_nodes"
    __table_args__ = (
        Index("ix_edge_nodes_status", "status"),
        Index("ix_edge_nodes_last_heartbeat", "last_heartbeat"),
    )

    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    capabilities: Mapped[dict | None] = mapped_column(JSON, default=list)
    status: Mapped[NodeStatus] = mapped_column(
        Enum(NodeStatus, native_enum=False, length=20),
        default=NodeStatus.REGISTERED,
        nullable=False,
    )
    last_heartbeat: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_load: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, default=dict)

    # Relationships
    jobs: Mapped[list["JobDispatch"]] = relationship(back_populates="node")

    def __repr__(self) -> str:
        return f"<EdgeNode(id={self.id}, name={self.name}, status={self.status.value})>"


class JobDispatch(BaseModel):
    """Record of a job dispatched to an edge node.

    Attributes:
        node_id: FK to the EdgeNode this job is assigned to.
        job_type: Type/category of the job (e.g. 'render', 'inference').
        payload_ref: Reference to the job payload (S3 URI, IPFS CID, etc.).
        status: Current lifecycle status (QUEUED through COMPLETED/FAILED).
        queued_at: Timestamp when the job entered the queue.
        dispatched_at: Timestamp when the job was sent to a node.
        completed_at: Timestamp when the job finished (success or failure).
        node: Relationship to the assigned EdgeNode.
    """

    __tablename__ = "job_dispatches"
    __table_args__ = (
        Index("ix_job_dispatches_node_id", "node_id"),
        Index("ix_job_dispatches_status", "status"),
    )

    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("edge_nodes.id"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=20),
        default=JobStatus.QUEUED,
        nullable=False,
    )
    queued_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    dispatched_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    node: Mapped["EdgeNode"] = relationship(back_populates="jobs")

    def __repr__(self) -> str:
        return (
            f"<JobDispatch(id={self.id}, node_id={self.node_id}, "
            f"status={self.status.value})>"
        )
