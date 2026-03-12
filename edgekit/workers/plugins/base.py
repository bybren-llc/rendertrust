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

"""Abstract base class for worker plugins and the WorkerResult dataclass.

Every concrete plugin must subclass :class:`BaseWorkerPlugin`, set the
``job_type`` class attribute, and implement the :meth:`execute` method.
The executor uses ``job_type`` to route incoming jobs to the correct plugin.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid


@dataclass(frozen=True, slots=True)
class WorkerResult:
    """Result of a plugin execution.

    Attributes:
        success: Whether the job completed successfully.
        result_ref: Reference to the output artifact (e.g. S3 URI, IPFS CID).
            ``None`` on failure.
        error: Human-readable error message. ``None`` on success.
    """

    success: bool
    result_ref: str | None = None
    error: str | None = None


class BaseWorkerPlugin(ABC):
    """Abstract base class for worker plugins.

    Subclasses **must** define a class-level ``job_type`` string that the
    :class:`~edgekit.workers.executor.WorkerExecutor` uses for dispatch.

    Example::

        class CpuPlugin(BaseWorkerPlugin):
            job_type = "cpu"

            async def execute(self, job_id: uuid.UUID, payload: dict) -> WorkerResult:
                # ... do work ...
                return WorkerResult(success=True, result_ref="s3://bucket/output.tar")
    """

    job_type: str
    """Unique identifier for the type of job this plugin handles."""

    @abstractmethod
    async def execute(self, job_id: uuid.UUID, payload: dict) -> WorkerResult:
        """Execute a job and return the result.

        Args:
            job_id: Unique identifier for this job.
            payload: Job-specific data (contents depend on ``job_type``).

        Returns:
            A :class:`WorkerResult` indicating success or failure.
        """
        ...
