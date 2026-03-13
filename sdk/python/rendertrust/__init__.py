# MIT License -- see LICENSE-MIT
"""RenderTrust Python SDK.

Provides synchronous and asynchronous clients for the RenderTrust API.

Quick start::

    from rendertrust import RenderTrustClient

    client = RenderTrustClient(base_url="https://api.rendertrust.com")
    client.login("user@example.com", "password")
    jobs = client.list_jobs()
"""

from rendertrust.async_client import AsyncRenderTrustClient
from rendertrust.client import RenderTrustClient
from rendertrust.exceptions import (
    AuthenticationError,
    InsufficientCreditsError,
    NotFoundError,
    RenderTrustError,
    ServiceUnavailableError,
    ValidationError,
)

__version__ = "0.1.0"

__all__ = [
    "AsyncRenderTrustClient",
    "AuthenticationError",
    "InsufficientCreditsError",
    "NotFoundError",
    "RenderTrustClient",
    "RenderTrustError",
    "ServiceUnavailableError",
    "ValidationError",
    "__version__",
]
