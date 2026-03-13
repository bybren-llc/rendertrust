# MIT License -- see LICENSE-MIT
"""Custom exceptions for the RenderTrust Python SDK."""

from __future__ import annotations

from typing import Any


class RenderTrustError(Exception):
    """Base exception for all RenderTrust SDK errors.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP status code from the API response, if available.
        response_body: Raw response body from the API, if available.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_body = response_body

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"status_code={self.status_code!r})"
        )


class AuthenticationError(RenderTrustError):
    """Raised when authentication fails (HTTP 401)."""


class NotFoundError(RenderTrustError):
    """Raised when a requested resource is not found (HTTP 404)."""


class InsufficientCreditsError(RenderTrustError):
    """Raised when the user has insufficient credits (HTTP 402)."""


class ValidationError(RenderTrustError):
    """Raised when the API rejects input as invalid (HTTP 422)."""


class ServiceUnavailableError(RenderTrustError):
    """Raised when the API service is unavailable (HTTP 503)."""
