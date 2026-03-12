# MIT License -- see LICENSE-MIT
"""Lightweight data models for the RenderTrust Python SDK.

Uses TypedDict for zero-dependency type hints. These provide IDE
autocompletion and type-checking without requiring pydantic at runtime.
"""

from __future__ import annotations

from typing import TypedDict


class TokenPair(TypedDict):
    """JWT token pair returned by login."""

    access_token: str
    refresh_token: str
    token_type: str


class Job(TypedDict, total=False):
    """Job record returned by the API."""

    id: str
    node_id: str
    job_type: str
    payload_ref: str
    status: str
    result_ref: str | None
    error_message: str | None
    retry_count: int
    queued_at: str
    dispatched_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str


class JobDispatchResult(TypedDict):
    """Result of dispatching a job."""

    job_id: str
    node_id: str
    status: str


class JobResult(TypedDict):
    """Presigned download URL for a completed job result."""

    job_id: str
    download_url: str
    expires_in: int


class CreditBalance(TypedDict):
    """Credit balance for the authenticated user."""

    balance: str
    user_id: str


class HealthStatus(TypedDict, total=False):
    """Health check response."""

    status: str
    version: str
    environment: str
