# MIT License -- see LICENSE-MIT
"""Tests for the RenderTrust Python SDK.

Uses ``respx`` to mock httpx transport, so no real HTTP calls are made.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest
import respx

from rendertrust import (
    AsyncRenderTrustClient,
    AuthenticationError,
    InsufficientCreditsError,
    NotFoundError,
    RenderTrustClient,
    RenderTrustError,
    ServiceUnavailableError,
    ValidationError,
)

BASE_URL = "https://api.rendertrust.com"

# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

TOKEN_RESPONSE: dict[str, Any] = {
    "access_token": "test-access-token",
    "refresh_token": "test-refresh-token",
    "token_type": "bearer",
}

JOB_RESPONSE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000001",
    "node_id": "00000000-0000-0000-0000-000000000099",
    "job_type": "render",
    "payload_ref": "s3://bucket/payload.json",
    "status": "completed",
    "result_ref": "s3://bucket/result.bin",
    "error_message": None,
    "retry_count": 0,
    "queued_at": "2026-03-12T00:00:00",
    "dispatched_at": "2026-03-12T00:00:01",
    "completed_at": "2026-03-12T00:01:00",
    "created_at": "2026-03-12T00:00:00",
    "updated_at": "2026-03-12T00:01:00",
}

JOB_LIST_RESPONSE: dict[str, Any] = {
    "jobs": [JOB_RESPONSE],
    "count": 1,
}

DISPATCH_RESPONSE: dict[str, Any] = {
    "job_id": "00000000-0000-0000-0000-000000000001",
    "node_id": "00000000-0000-0000-0000-000000000099",
    "status": "dispatched",
}

JOB_RESULT_RESPONSE: dict[str, Any] = {
    "job_id": "00000000-0000-0000-0000-000000000001",
    "download_url": "https://storage.example.com/result.bin?signed=1",
    "expires_in": 3600,
}

BALANCE_RESPONSE: dict[str, Any] = {
    "balance": "100.50",
    "user_id": "user-123",
}

HEALTH_RESPONSE: dict[str, Any] = {
    "status": "healthy",
    "version": "0.1.0",
    "environment": "production",
}


# -----------------------------------------------------------------------
# Sync client tests
# -----------------------------------------------------------------------


class TestSyncLogin:
    """Test login flow for the sync client."""

    @respx.mock
    def test_login_success(self) -> None:
        respx.post(f"{BASE_URL}/api/v1/auth/login").mock(
            return_value=httpx.Response(200, json=TOKEN_RESPONSE)
        )
        client = RenderTrustClient(base_url=BASE_URL)
        result = client.login("user@example.com", "password")
        assert result["access_token"] == "test-access-token"
        assert result["refresh_token"] == "test-refresh-token"
        assert client._token == "test-access-token"
        client.close()

    @respx.mock
    def test_login_invalid_credentials(self) -> None:
        respx.post(f"{BASE_URL}/api/v1/auth/login").mock(
            return_value=httpx.Response(401, json={"detail": "Invalid email or password"})
        )
        client = RenderTrustClient(base_url=BASE_URL)
        with pytest.raises(AuthenticationError) as exc_info:
            client.login("bad@example.com", "wrong")
        assert exc_info.value.status_code == 401
        assert "Invalid email or password" in str(exc_info.value)
        client.close()


class TestSyncJobs:
    """Test job operations for the sync client."""

    @respx.mock
    def test_submit_job(self) -> None:
        respx.post(f"{BASE_URL}/api/v1/jobs/dispatch").mock(
            return_value=httpx.Response(201, json=DISPATCH_RESPONSE)
        )
        client = RenderTrustClient(base_url=BASE_URL, token="tok")
        result = client.submit_job("render", {"ref": "s3://bucket/payload.json"})
        assert result["job_id"] == "00000000-0000-0000-0000-000000000001"
        assert result["status"] == "dispatched"
        client.close()

    @respx.mock
    def test_submit_job_no_nodes(self) -> None:
        respx.post(f"{BASE_URL}/api/v1/jobs/dispatch").mock(
            return_value=httpx.Response(
                503, json={"detail": "No healthy nodes available for job type: render"}
            )
        )
        client = RenderTrustClient(base_url=BASE_URL, token="tok")
        with pytest.raises(ServiceUnavailableError) as exc_info:
            client.submit_job("render", {"ref": "s3://payload"})
        assert exc_info.value.status_code == 503
        client.close()

    @respx.mock
    def test_get_job(self) -> None:
        job_id = "00000000-0000-0000-0000-000000000001"
        respx.get(f"{BASE_URL}/api/v1/jobs/{job_id}").mock(
            return_value=httpx.Response(200, json=JOB_RESPONSE)
        )
        client = RenderTrustClient(base_url=BASE_URL, token="tok")
        result = client.get_job(job_id)
        assert result["id"] == job_id
        assert result["status"] == "completed"
        client.close()

    @respx.mock
    def test_get_job_not_found(self) -> None:
        job_id = "00000000-0000-0000-0000-999999999999"
        respx.get(f"{BASE_URL}/api/v1/jobs/{job_id}").mock(
            return_value=httpx.Response(404, json={"detail": "Job not found"})
        )
        client = RenderTrustClient(base_url=BASE_URL, token="tok")
        with pytest.raises(NotFoundError) as exc_info:
            client.get_job(job_id)
        assert exc_info.value.status_code == 404
        client.close()

    @respx.mock
    def test_list_jobs(self) -> None:
        respx.get(f"{BASE_URL}/api/v1/jobs").mock(
            return_value=httpx.Response(200, json=JOB_LIST_RESPONSE)
        )
        client = RenderTrustClient(base_url=BASE_URL, token="tok")
        result = client.list_jobs()
        assert len(result) == 1
        assert result[0]["id"] == "00000000-0000-0000-0000-000000000001"
        client.close()

    @respx.mock
    def test_list_jobs_with_status_filter(self) -> None:
        route = respx.get(f"{BASE_URL}/api/v1/jobs").mock(
            return_value=httpx.Response(200, json=JOB_LIST_RESPONSE)
        )
        client = RenderTrustClient(base_url=BASE_URL, token="tok")
        result = client.list_jobs(status="completed", limit=10)
        assert len(result) == 1
        # Verify query parameters were sent
        assert route.calls.last.request.url.params["status"] == "completed"
        assert route.calls.last.request.url.params["limit"] == "10"
        client.close()

    @respx.mock
    def test_cancel_job(self) -> None:
        job_id = "00000000-0000-0000-0000-000000000001"
        cancelled_job = {**JOB_RESPONSE, "status": "cancelled"}
        respx.post(f"{BASE_URL}/api/v1/jobs/{job_id}/cancel").mock(
            return_value=httpx.Response(200, json=cancelled_job)
        )
        client = RenderTrustClient(base_url=BASE_URL, token="tok")
        result = client.cancel_job(job_id)
        assert result["status"] == "cancelled"
        client.close()


class TestSyncDownloadResult:
    """Test result download for the sync client."""

    @respx.mock
    def test_download_result(self, tmp_path: Any) -> None:
        job_id = "00000000-0000-0000-0000-000000000001"
        output_file = str(tmp_path / "output.bin")
        file_content = b"binary result data here"

        respx.get(f"{BASE_URL}/api/v1/jobs/{job_id}/result").mock(
            return_value=httpx.Response(200, json=JOB_RESULT_RESPONSE)
        )
        respx.get("https://storage.example.com/result.bin?signed=1").mock(
            return_value=httpx.Response(200, content=file_content)
        )

        client = RenderTrustClient(base_url=BASE_URL, token="tok")
        result_path = client.download_result(job_id, output_path=output_file)
        assert os.path.exists(result_path)
        with open(result_path, "rb") as f:
            assert f.read() == file_content
        client.close()

    @respx.mock
    def test_download_result_not_found(self) -> None:
        job_id = "00000000-0000-0000-0000-000999999999"
        respx.get(f"{BASE_URL}/api/v1/jobs/{job_id}/result").mock(
            return_value=httpx.Response(
                404, json={"detail": "Job result not available: job is not completed"}
            )
        )
        client = RenderTrustClient(base_url=BASE_URL, token="tok")
        with pytest.raises(NotFoundError):
            client.download_result(job_id)
        client.close()


class TestSyncCredits:
    """Test credit operations for the sync client."""

    @respx.mock
    def test_get_balance(self) -> None:
        respx.get(f"{BASE_URL}/api/v1/credits/balance").mock(
            return_value=httpx.Response(200, json=BALANCE_RESPONSE)
        )
        client = RenderTrustClient(base_url=BASE_URL, token="tok")
        result = client.get_balance()
        assert result["balance"] == "100.50"
        assert result["user_id"] == "user-123"
        client.close()

    @respx.mock
    def test_insufficient_credits(self) -> None:
        respx.get(f"{BASE_URL}/api/v1/credits/balance").mock(
            return_value=httpx.Response(
                402,
                json={
                    "detail": "Insufficient credits",
                    "available": "0.00",
                    "requested": "10.00",
                },
            )
        )
        client = RenderTrustClient(base_url=BASE_URL, token="tok")
        with pytest.raises(InsufficientCreditsError) as exc_info:
            client.get_balance()
        assert exc_info.value.status_code == 402
        assert exc_info.value.response_body is not None
        assert exc_info.value.response_body["available"] == "0.00"
        client.close()


class TestSyncHealth:
    """Test health check for the sync client."""

    @respx.mock
    def test_health(self) -> None:
        respx.get(f"{BASE_URL}/health").mock(return_value=httpx.Response(200, json=HEALTH_RESPONSE))
        client = RenderTrustClient(base_url=BASE_URL)
        result = client.health()
        assert result["status"] == "healthy"
        assert result["version"] == "0.1.0"
        client.close()


class TestSyncAuth:
    """Test authentication headers for the sync client."""

    @respx.mock
    def test_bearer_token_header(self) -> None:
        route = respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(200, json=HEALTH_RESPONSE)
        )
        client = RenderTrustClient(base_url=BASE_URL, token="my-jwt")
        client.health()
        assert route.calls.last.request.headers["authorization"] == "Bearer my-jwt"
        client.close()

    @respx.mock
    def test_api_key_header(self) -> None:
        route = respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(200, json=HEALTH_RESPONSE)
        )
        client = RenderTrustClient(base_url=BASE_URL, api_key="key-123")
        client.health()
        assert route.calls.last.request.headers["x-api-key"] == "key-123"
        client.close()

    @respx.mock
    def test_both_auth_headers(self) -> None:
        route = respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(200, json=HEALTH_RESPONSE)
        )
        client = RenderTrustClient(base_url=BASE_URL, token="jwt", api_key="key")
        client.health()
        headers = route.calls.last.request.headers
        assert headers["authorization"] == "Bearer jwt"
        assert headers["x-api-key"] == "key"
        client.close()

    def test_context_manager(self) -> None:
        with RenderTrustClient(base_url=BASE_URL) as client:
            assert client.base_url == BASE_URL


class TestSyncErrorHandling:
    """Test error mapping for various HTTP status codes."""

    @respx.mock
    def test_422_validation_error(self) -> None:
        respx.get(f"{BASE_URL}/api/v1/jobs").mock(
            return_value=httpx.Response(
                422, json={"detail": "Invalid status: bogus. Valid values: [...]"}
            )
        )
        client = RenderTrustClient(base_url=BASE_URL, token="tok")
        with pytest.raises(ValidationError) as exc_info:
            client.list_jobs(status="bogus")
        assert exc_info.value.status_code == 422
        client.close()

    @respx.mock
    def test_generic_server_error(self) -> None:
        respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(500, json={"detail": "Internal server error"})
        )
        client = RenderTrustClient(base_url=BASE_URL)
        with pytest.raises(RenderTrustError) as exc_info:
            client.health()
        assert exc_info.value.status_code == 500
        client.close()

    @respx.mock
    def test_non_json_error_response(self) -> None:
        respx.get(f"{BASE_URL}/health").mock(return_value=httpx.Response(502, text="Bad Gateway"))
        client = RenderTrustClient(base_url=BASE_URL)
        with pytest.raises(RenderTrustError) as exc_info:
            client.health()
        assert exc_info.value.status_code == 502
        client.close()


class TestExceptions:
    """Test exception class behaviour."""

    def test_rendertrust_error_repr(self) -> None:
        err = RenderTrustError("boom", status_code=500, response_body={"detail": "boom"})
        assert "RenderTrustError" in repr(err)
        assert "500" in repr(err)

    def test_inheritance_chain(self) -> None:
        assert issubclass(AuthenticationError, RenderTrustError)
        assert issubclass(NotFoundError, RenderTrustError)
        assert issubclass(InsufficientCreditsError, RenderTrustError)
        assert issubclass(ValidationError, RenderTrustError)
        assert issubclass(ServiceUnavailableError, RenderTrustError)


# -----------------------------------------------------------------------
# Async client tests
# -----------------------------------------------------------------------


class TestAsyncLogin:
    """Test login flow for the async client."""

    @respx.mock
    async def test_login_success(self) -> None:
        respx.post(f"{BASE_URL}/api/v1/auth/login").mock(
            return_value=httpx.Response(200, json=TOKEN_RESPONSE)
        )
        client = AsyncRenderTrustClient(base_url=BASE_URL)
        result = await client.login("user@example.com", "password")
        assert result["access_token"] == "test-access-token"
        assert client._token == "test-access-token"
        await client.close()

    @respx.mock
    async def test_login_failure(self) -> None:
        respx.post(f"{BASE_URL}/api/v1/auth/login").mock(
            return_value=httpx.Response(401, json={"detail": "Invalid email or password"})
        )
        client = AsyncRenderTrustClient(base_url=BASE_URL)
        with pytest.raises(AuthenticationError):
            await client.login("bad@example.com", "wrong")
        await client.close()


class TestAsyncJobs:
    """Test job operations for the async client."""

    @respx.mock
    async def test_submit_job(self) -> None:
        respx.post(f"{BASE_URL}/api/v1/jobs/dispatch").mock(
            return_value=httpx.Response(201, json=DISPATCH_RESPONSE)
        )
        async with AsyncRenderTrustClient(base_url=BASE_URL, token="tok") as client:
            result = await client.submit_job("render", {"ref": "s3://bucket/payload"})
            assert result["job_id"] == "00000000-0000-0000-0000-000000000001"

    @respx.mock
    async def test_get_job(self) -> None:
        job_id = "00000000-0000-0000-0000-000000000001"
        respx.get(f"{BASE_URL}/api/v1/jobs/{job_id}").mock(
            return_value=httpx.Response(200, json=JOB_RESPONSE)
        )
        async with AsyncRenderTrustClient(base_url=BASE_URL, token="tok") as client:
            result = await client.get_job(job_id)
            assert result["status"] == "completed"

    @respx.mock
    async def test_list_jobs(self) -> None:
        respx.get(f"{BASE_URL}/api/v1/jobs").mock(
            return_value=httpx.Response(200, json=JOB_LIST_RESPONSE)
        )
        async with AsyncRenderTrustClient(base_url=BASE_URL, token="tok") as client:
            result = await client.list_jobs()
            assert len(result) == 1

    @respx.mock
    async def test_cancel_job(self) -> None:
        job_id = "00000000-0000-0000-0000-000000000001"
        cancelled = {**JOB_RESPONSE, "status": "cancelled"}
        respx.post(f"{BASE_URL}/api/v1/jobs/{job_id}/cancel").mock(
            return_value=httpx.Response(200, json=cancelled)
        )
        async with AsyncRenderTrustClient(base_url=BASE_URL, token="tok") as client:
            result = await client.cancel_job(job_id)
            assert result["status"] == "cancelled"

    @respx.mock
    async def test_download_result(self, tmp_path: Any) -> None:
        job_id = "00000000-0000-0000-0000-000000000001"
        output_file = str(tmp_path / "async_output.bin")
        file_content = b"async binary result"

        respx.get(f"{BASE_URL}/api/v1/jobs/{job_id}/result").mock(
            return_value=httpx.Response(200, json=JOB_RESULT_RESPONSE)
        )
        respx.get("https://storage.example.com/result.bin?signed=1").mock(
            return_value=httpx.Response(200, content=file_content)
        )

        async with AsyncRenderTrustClient(base_url=BASE_URL, token="tok") as client:
            result_path = await client.download_result(job_id, output_path=output_file)
            assert os.path.exists(result_path)
            with open(result_path, "rb") as f:
                assert f.read() == file_content


class TestAsyncCreditsAndHealth:
    """Test credits and health for the async client."""

    @respx.mock
    async def test_get_balance(self) -> None:
        respx.get(f"{BASE_URL}/api/v1/credits/balance").mock(
            return_value=httpx.Response(200, json=BALANCE_RESPONSE)
        )
        async with AsyncRenderTrustClient(base_url=BASE_URL, token="tok") as client:
            result = await client.get_balance()
            assert result["balance"] == "100.50"

    @respx.mock
    async def test_health(self) -> None:
        respx.get(f"{BASE_URL}/health").mock(return_value=httpx.Response(200, json=HEALTH_RESPONSE))
        async with AsyncRenderTrustClient(base_url=BASE_URL) as client:
            result = await client.health()
            assert result["status"] == "healthy"

    @respx.mock
    async def test_async_context_manager(self) -> None:
        respx.get(f"{BASE_URL}/health").mock(return_value=httpx.Response(200, json=HEALTH_RESPONSE))
        async with AsyncRenderTrustClient(base_url=BASE_URL) as client:
            assert client.base_url == BASE_URL
