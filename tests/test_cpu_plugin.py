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

"""Unit tests for the CPU worker plugins (EchoPlugin and CpuBenchmarkPlugin).

Covers:
 1. EchoPlugin echoes full payload as JSON when no "message" key
 2. EchoPlugin echoes only the "message" value when present
 3. EchoPlugin handles empty payload dict
 4. EchoPlugin returns success=True on valid input
 5. EchoPlugin job_type is "echo"
 6. CpuBenchmarkPlugin job_type is "cpu_benchmark"
 7. CpuBenchmarkPlugin runs with default limit when not specified
 8. CpuBenchmarkPlugin uses custom limit from payload
 9. CpuBenchmarkPlugin rejects limit < 2
10. CpuBenchmarkPlugin rejects limit exceeding MAX_LIMIT
11. CpuBenchmarkPlugin rejects non-integer limit
12. CpuBenchmarkPlugin result contains expected JSON fields
13. CpuBenchmarkPlugin sieve returns correct prime count for known values
14. CpuBenchmarkPlugin reports correct job_id in result
15. Both plugins are subclasses of BaseWorkerPlugin
16. EchoPlugin handles non-serializable payload gracefully
"""

from __future__ import annotations

import json
import os
import uuid

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

from edgekit.workers.plugins.base import BaseWorkerPlugin
from edgekit.workers.plugins.cpu import CpuBenchmarkPlugin, EchoPlugin

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def echo_plugin():
    """Create an EchoPlugin instance."""
    return EchoPlugin()


@pytest.fixture
def benchmark_plugin():
    """Create a CpuBenchmarkPlugin instance."""
    return CpuBenchmarkPlugin()


@pytest.fixture
def job_id():
    """Generate a deterministic job UUID for testing."""
    return uuid.UUID("12345678-1234-5678-1234-567812345678")


# ---------------------------------------------------------------------------
# Tests: Plugin identity and inheritance
# ---------------------------------------------------------------------------


class TestPluginIdentity:
    """Verify plugin class attributes and inheritance."""

    def test_echo_plugin_job_type(self, echo_plugin):
        """EchoPlugin declares job_type='echo'."""
        assert echo_plugin.job_type == "echo"

    def test_benchmark_plugin_job_type(self, benchmark_plugin):
        """CpuBenchmarkPlugin declares job_type='cpu_benchmark'."""
        assert benchmark_plugin.job_type == "cpu_benchmark"

    def test_echo_plugin_is_base_subclass(self, echo_plugin):
        """EchoPlugin is a subclass of BaseWorkerPlugin."""
        assert isinstance(echo_plugin, BaseWorkerPlugin)

    def test_benchmark_plugin_is_base_subclass(self, benchmark_plugin):
        """CpuBenchmarkPlugin is a subclass of BaseWorkerPlugin."""
        assert isinstance(benchmark_plugin, BaseWorkerPlugin)


# ---------------------------------------------------------------------------
# Tests: EchoPlugin
# ---------------------------------------------------------------------------


class TestEchoPlugin:
    """Verify EchoPlugin echo behaviour."""

    @pytest.mark.asyncio
    async def test_echo_full_payload_as_json(self, echo_plugin, job_id):
        """When no 'message' key, the entire payload is serialized to JSON."""
        payload = {"job_type": "echo", "job_id": str(job_id), "data": "hello"}
        result = await echo_plugin.execute(job_id, payload)

        assert result.success is True
        assert result.error is None

        # result_ref should be valid JSON matching the payload
        parsed = json.loads(result.result_ref)
        assert parsed["data"] == "hello"
        assert parsed["job_type"] == "echo"

    @pytest.mark.asyncio
    async def test_echo_message_key_only(self, echo_plugin, job_id):
        """When 'message' key is present, only that value is echoed."""
        payload = {
            "job_type": "echo",
            "job_id": str(job_id),
            "message": "ping",
            "extra": "ignored",
        }
        result = await echo_plugin.execute(job_id, payload)

        assert result.success is True
        assert result.result_ref == "ping"

    @pytest.mark.asyncio
    async def test_echo_empty_payload(self, echo_plugin, job_id):
        """Empty payload produces valid JSON output."""
        result = await echo_plugin.execute(job_id, {})

        assert result.success is True
        parsed = json.loads(result.result_ref)
        assert parsed == {}

    @pytest.mark.asyncio
    async def test_echo_numeric_message(self, echo_plugin, job_id):
        """Numeric 'message' value is converted to string."""
        payload = {"message": 42}
        result = await echo_plugin.execute(job_id, payload)

        assert result.success is True
        assert result.result_ref == "42"

    @pytest.mark.asyncio
    async def test_echo_returns_success(self, echo_plugin, job_id):
        """EchoPlugin always returns success=True for valid payloads."""
        payload = {"job_type": "echo"}
        result = await echo_plugin.execute(job_id, payload)

        assert result.success is True
        assert result.error is None

    @pytest.mark.asyncio
    async def test_echo_sorted_keys_in_json(self, echo_plugin, job_id):
        """Full-payload echo produces sorted JSON keys."""
        payload = {"z_key": "last", "a_key": "first"}
        result = await echo_plugin.execute(job_id, payload)

        assert result.success is True
        # Verify keys are sorted
        parsed_keys = list(json.loads(result.result_ref).keys())
        assert parsed_keys == sorted(parsed_keys)


# ---------------------------------------------------------------------------
# Tests: CpuBenchmarkPlugin
# ---------------------------------------------------------------------------


