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

"""Unit tests for edgekit.poller.metrics -- GPU/CPU metrics poller.

Covers:
 1. detect_gpu returns GpuInfo when nvidia-smi succeeds
 2. detect_gpu returns None when nvidia-smi is not found
 3. detect_gpu returns None when nvidia-smi returns non-zero exit code
 4. detect_cpu returns correct core count and model
 5. build_capabilities with GPU produces correct format
 6. build_capabilities without GPU produces cpu-only format
 7. build_metrics_payload includes all required fields
 8. build_metrics_payload without GPU has null GPU fields
 9. run_poller sends metrics at interval via relay client
10. run_poller handles relay send failure gracefully
11. GpuInfo and CpuInfo dataclass field validation
12. nvidia-smi parsing handles various output formats
13. detect_gpu returns None on timeout
14. detect_gpu returns None on empty output
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import fields
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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

from edgekit.poller.metrics import (
    DEFAULT_INTERVAL,
    CpuInfo,
    GpuInfo,
    build_capabilities,
    build_metrics_payload,
    detect_cpu,
    detect_gpu,
    run_poller,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NVIDIA_SMI_OUTPUT_RTX4090 = (
    "NVIDIA GeForce RTX 4090, 24576, 8192, 75, 62\n"
)

NVIDIA_SMI_OUTPUT_A100 = (
    "NVIDIA A100-SXM4-80GB, 81920, 40960, 92, 71\n"
)

NVIDIA_SMI_OUTPUT_SPACES = (
    "  NVIDIA GeForce RTX 3080 , 10240 , 4096 , 50 , 55  \n"
)


@pytest.fixture
def mock_relay_client() -> AsyncMock:
    """Create a mock relay transport with async send_message."""
    client = AsyncMock()
    client.send_message = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# detect_gpu tests
# ---------------------------------------------------------------------------


class TestDetectGpu:
    """Tests for the detect_gpu function."""

    def test_returns_gpu_info_when_nvidia_smi_succeeds(self):
        """detect_gpu returns a GpuInfo when nvidia-smi produces valid output."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = NVIDIA_SMI_OUTPUT_RTX4090
        mock_result.stderr = ""

        with patch("edgekit.poller.metrics.subprocess.run", return_value=mock_result):
            gpu = detect_gpu()

        assert gpu is not None
        assert isinstance(gpu, GpuInfo)
        assert gpu.name == "NVIDIA GeForce RTX 4090"
        assert gpu.vram_total_mb == 24576
        assert gpu.vram_used_mb == 8192
        assert gpu.utilization == pytest.approx(0.75)
        assert gpu.temperature == 62

    def test_returns_none_when_nvidia_smi_not_found(self):
        """detect_gpu returns None when nvidia-smi binary is not installed."""
        with patch(
            "edgekit.poller.metrics.subprocess.run",
            side_effect=FileNotFoundError("nvidia-smi not found"),
        ):
            gpu = detect_gpu()

        assert gpu is None

    def test_returns_none_when_nvidia_smi_fails(self):
        """detect_gpu returns None when nvidia-smi exits with non-zero code."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "NVIDIA-SMI has failed"

        with patch("edgekit.poller.metrics.subprocess.run", return_value=mock_result):
            gpu = detect_gpu()

        assert gpu is None

    def test_returns_none_on_timeout(self):
        """detect_gpu returns None when nvidia-smi times out."""
        with patch(
            "edgekit.poller.metrics.subprocess.run",
            side_effect=subprocess.TimeoutExpired("nvidia-smi", 10),
        ):
            gpu = detect_gpu()

        assert gpu is None

    def test_returns_none_on_empty_output(self):
        """detect_gpu returns None when nvidia-smi returns empty output."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "\n"
        mock_result.stderr = ""

        with patch("edgekit.poller.metrics.subprocess.run", return_value=mock_result):
            gpu = detect_gpu()

        assert gpu is None

    def test_parses_a100_output_format(self):
        """detect_gpu correctly parses A100 nvidia-smi output."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = NVIDIA_SMI_OUTPUT_A100
        mock_result.stderr = ""

        with patch("edgekit.poller.metrics.subprocess.run", return_value=mock_result):
            gpu = detect_gpu()

        assert gpu is not None
        assert gpu.name == "NVIDIA A100-SXM4-80GB"
        assert gpu.vram_total_mb == 81920
        assert gpu.vram_used_mb == 40960
        assert gpu.utilization == pytest.approx(0.92)
        assert gpu.temperature == 71

    def test_handles_output_with_extra_spaces(self):
        """detect_gpu strips whitespace from nvidia-smi CSV fields."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = NVIDIA_SMI_OUTPUT_SPACES
        mock_result.stderr = ""

        with patch("edgekit.poller.metrics.subprocess.run", return_value=mock_result):
            gpu = detect_gpu()

        assert gpu is not None
        assert gpu.name == "NVIDIA GeForce RTX 3080"
        assert gpu.vram_total_mb == 10240
        assert gpu.vram_used_mb == 4096
        assert gpu.utilization == pytest.approx(0.50)
        assert gpu.temperature == 55

    def test_returns_none_on_malformed_output(self):
        """detect_gpu returns None when nvidia-smi output is not CSV-parseable."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "some garbage output without commas"
        mock_result.stderr = ""

        with patch("edgekit.poller.metrics.subprocess.run", return_value=mock_result):
            gpu = detect_gpu()

        assert gpu is None


# ---------------------------------------------------------------------------
# detect_cpu tests
# ---------------------------------------------------------------------------


class TestDetectCpu:
    """Tests for the detect_cpu function."""

    def test_returns_correct_core_count_and_model(self):
        """detect_cpu returns CpuInfo with correct values from platform/os."""
        with (
            patch("platform.processor", return_value="AMD Ryzen 9 7950X"),
            patch("os.cpu_count", return_value=32),
        ):
            cpu = detect_cpu()

        assert isinstance(cpu, CpuInfo)
        assert cpu.model == "AMD Ryzen 9 7950X"
        assert cpu.cores == 32

    def test_fallback_when_processor_is_empty(self):
        """detect_cpu falls back to 'unknown' when platform.processor returns empty string."""
        with (
            patch("platform.processor", return_value=""),
            patch("os.cpu_count", return_value=8),
        ):
            cpu = detect_cpu()

        assert cpu.model == "unknown"
        assert cpu.cores == 8

    def test_fallback_when_cpu_count_is_none(self):
        """detect_cpu falls back to 1 core when os.cpu_count returns None."""
        with (
            patch("platform.processor", return_value="x86_64"),
            patch("os.cpu_count", return_value=None),
        ):
            cpu = detect_cpu()

        assert cpu.cores == 1


# ---------------------------------------------------------------------------
# build_capabilities tests
# ---------------------------------------------------------------------------


class TestBuildCapabilities:
    """Tests for the build_capabilities function."""

    def test_with_gpu_produces_correct_format(self):
        """Capabilities include gpu:<name>:<vram>gb and cpu:<N>core."""
        gpu = GpuInfo(
            name="NVIDIA GeForce RTX 4090",
            vram_total_mb=24576,
            vram_used_mb=8192,
            utilization=0.75,
            temperature=62,
        )
        cpu = CpuInfo(model="AMD Ryzen 9 7950X", cores=32)

        caps = build_capabilities(gpu, cpu)

        assert len(caps) == 2
        assert caps[0] == "gpu:rtx4090:24gb"
        assert caps[1] == "cpu:32core"

    def test_without_gpu_produces_cpu_only(self):
        """Capabilities list contains only cpu entry when no GPU."""
        cpu = CpuInfo(model="Intel Xeon", cores=16)

        caps = build_capabilities(None, cpu)

        assert len(caps) == 1
        assert caps[0] == "cpu:16core"

    def test_a100_gpu_name_formatting(self):
        """NVIDIA A100 name is shortened correctly (no 'geforce' prefix)."""
        gpu = GpuInfo(
            name="NVIDIA A100-SXM4-80GB",
            vram_total_mb=81920,
            vram_used_mb=0,
            utilization=0.0,
            temperature=30,
        )
        cpu = CpuInfo(model="x86_64", cores=64)

        caps = build_capabilities(gpu, cpu)

        assert caps[0] == "gpu:a100-sxm4-80gb:80gb"


# ---------------------------------------------------------------------------
# build_metrics_payload tests
# ---------------------------------------------------------------------------


class TestBuildMetricsPayload:
    """Tests for the build_metrics_payload function."""

    def test_includes_all_required_fields_with_gpu(self):
        """Payload includes all GPU and CPU fields plus a timestamp."""
        gpu = GpuInfo(
            name="NVIDIA GeForce RTX 4090",
            vram_total_mb=24576,
            vram_used_mb=8192,
            utilization=0.75,
            temperature=62,
        )
        cpu = CpuInfo(model="AMD Ryzen 9 7950X", cores=32)

        payload = build_metrics_payload(gpu, cpu)

        assert payload["gpu_utilization"] == pytest.approx(0.75)
        assert payload["gpu_temperature"] == 62
        assert payload["gpu_vram_used_mb"] == 8192
        assert payload["gpu_vram_total_mb"] == 24576
        assert payload["cpu_cores"] == 32
        assert payload["cpu_model"] == "AMD Ryzen 9 7950X"
        assert "timestamp" in payload
        assert "capabilities" in payload
        assert isinstance(payload["capabilities"], list)

    def test_without_gpu_has_null_gpu_fields(self):
        """Payload GPU fields are None when no GPU detected."""
        cpu = CpuInfo(model="x86_64", cores=8)

        payload = build_metrics_payload(None, cpu)

        assert payload["gpu_utilization"] is None
        assert payload["gpu_temperature"] is None
        assert payload["gpu_vram_used_mb"] is None
        assert payload["gpu_vram_total_mb"] is None
        assert payload["cpu_cores"] == 8
        assert payload["capabilities"] == ["cpu:8core"]

    def test_timestamp_is_iso_format(self):
        """Payload timestamp is an ISO-8601 formatted string."""
        cpu = CpuInfo(model="x86_64", cores=4)

        payload = build_metrics_payload(None, cpu)

        # Should be parseable as ISO datetime
        from datetime import datetime

        ts = datetime.fromisoformat(payload["timestamp"])
        assert ts is not None


# ---------------------------------------------------------------------------
# run_poller tests
# ---------------------------------------------------------------------------


class TestRunPoller:
    """Tests for the async run_poller function."""

    @pytest.mark.asyncio
    async def test_sends_metrics_at_interval(self, mock_relay_client):
        """run_poller calls send_message on each iteration."""
        call_count = 0

        async def counting_send(**kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise KeyboardInterrupt  # break the loop

        mock_relay_client.send_message = AsyncMock(side_effect=counting_send)

        with (
            patch("edgekit.poller.metrics.detect_gpu", return_value=None),
            patch(
                "edgekit.poller.metrics.detect_cpu",
                return_value=CpuInfo(model="test", cores=4),
            ),
            patch(
                "edgekit.poller.metrics.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep,
            pytest.raises(KeyboardInterrupt),
        ):
            await run_poller(mock_relay_client, interval=10)

        # Should have been called 3 times before the KeyboardInterrupt
        assert call_count == 3
        # asyncio.sleep should have been called with the interval
        assert mock_sleep.call_count >= 2
        mock_sleep.assert_called_with(10)

    @pytest.mark.asyncio
    async def test_sends_correct_message_type(self, mock_relay_client):
        """run_poller sends messages with type='metrics'."""
        call_count = 0

        async def stop_after_one(**kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise KeyboardInterrupt

        mock_relay_client.send_message = AsyncMock(side_effect=stop_after_one)

        with (
            patch("edgekit.poller.metrics.detect_gpu", return_value=None),
            patch(
                "edgekit.poller.metrics.detect_cpu",
                return_value=CpuInfo(model="test", cores=4),
            ),
            patch("edgekit.poller.metrics.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(KeyboardInterrupt),
        ):
            await run_poller(mock_relay_client, interval=5)

        # Verify type="metrics" was passed
        mock_relay_client.send_message.assert_called_once()
        call_kwargs = mock_relay_client.send_message.call_args
        assert call_kwargs.kwargs["type"] == "metrics"
        assert "cpu_cores" in call_kwargs.kwargs["data"]

    @pytest.mark.asyncio
    async def test_handles_relay_send_failure_gracefully(self, mock_relay_client):
        """run_poller continues looping when send_message raises an exception."""
        call_count = 0

        async def failing_then_ok(**kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Relay unavailable")
            if call_count >= 2:
                raise KeyboardInterrupt  # stop the loop

        mock_relay_client.send_message = AsyncMock(side_effect=failing_then_ok)

        with (
            patch("edgekit.poller.metrics.detect_gpu", return_value=None),
            patch(
                "edgekit.poller.metrics.detect_cpu",
                return_value=CpuInfo(model="test", cores=4),
            ),
            patch("edgekit.poller.metrics.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(KeyboardInterrupt),
        ):
            await run_poller(mock_relay_client, interval=1)

        # The poller should have tried twice: first failed, second raised KeyboardInterrupt
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_uses_default_interval(self):
        """DEFAULT_INTERVAL is 30 seconds."""
        assert DEFAULT_INTERVAL == 30


# ---------------------------------------------------------------------------
# Dataclass validation tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    """Tests for GpuInfo and CpuInfo dataclass definitions."""

    def test_gpu_info_fields(self):
        """GpuInfo has the expected frozen fields."""
        field_names = {f.name for f in fields(GpuInfo)}
        expected = {"name", "vram_total_mb", "vram_used_mb", "utilization", "temperature"}
        assert field_names == expected

    def test_cpu_info_fields(self):
        """CpuInfo has the expected frozen fields."""
        field_names = {f.name for f in fields(CpuInfo)}
        assert field_names == {"model", "cores"}

    def test_gpu_info_is_frozen(self):
        """GpuInfo instances are immutable."""
        gpu = GpuInfo(
            name="Test GPU",
            vram_total_mb=8192,
            vram_used_mb=1024,
            utilization=0.5,
            temperature=50,
        )
        with pytest.raises(AttributeError):
            gpu.name = "Changed"  # type: ignore[misc]

    def test_cpu_info_is_frozen(self):
        """CpuInfo instances are immutable."""
        cpu = CpuInfo(model="Test CPU", cores=8)
        with pytest.raises(AttributeError):
            cpu.cores = 16  # type: ignore[misc]

    def test_gpu_info_equality(self):
        """Two GpuInfo instances with identical values are equal."""
        a = GpuInfo(name="GPU", vram_total_mb=8192, vram_used_mb=0, utilization=0.0, temperature=30)
        b = GpuInfo(name="GPU", vram_total_mb=8192, vram_used_mb=0, utilization=0.0, temperature=30)
        assert a == b
