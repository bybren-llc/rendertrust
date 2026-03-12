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

"""Worker executor that routes jobs to plugins and manages execution lifecycle.

Receives job dicts from the :class:`~edgekit.relay.client.RelayClient`
``on_job_assigned`` callback, selects the correct plugin based on
``job_type``, runs it with timeout enforcement, and reports status
back through the relay client (RUNNING -> COMPLETED / FAILED).
"""

from __future__ import annotations

import asyncio
import resource
import uuid
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from edgekit.relay.client import RelayClient
    from edgekit.workers.plugins.base import BaseWorkerPlugin

logger = structlog.get_logger(__name__)

# Default execution constraints
_DEFAULT_TIMEOUT_SECONDS = 300.0
_DEFAULT_MAX_MEMORY_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
_DEFAULT_MAX_CPU_SECONDS = 600


class WorkerExecutor:
    """Routes incoming jobs to registered plugins and manages execution.

    Plugins are registered at construction time and looked up by their
    ``job_type`` class attribute. The executor sends status updates
    through the relay client as the job progresses.

    Args:
        relay_client: The :class:`~edgekit.relay.client.RelayClient` used to
            send status updates back to the gateway.
        plugins: List of plugin instances to register.
        timeout: Maximum wall-clock seconds allowed per job execution
            (default 300).
        max_memory_bytes: Soft memory limit in bytes applied via
            ``resource.setrlimit`` before running the plugin (default 2 GiB).
        max_cpu_seconds: Soft CPU time limit in seconds applied via
            ``resource.setrlimit`` before running the plugin (default 600).

    Raises:
        ValueError: If two plugins declare the same ``job_type``.

    Example::

        executor = WorkerExecutor(
            relay_client=client,
            plugins=[CpuPlugin(), RenderPlugin()],
            timeout=120.0,
        )
        # Wire as the relay client callback:
        client = RelayClient(
            ...,
            on_job_assigned=executor.handle_job,
        )
    """

    def __init__(
        self,
        relay_client: RelayClient,
        plugins: list[BaseWorkerPlugin],
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        max_memory_bytes: int = _DEFAULT_MAX_MEMORY_BYTES,
        max_cpu_seconds: int = _DEFAULT_MAX_CPU_SECONDS,
    ) -> None:
        self._relay = relay_client
        self._timeout = timeout
        self._max_memory_bytes = max_memory_bytes
        self._max_cpu_seconds = max_cpu_seconds

        # Build the plugin registry, detecting duplicates
        self._plugins: dict[str, BaseWorkerPlugin] = {}
        for plugin in plugins:
            if plugin.job_type in self._plugins:
                raise ValueError(
                    f"Duplicate job_type '{plugin.job_type}' registered by "
                    f"{type(plugin).__name__} (already registered by "
                    f"{type(self._plugins[plugin.job_type]).__name__})"
                )
            self._plugins[plugin.job_type] = plugin
            logger.info(
                "worker_plugin_registered",
                job_type=plugin.job_type,
                plugin=type(plugin).__name__,
            )

    @property
    def registered_job_types(self) -> list[str]:
        """Return a sorted list of registered job type identifiers."""
        return sorted(self._plugins.keys())

    def _apply_resource_limits(self) -> None:
        """Apply soft resource limits for the current process.

        Sets RLIMIT_AS (virtual memory) and RLIMIT_CPU (CPU time) so that
        runaway plugins get killed by the OS rather than consuming the node.

        These limits are *soft* -- the hard limit is left unchanged.
        """
        try:
            _, hard = resource.getrlimit(resource.RLIMIT_AS)
            resource.setrlimit(
                resource.RLIMIT_AS,
                (self._max_memory_bytes, hard),
            )
        except (ValueError, OSError):
            logger.warning("worker_rlimit_as_not_set")

        try:
            _, hard = resource.getrlimit(resource.RLIMIT_CPU)
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (self._max_cpu_seconds, hard),
            )
        except (ValueError, OSError):
            logger.warning("worker_rlimit_cpu_not_set")

    async def handle_job(self, job_data: dict[str, Any]) -> None:
        """Process an incoming job from the relay client.

        This is the callback wired to :class:`~edgekit.relay.client.RelayClient`
        ``on_job_assigned``.

        Workflow:
        1. Parse ``job_id`` and ``job_type`` from ``job_data``.
        2. Look up the plugin for the ``job_type``.
        3. Send ``RUNNING`` status via relay.
        4. Execute the plugin with timeout enforcement.
        5. Send ``COMPLETED`` or ``FAILED`` status via relay.

        Args:
            job_data: The raw dict from the ``job_assign`` message. Expected
                keys: ``job_id`` (str UUID), ``job_type`` (str), plus any
                job-specific payload.
        """
        # -- Parse job_id --
        raw_job_id = job_data.get("job_id")
        if raw_job_id is None:
            logger.error("worker_missing_job_id", job_data=job_data)
            return

        try:
            job_id = uuid.UUID(str(raw_job_id))
        except ValueError:
            logger.error("worker_invalid_job_id", job_id=raw_job_id)
            return

        # -- Parse job_type --
        job_type = job_data.get("job_type")
        if not job_type:
            logger.error("worker_missing_job_type", job_id=str(job_id))
            await self._send_status(
                job_id, "failed", detail="Missing job_type in job data"
            )
            return

        log = logger.bind(job_id=str(job_id), job_type=job_type)

        # -- Look up plugin --
        plugin = self._plugins.get(job_type)
        if plugin is None:
            log.error("worker_unknown_job_type")
            await self._send_status(
                job_id,
                "failed",
                detail=f"Unknown job_type: {job_type}",
            )
            return

        # -- Execute with resource limits and timeout --
        log.info("worker_job_starting", plugin=type(plugin).__name__)
        await self._send_status(job_id, "running")

        self._apply_resource_limits()

        try:
            result = await asyncio.wait_for(
                plugin.execute(job_id, job_data),
                timeout=self._timeout,
            )
        except TimeoutError:
            log.error("worker_job_timeout", timeout=self._timeout)
            await self._send_status(
                job_id,
                "failed",
                detail=f"Job timed out after {self._timeout}s",
            )
            return
        except Exception as exc:
            log.exception("worker_job_exception")
            await self._send_status(
                job_id,
                "failed",
                detail=f"Plugin raised exception: {exc}",
            )
            return

        # -- Report result --
        if result.success:
            log.info("worker_job_completed", result_ref=result.result_ref)
            await self._send_status(
                job_id,
                "completed",
                progress=1.0,
                detail=result.result_ref,
            )
        else:
            log.warning("worker_job_failed", error=result.error)
            await self._send_status(
                job_id,
                "failed",
                detail=result.error,
            )

    async def _send_status(
        self,
        job_id: uuid.UUID,
        status: str,
        progress: float | None = None,
        detail: str | None = None,
    ) -> None:
        """Send a status update through the relay client.

        Catches and logs any errors from the relay so that status-send
        failures do not crash the executor.
        """
        try:
            await self._relay.send_status_update(
                job_id=job_id,
                status=status,
                progress=progress,
                detail=detail,
            )
        except Exception:
            logger.exception(
                "worker_status_send_failed",
                job_id=str(job_id),
                status=status,
            )
