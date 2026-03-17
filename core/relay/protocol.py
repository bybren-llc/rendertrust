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

"""WebSocket message protocol models for the edge relay.

Defines the message types and Pydantic models used for all communication
between the gateway and edge nodes over WebSocket connections.
"""

import datetime
import enum
import uuid

from pydantic import BaseModel, Field


class RelayMessageType(enum.StrEnum):
    """Types of messages exchanged over the relay WebSocket."""

    JOB_ASSIGN = "job_assign"
    JOB_ACK = "job_ack"
    STATUS_UPDATE = "status_update"
    HEARTBEAT_PING = "heartbeat_ping"
    HEARTBEAT_PONG = "heartbeat_pong"


class RelayMessage(BaseModel):
    """Base message model for all relay WebSocket communication.

    Attributes:
        type: The message type discriminator.
        payload: Arbitrary key-value payload data.
        timestamp: UTC timestamp of message creation.
    """

    type: RelayMessageType
    payload: dict[str, object] = Field(default_factory=dict)
    timestamp: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(tz=datetime.UTC)
    )


class JobAssignMessage(BaseModel):
    """Message sent from gateway to node to assign a job.

    Attributes:
        type: Always ``job_assign``.
        job_id: Unique identifier for the dispatched job.
        job_type: Category of compute job (e.g. ``render``, ``inference``).
        payload_ref: Reference to the job payload (S3 URI, IPFS CID, etc.).
        timestamp: UTC timestamp of message creation.
    """

    type: RelayMessageType = RelayMessageType.JOB_ASSIGN
    job_id: uuid.UUID
    job_type: str
    payload_ref: str
    timestamp: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(tz=datetime.UTC)
    )


class JobAckMessage(BaseModel):
    """Message sent from node to gateway acknowledging a job assignment.

    Attributes:
        type: Always ``job_ack``.
        job_id: The job being acknowledged.
        accepted: Whether the node accepted the job.
        timestamp: UTC timestamp of message creation.
    """

    type: RelayMessageType = RelayMessageType.JOB_ACK
    job_id: uuid.UUID
    accepted: bool = True
    timestamp: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(tz=datetime.UTC)
    )


class StatusUpdateMessage(BaseModel):
    """Message sent from node to gateway with execution status.

    Attributes:
        type: Always ``status_update``.
        job_id: The job this status applies to.
        status: Current status string (e.g. ``running``, ``completed``, ``failed``).
        progress: Optional progress percentage (0.0 to 1.0).
        detail: Optional human-readable detail string.
        timestamp: UTC timestamp of message creation.
    """

    type: RelayMessageType = RelayMessageType.STATUS_UPDATE
    job_id: uuid.UUID
    status: str
    progress: float | None = None
    detail: str | None = None
    timestamp: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(tz=datetime.UTC)
    )