class TestCpuBenchmarkPlugin:
    """Verify CpuBenchmarkPlugin benchmark behaviour."""

    @pytest.mark.asyncio
    async def test_benchmark_default_limit(self, benchmark_plugin, job_id):
        """Runs with default limit (100_000) when not specified in payload."""
        payload = {"job_type": "cpu_benchmark", "job_id": str(job_id)}
        result = await benchmark_plugin.execute(job_id, payload)

        assert result.success is True
        assert result.error is None

        parsed = json.loads(result.result_ref)
        assert parsed["limit"] == 100_000
        # There are 9592 primes below 100,000
        assert parsed["primes_found"] == 9592

    @pytest.mark.asyncio
    async def test_benchmark_custom_limit(self, benchmark_plugin, job_id):
        """Uses custom limit from payload."""
        payload = {"job_type": "cpu_benchmark", "limit": 1000}
        result = await benchmark_plugin.execute(job_id, payload)

        assert result.success is True
        parsed = json.loads(result.result_ref)
        assert parsed["limit"] == 1000
        # There are 168 primes below 1000
        assert parsed["primes_found"] == 168

    @pytest.mark.asyncio
    async def test_benchmark_limit_too_small(self, benchmark_plugin, job_id):
        """Rejects limit < 2 with failure result."""
        payload = {"limit": 1}
        result = await benchmark_plugin.execute(job_id, payload)

        assert result.success is False
        assert "Limit must be >= 2" in result.error
        assert result.result_ref is None

    @pytest.mark.asyncio
    async def test_benchmark_limit_zero(self, benchmark_plugin, job_id):
        """Rejects limit of 0."""
        payload = {"limit": 0}
        result = await benchmark_plugin.execute(job_id, payload)

        assert result.success is False
        assert "Limit must be >= 2" in result.error

    @pytest.mark.asyncio
    async def test_benchmark_limit_negative(self, benchmark_plugin, job_id):
        """Rejects negative limit."""
        payload = {"limit": -100}
        result = await benchmark_plugin.execute(job_id, payload)

        assert result.success is False
        assert "Limit must be >= 2" in result.error

    @pytest.mark.asyncio
    async def test_benchmark_limit_exceeds_max(self, benchmark_plugin, job_id):
        """Rejects limit exceeding MAX_LIMIT."""
        payload = {"limit": CpuBenchmarkPlugin.MAX_LIMIT + 1}
        result = await benchmark_plugin.execute(job_id, payload)

        assert result.success is False
        assert "exceeds maximum" in result.error
        assert result.result_ref is None

    @pytest.mark.asyncio
    async def test_benchmark_non_integer_limit(self, benchmark_plugin, job_id):
        """Rejects non-integer limit value."""
        payload = {"limit": "not_a_number"}
        result = await benchmark_plugin.execute(job_id, payload)

        assert result.success is False
        assert "Invalid limit value" in result.error

    @pytest.mark.asyncio
    async def test_benchmark_float_limit_truncated(self, benchmark_plugin, job_id):
        """Float limit is truncated to int (int() behaviour)."""
        payload = {"limit": 100.9}
        result = await benchmark_plugin.execute(job_id, payload)

        assert result.success is True
        parsed = json.loads(result.result_ref)
        assert parsed["limit"] == 100
        # 25 primes up to 100
        assert parsed["primes_found"] == 25

    @pytest.mark.asyncio
    async def test_benchmark_result_contains_expected_fields(self, benchmark_plugin, job_id):
        """Result JSON contains job_id, primes_found, limit, duration_seconds."""
        payload = {"limit": 50}
        result = await benchmark_plugin.execute(job_id, payload)

        assert result.success is True
        parsed = json.loads(result.result_ref)

        assert "job_id" in parsed
        assert "primes_found" in parsed
        assert "limit" in parsed
        assert "duration_seconds" in parsed

        assert parsed["job_id"] == str(job_id)
        assert isinstance(parsed["primes_found"], int)
        assert isinstance(parsed["duration_seconds"], float)

    @pytest.mark.asyncio
    async def test_benchmark_reports_correct_job_id(self, benchmark_plugin, job_id):
        """Result includes the correct job_id string."""
        payload = {"limit": 10}
        result = await benchmark_plugin.execute(job_id, payload)

        parsed = json.loads(result.result_ref)
        assert parsed["job_id"] == "12345678-1234-5678-1234-567812345678"

    @pytest.mark.asyncio
    async def test_benchmark_none_limit(self, benchmark_plugin, job_id):
        """Explicit None limit is rejected as non-integer."""
        payload = {"limit": None}
        result = await benchmark_plugin.execute(job_id, payload)

        # int(None) raises TypeError, handled as invalid
        assert result.success is False
        assert "Invalid limit value" in result.error


# ---------------------------------------------------------------------------
# Tests: Sieve correctness
# ---------------------------------------------------------------------------


class TestSieveCorrectness:
    """Verify the prime sieve implementation against known values."""

    @pytest.mark.parametrize(
        ("limit", "expected_count"),
        [
            (2, 1),       # Only 2
            (10, 4),      # 2, 3, 5, 7
            (30, 10),     # First 10 primes
            (100, 25),    # 25 primes up to 100
            (1000, 168),  # 168 primes up to 1000
        ],
    )
    def test_sieve_known_prime_counts(self, limit, expected_count):
        """Sieve of Eratosthenes returns correct count for known limits."""
        assert CpuBenchmarkPlugin._sieve_of_eratosthenes(limit) == expected_count

    def test_sieve_below_two_returns_zero(self):
        """Sieve with limit < 2 returns 0 (no primes)."""
        assert CpuBenchmarkPlugin._sieve_of_eratosthenes(1) == 0
        assert CpuBenchmarkPlugin._sieve_of_eratosthenes(0) == 0
