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

"""GPU and CPU metrics poller for edge nodes.

Periodically collects hardware metrics (GPU utilization, VRAM, temperature,
CPU cores) and reports them through the WebSocket relay to the gateway.
Replaces the legacy InfluxDB + direct HTTP heartbeat in fleet_gateway.py.
"""

from __future__ import annotations

import asyncio
import platform
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_INTERVAL = 30


@dataclass(frozen=True)
class GpuInfo:
    """Snapshot of GPU hardware state from nvidia-smi."""

    name: str
    """GPU product name, e.g. ``NVIDIA GeForce RTX 4090``."""

    vram_total_mb: int
    """Total VRAM in megabytes."""

    vram_used_mb: int
    """Currently used VRAM in megabytes."""

    utilization: float
    """GPU utilization as a fraction between 0.0 and 1.0."""

    temperature: int
    """GPU temperature in degrees Celsius."""


@dataclass(frozen=True)
class CpuInfo:
    """Snapshot of CPU identity and core count."""

    model: str
    """CPU model name, e.g. ``AMD Ryzen 9 7950X``."""

    cores: int
    """Number of logical CPU cores."""


class RelayTransport(Protocol):
    """Protocol describing the send interface the poller requires.

    Any object whose ``send_message`` coroutine accepts ``type`` and ``data``
    keyword arguments satisfies this protocol.  The :class:`RelayClient`
    can be adapted to this interface with a thin wrapper, or a mock can
    implement it directly in tests.
    """

    async def send_message(self, *, type: str, data: dict[str, Any]) -> None: ...


def detect_gpu() -> GpuInfo | None:
    """Query ``nvidia-smi`` for GPU metrics.

    Returns:
        A :class:`GpuInfo` instance if nvidia-smi succeeds, or ``None`` if
        no GPU is detected or nvidia-smi is not installed.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        logger.debug("nvidia_smi_not_found")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("nvidia_smi_timeout")
        return None

    if result.returncode != 0:
        logger.warning("nvidia_smi_failed", returncode=result.returncode, stderr=result.stderr)
        return None

    line = result.stdout.strip()
    if not line:
        logger.warning("nvidia_smi_empty_output")
        return None

    try:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            logger.warning("nvidia_smi_unexpected_format", output=line)
            return None

        name = parts[0]
        vram_total_mb = int(parts[1])
        vram_used_mb = int(parts[2])
        utilization_pct = float(parts[3])
        temperature = int(parts[4])

        return GpuInfo(
            name=name,
            vram_total_mb=vram_total_mb,
            vram_used_mb=vram_used_mb,
            utilization=utilization_pct / 100.0,
            temperature=temperature,
        )
    except (ValueError, IndexError):
        logger.warning("nvidia_smi_parse_error", output=line)
        return None


def detect_cpu() -> CpuInfo:
    """Detect CPU model name and logical core count.

    Uses :func:`platform.processor` for the model name (falls back to
    ``"unknown"``) and :func:`os.cpu_count` for the core count (falls
    back to 1).

    Returns:
        A :class:`CpuInfo` instance.
    """
    import os

    model = platform.processor() or "unknown"
    cores = os.cpu_count() or 1
    return CpuInfo(model=model, cores=cores)


def build_capabilities(gpu: GpuInfo | None, cpu: CpuInfo) -> list[str]:
    """Build a capabilities list suitable for the ``EdgeNode.capabilities`` field.

    Format:
        - ``gpu:<short_name>:<vram>gb`` when a GPU is detected
        - ``cpu:<cores>core`` always included

    Examples::

        ["gpu:rtx4090:24gb", "cpu:32core"]
        ["cpu:8core"]

    Args:
        gpu: GPU info, or ``None`` if no GPU is available.
        cpu: CPU info.

    Returns:
        List of capability strings.
    """
    caps: list[str] = []
    if gpu is not None:
        short_name = gpu.name.lower()
        # Strip common prefixes for brevity
        for prefix in ("nvidia geforce ", "nvidia ", "geforce "):
            if short_name.startswith(prefix):
                short_name = short_name[len(prefix) :]
                break
        short_name = short_name.replace(" ", "")
        vram_gb = gpu.vram_total_mb // 1024
        caps.append(f"gpu:{short_name}:{vram_gb}gb")
    caps.append(f"cpu:{cpu.cores}core")
    return caps


def build_metrics_payload(gpu: GpuInfo | None, cpu: CpuInfo) -> dict[str, Any]:
    """Build a JSON-serializable metrics payload.

    The payload includes GPU metrics (or ``None`` for each if no GPU),
    CPU core count, and an ISO-8601 UTC timestamp.

    Args:
        gpu: GPU info, or ``None`` if no GPU is available.
        cpu: CPU info.

    Returns:
        Dictionary with keys: ``gpu_utilization``, ``gpu_temperature``,
        ``gpu_vram_used_mb``, ``gpu_vram_total_mb``, ``cpu_cores``,
        ``capabilities``, ``timestamp``.
    """
    capabilities = build_capabilities(gpu, cpu)
    return {
        "gpu_utilization": gpu.utilization if gpu else None,
        "gpu_temperature": gpu.temperature if gpu else None,
        "gpu_vram_used_mb": gpu.vram_used_mb if gpu else None,
        "gpu_vram_total_mb": gpu.vram_total_mb if gpu else None,
        "cpu_cores": cpu.cores,
        "cpu_model": cpu.model,
        "capabilities": capabilities,
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }


async def run_poller(
    relay_client: RelayTransport,
    interval: int = DEFAULT_INTERVAL,
) -> None:
    """Continuously collect and report hardware metrics via the relay.

    Runs an infinite loop that:

    1. Calls :func:`detect_gpu` and :func:`detect_cpu`.
    2. Builds a metrics payload via :func:`build_metrics_payload`.
    3. Sends the payload through ``relay_client.send_message(type="metrics", ...)``.
    4. Sleeps for ``interval`` seconds before the next cycle.

    Errors during detection or sending are logged but do not stop the loop.

    Args:
        relay_client: Object implementing the :class:`RelayTransport` protocol.
        interval: Seconds between metric reports (default :data:`DEFAULT_INTERVAL`).
    """
    logger.info("metrics_poller_started", interval=interval)

    while True:
        try:
            gpu = detect_gpu()
            cpu = detect_cpu()
            payload = build_metrics_payload(gpu, cpu)

            await relay_client.send_message(type="metrics", data=payload)
            logger.debug(
                "metrics_sent",
                gpu_detected=gpu is not None,
                cpu_cores=cpu.cores,
            )
        except Exception:
            logger.exception("metrics_poller_send_error")

        await asyncio.sleep(interval)
