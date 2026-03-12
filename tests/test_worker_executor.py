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

"""Unit tests for the edge worker execution framework.

Covers:
 1. Plugin registration and job_type lookup
 2. Duplicate job_type detection raises ValueError
 3. Executor receives job from relay client callback
 4. Correct plugin selected based on job_type
 5. RUNNING status sent before execution
 6. COMPLETED status sent on success
 7. FAILED status sent on plugin failure result
 8. FAILED status sent on unknown job_type
 9. FAILED status sent on timeout
10. FAILED status sent on plugin exception
11. Missing job_id handled gracefully
12. Invalid job_id handled gracefully
13. Missing job_type sends FAILED
14. WorkerResult dataclass fields
15. BaseWorkerPlugin ABC cannot be instantiated
16. registered_job_types property returns sorted list
17. Status send failure does not crash executor
18. Plugin receives correct job_data payload

Uses mocked RelayClient for unit testing.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

# Environment overrides must come before application imports.
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_fake")

import pytest

from edgekit.workers.executor import WorkerExecutor
from edgekit.workers.plugins.base import BaseWorkerPlugin, WorkerResult

# ---------------------------------------------------------------------------
# Concrete test plugins
# ---------------------------------------------------------------------------


class _EchoPlugin(BaseWorkerPlugin):
    """Plugin that echoes the payload_ref back as the result."""

    job_type = "echo"

    async def execute(self, job_id, payload):
        ref = payload.get("payload_ref", "unknown")
        return WorkerResult(success=True, result_ref=ref)


class _FailPlugin(BaseWorkerPlugin):
    """Plugin that always returns a failure result."""

    job_type = "fail"

    async def execute(self, job_id, payload):
        return WorkerResult(success=False, error="Intentional failure")


class _SlowPlugin(BaseWorkerPlugin):
    """Plugin that sleeps forever (for timeout testing)."""

    job_type = "slow"

    async def execute(self, job_id, payload):
        await asyncio.sleep(3600)
        return WorkerResult(success=True)  # pragma: no cover


class _CrashPlugin(BaseWorkerPlugin):
    """Plugin that raises an exception."""

    job_type = "crash"

    async def execute(self, job_id, payload):
        raise RuntimeError("kaboom")


class _DuplicateEchoPlugin(BaseWorkerPlugin):
    """A second plugin with the same job_type as _EchoPlugin."""

    job_type = "echo"

    async def execute(self, job_id, payload):
        return WorkerResult(success=True)  # pragma: no cover


class _TrackingPlugin(BaseWorkerPlugin):
    """Plugin that records the arguments it receives."""

    job_type = "track"

    def __init__(self):
        self.received_job_id = None
        self.received_payload = None

    async def execute(self, job_id, payload):
        self.received_job_id = job_id
        self.received_payload = payload
        return WorkerResult(success=True, result_ref="s3://bucket/tracked")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_relay():
    """Create a mock RelayClient with async send_status_update."""
    relay = MagicMock()
    relay.send_status_update = AsyncMock()
    return relay


@pytest.fixture
def echo_plugin():
    return _EchoPlugin()


@pytest.fixture
def fail_plugin():
    return _FailPlugin()


@pytest.fixture
def slow_plugin():
    return _SlowPlugin()


@pytest.fixture
def crash_plugin():
    return _CrashPlugin()


@pytest.fixture
def tracking_plugin():
    return _TrackingPlugin()


@pytest.fixture
def executor(mock_relay, echo_plugin, fail_plugin, slow_plugin, crash_plugin, tracking_plugin):
    """Create a WorkerExecutor with several test plugins."""
    return WorkerExecutor(
        relay_client=mock_relay,
        plugins=[echo_plugin, fail_plugin, slow_plugin, crash_plugin, tracking_plugin],
        timeout=0.5,  # short timeout for tests
    )


def _job_data(job_type="echo", job_id=None, payload_ref="s3://bucket/input.zip"):
    """Build a minimal job_assign-style dict."""
    return {
        "type": "job_assign",
        "job_id": str(job_id or uuid.uuid4()),
        "job_type": job_type,
        "payload_ref": payload_ref,
    }


# ---------------------------------------------------------------------------
# Tests: WorkerResult dataclass
# ---------------------------------------------------------------------------


class TestWorkerResult:
    """Verify WorkerResult dataclass behaviour."""

    def test_success_result_fields(self):
        """Success result has correct field values."""
        result = WorkerResult(success=True, result_ref="s3://out", error=None)
        assert result.success is True
        assert result.result_ref == "s3://out"
        assert result.error is None

    def test_failure_result_fields(self):
        """Failure result carries an error message."""
        result = WorkerResult(success=False, error="something broke")
        assert result.success is False
        assert result.result_ref is None
        assert result.error == "something broke"

    def test_result_is_frozen(self):
        """WorkerResult is immutable."""
        result = WorkerResult(success=True)
        with pytest.raises(AttributeError):
            result.success = False


# ---------------------------------------------------------------------------
# Tests: BaseWorkerPlugin ABC
# ---------------------------------------------------------------------------


class TestBaseWorkerPlugin:
    """Verify the abstract base class contract."""

    def test_cannot_instantiate_abc(self):
        """BaseWorkerPlugin cannot be directly instantiated."""
        with pytest.raises(TypeError):
            BaseWorkerPlugin()


# ---------------------------------------------------------------------------
# Tests: Plugin registration
# ---------------------------------------------------------------------------


class TestPluginRegistration:
    """Verify plugin lookup and duplicate detection."""

    def test_registered_job_types(self, executor):
        """registered_job_types returns sorted list of all job types."""
        expected = sorted(["echo", "fail", "slow", "crash", "track"])
        assert executor.registered_job_types == expected

    def test_duplicate_job_type_raises(self, mock_relay, echo_plugin):
        """Registering two plugins with the same job_type raises ValueError."""
        dup = _DuplicateEchoPlugin()
        with pytest.raises(ValueError, match="Duplicate job_type 'echo'"):
            WorkerExecutor(
                relay_client=mock_relay,
                plugins=[echo_plugin, dup],
            )

    def test_no_plugins_is_valid(self, mock_relay):
        """Executor with no plugins is valid (all jobs will fail at dispatch)."""
        executor = WorkerExecutor(relay_client=mock_relay, plugins=[])
        assert executor.registered_job_types == []


# ---------------------------------------------------------------------------
# Tests: Job dispatch and execution
# ---------------------------------------------------------------------------


class TestJobDispatch:
    """Verify correct plugin selection and status reporting."""

    @pytest.mark.asyncio
    async def test_correct_plugin_selected(self, executor, mock_relay):
        """Executor selects the echo plugin for job_type='echo'."""
        job = _job_data(job_type="echo", payload_ref="s3://bucket/frame.zip")
        await executor.handle_job(job)

        # Should have called send_status_update at least twice:
        # once for RUNNING, once for COMPLETED
        calls = mock_relay.send_status_update.call_args_list
        status_values = [c.kwargs.get("status") for c in calls]
        assert "running" in status_values
        assert "completed" in status_values

    @pytest.mark.asyncio
    async def test_running_status_sent_before_execution(self, executor, mock_relay):
        """RUNNING status is sent before the plugin executes."""
        job = _job_data(job_type="echo")
        await executor.handle_job(job)

        first_call = mock_relay.send_status_update.call_args_list[0]
        assert first_call.kwargs.get("status") == "running"

    @pytest.mark.asyncio
    async def test_completed_status_on_success(self, executor, mock_relay):
        """COMPLETED status is sent when plugin returns success=True."""
        job = _job_data(job_type="echo", payload_ref="s3://out/result.tar")
        await executor.handle_job(job)

        last_call = mock_relay.send_status_update.call_args_list[-1]
        assert last_call.kwargs.get("status") == "completed"
        assert last_call.kwargs.get("progress") == 1.0
        assert last_call.kwargs.get("detail") == "s3://out/result.tar"

    @pytest.mark.asyncio
    async def test_failed_status_on_plugin_failure_result(self, executor, mock_relay):
        """FAILED status sent when plugin returns success=False."""
        job = _job_data(job_type="fail")
        await executor.handle_job(job)

        last_call = mock_relay.send_status_update.call_args_list[-1]
        assert last_call.kwargs.get("status") == "failed"
        assert "Intentional failure" in last_call.kwargs.get("detail", "")

    @pytest.mark.asyncio
    async def test_failed_status_on_unknown_job_type(self, executor, mock_relay):
        """FAILED status sent when job_type has no registered plugin."""
        job = _job_data(job_type="nonexistent_type")
        await executor.handle_job(job)

        mock_relay.send_status_update.assert_called_once()
        call = mock_relay.send_status_update.call_args
        assert call.kwargs.get("status") == "failed"
        assert "Unknown job_type: nonexistent_type" in call.kwargs.get("detail", "")

    @pytest.mark.asyncio
    async def test_failed_status_on_timeout(self, executor, mock_relay):
        """FAILED status sent when plugin exceeds timeout."""
        job = _job_data(job_type="slow")
        await executor.handle_job(job)

        last_call = mock_relay.send_status_update.call_args_list[-1]
        assert last_call.kwargs.get("status") == "failed"
        assert "timed out" in last_call.kwargs.get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_failed_status_on_plugin_exception(self, executor, mock_relay):
        """FAILED status sent when plugin raises an exception."""
        job = _job_data(job_type="crash")
        await executor.handle_job(job)

        last_call = mock_relay.send_status_update.call_args_list[-1]
        assert last_call.kwargs.get("status") == "failed"
        assert "kaboom" in last_call.kwargs.get("detail", "")

    @pytest.mark.asyncio
    async def test_plugin_receives_correct_payload(self, executor, mock_relay, tracking_plugin):
        """Plugin receives the full job_data dict and parsed job_id."""
        job_id = uuid.uuid4()
        job = _job_data(job_type="track", job_id=job_id, payload_ref="s3://bucket/data.bin")
        await executor.handle_job(job)

        assert tracking_plugin.received_job_id == job_id
        assert tracking_plugin.received_payload == job
        assert tracking_plugin.received_payload["payload_ref"] == "s3://bucket/data.bin"


# ---------------------------------------------------------------------------
# Tests: Edge cases and error handling
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Verify graceful handling of malformed input and relay failures."""

    @pytest.mark.asyncio
    async def test_missing_job_id_handled(self, executor, mock_relay):
        """Job with no job_id is silently skipped (no crash)."""
        job = {"type": "job_assign", "job_type": "echo"}
        await executor.handle_job(job)
        # No status update should be sent since we can't identify the job
        mock_relay.send_status_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_job_id_handled(self, executor, mock_relay):
        """Job with non-UUID job_id is silently skipped."""
        job = {"type": "job_assign", "job_id": "not-a-uuid", "job_type": "echo"}
        await executor.handle_job(job)
        mock_relay.send_status_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_job_type_sends_failed(self, executor, mock_relay):
        """Job with no job_type gets a FAILED status."""
        job_id = str(uuid.uuid4())
        job = {"type": "job_assign", "job_id": job_id}
        await executor.handle_job(job)

        mock_relay.send_status_update.assert_called_once()
        call = mock_relay.send_status_update.call_args
        assert call.kwargs.get("status") == "failed"
        assert "Missing job_type" in call.kwargs.get("detail", "")

    @pytest.mark.asyncio
    async def test_status_send_failure_does_not_crash(self, mock_relay, echo_plugin):
        """Executor continues even if relay.send_status_update raises."""
        mock_relay.send_status_update = AsyncMock(
            side_effect=RuntimeError("relay down")
        )
        executor = WorkerExecutor(
            relay_client=mock_relay,
            plugins=[echo_plugin],
            timeout=5.0,
        )
        job = _job_data(job_type="echo")
        # Should not raise despite relay failure
        await executor.handle_job(job)

    @pytest.mark.asyncio
    async def test_empty_job_type_sends_failed(self, executor, mock_relay):
        """Job with empty string job_type gets a FAILED status."""
        job_id = str(uuid.uuid4())
        job = {"type": "job_assign", "job_id": job_id, "job_type": ""}
        await executor.handle_job(job)

        mock_relay.send_status_update.assert_called_once()
        call = mock_relay.send_status_update.call_args
        assert call.kwargs.get("status") == "failed"

    @pytest.mark.asyncio
    async def test_multiple_jobs_run_independently(self, executor, mock_relay):
        """Multiple jobs can be dispatched sequentially without interference."""
        job_echo = _job_data(job_type="echo")
        job_fail = _job_data(job_type="fail")

        await executor.handle_job(job_echo)
        await executor.handle_job(job_fail)

        # echo: running + completed = 2 calls
        # fail: running + failed = 2 calls
        assert mock_relay.send_status_update.call_count == 4

        all_statuses = [
            c.kwargs.get("status")
            for c in mock_relay.send_status_update.call_args_list
        ]
        assert all_statuses.count("running") == 2
        assert all_statuses.count("completed") == 1
        assert all_statuses.count("failed") == 1
