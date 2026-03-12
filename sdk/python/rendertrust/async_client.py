# MIT License -- see LICENSE-MIT
"""Asynchronous HTTP client for the RenderTrust API.

Example usage::

    import asyncio
    from rendertrust import AsyncRenderTrustClient

    async def main():
        async with AsyncRenderTrustClient(base_url="https://api.rendertrust.com") as client:
            await client.login("user@example.com", "password")

            jobs = await client.list_jobs(status="completed")
            for job in jobs:
                print(job["id"], job["status"])

    asyncio.run(main())
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from rendertrust.exceptions import (
    AuthenticationError,
    InsufficientCreditsError,
    NotFoundError,
    RenderTrustError,
    ServiceUnavailableError,
    ValidationError,
)


class AsyncRenderTrustClient:
    """Asynchronous client for the RenderTrust API.

    Supports two authentication modes:
    - **JWT**: Call :meth:`login` or pass ``token`` directly.
    - **API Key**: Pass ``api_key`` for edge-node / service-account access.

    Args:
        base_url: Base URL of the RenderTrust API (no trailing slash).
        api_key: API key for X-API-Key header authentication.
        token: Pre-existing JWT access token (skips login).
        timeout: Default request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str = "https://api.rendertrust.com",
        api_key: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._token = token
        self._refresh_token: str | None = None
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.aclose()

    async def __aenter__(self) -> AsyncRenderTrustClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        """Build request headers with the appropriate auth mechanism."""
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    def _handle_response(self, response: httpx.Response) -> Any:
        """Check response status and raise typed SDK exceptions on errors."""
        if response.is_success:
            return response.json()

        status_code = response.status_code
        try:
            body = response.json()
        except Exception:
            body = {"detail": response.text}

        detail = body.get("detail", str(body))

        if status_code == 401:
            raise AuthenticationError(
                message=detail,
                status_code=status_code,
                response_body=body,
            )
        if status_code == 402:
            raise InsufficientCreditsError(
                message=detail,
                status_code=status_code,
                response_body=body,
            )
        if status_code == 404:
            raise NotFoundError(
                message=detail,
                status_code=status_code,
                response_body=body,
            )
        if status_code == 422:
            raise ValidationError(
                message=detail,
                status_code=status_code,
                response_body=body,
            )
        if status_code == 503:
            raise ServiceUnavailableError(
                message=detail,
                status_code=status_code,
                response_body=body,
            )

        raise RenderTrustError(
            message=detail,
            status_code=status_code,
            response_body=body,
        )

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def login(self, email: str, password: str) -> dict[str, Any]:
        """Authenticate with email and password.

        On success the client stores the access and refresh tokens
        internally so subsequent requests are automatically authenticated.

        Args:
            email: User email address.
            password: User password.

        Returns:
            Token pair dict with ``access_token``, ``refresh_token``, and
            ``token_type`` keys.

        Raises:
            AuthenticationError: If credentials are invalid.
        """
        response = await self._client.post(
            f"{self.base_url}/api/v1/auth/login",
            json={"email": email, "password": password},
            headers=self._headers(),
        )
        data = self._handle_response(response)
        self._token = data["access_token"]
        self._refresh_token = data.get("refresh_token")
        return data

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    async def submit_job(
        self,
        job_type: str,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Submit (dispatch) a job to the least-loaded edge node.

        Args:
            job_type: Job type string (e.g. ``"render"``, ``"inference"``).
            payload: Job payload. The ``payload_ref`` field is derived from
                the payload's ``"ref"`` key, or the payload is serialized as
                a JSON string if no ref is provided.
            **kwargs: Additional fields forwarded in the request body.

        Returns:
            Dispatch result dict with ``job_id``, ``node_id``, and
            ``status`` keys.

        Raises:
            AuthenticationError: If not authenticated.
            ServiceUnavailableError: If no healthy nodes are available.
        """
        payload_ref = payload.get("ref", str(payload))
        body: dict[str, Any] = {
            "job_type": job_type,
            "payload_ref": payload_ref,
            **kwargs,
        }
        response = await self._client.post(
            f"{self.base_url}/api/v1/jobs/dispatch",
            json=body,
            headers=self._headers(),
        )
        return self._handle_response(response)

    async def get_job(self, job_id: str) -> dict[str, Any]:
        """Get details for a single job by ID.

        Args:
            job_id: UUID of the job.

        Returns:
            Full job dict.

        Raises:
            NotFoundError: If the job does not exist.
        """
        response = await self._client.get(
            f"{self.base_url}/api/v1/jobs/{job_id}",
            headers=self._headers(),
        )
        return self._handle_response(response)

    async def list_jobs(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List jobs with optional status filter.

        Args:
            status: Filter by job status (e.g. ``"completed"``, ``"queued"``).
            limit: Maximum number of jobs to return (1-100, default 50).

        Returns:
            List of job dicts.
        """
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        response = await self._client.get(
            f"{self.base_url}/api/v1/jobs",
            params=params,
            headers=self._headers(),
        )
        data = self._handle_response(response)
        return data.get("jobs", [])

    async def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Cancel a queued or dispatched job.

        Args:
            job_id: UUID of the job to cancel.

        Returns:
            Updated job dict with ``status`` set to ``"cancelled"``.

        Raises:
            NotFoundError: If the job does not exist.
            RenderTrustError: If the job is not in a cancellable state.
        """
        response = await self._client.post(
            f"{self.base_url}/api/v1/jobs/{job_id}/cancel",
            headers=self._headers(),
        )
        return self._handle_response(response)

    async def download_result(
        self,
        job_id: str,
        output_path: str | None = None,
    ) -> str:
        """Download the result of a completed job.

        First retrieves a presigned URL from the API, then downloads the
        file content from that URL.

        Args:
            job_id: UUID of the completed job.
            output_path: Local file path to save the result. If ``None``,
                defaults to ``{job_id}.result`` in the current directory.

        Returns:
            Absolute path of the downloaded file.

        Raises:
            NotFoundError: If the job or result does not exist.
        """
        # Step 1: Get presigned URL from the API.
        response = await self._client.get(
            f"{self.base_url}/api/v1/jobs/{job_id}/result",
            headers=self._headers(),
        )
        data = self._handle_response(response)
        download_url = data["download_url"]

        # Step 2: Download from presigned URL.
        if output_path is None:
            output_path = f"{job_id}.result"

        async with self._client.stream("GET", download_url) as stream:
            stream.raise_for_status()
            with open(output_path, "wb") as f:
                async for chunk in stream.aiter_bytes(chunk_size=8192):
                    f.write(chunk)

        return os.path.abspath(output_path)

    # ------------------------------------------------------------------
    # Credits
    # ------------------------------------------------------------------

    async def get_balance(self) -> dict[str, Any]:
        """Get the current credit balance for the authenticated user.

        Returns:
            Balance dict with ``balance`` and ``user_id`` keys.
        """
        response = await self._client.get(
            f"{self.base_url}/api/v1/credits/balance",
            headers=self._headers(),
        )
        return self._handle_response(response)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        """Check the API health status.

        Returns:
            Health dict with ``status``, ``version``, and ``environment``
            keys.
        """
        response = await self._client.get(
            f"{self.base_url}/health",
            headers=self._headers(),
        )
        return self._handle_response(response)
