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

"""Edge worker execution framework with plugin-based job processing.

Provides :class:`WorkerExecutor` for receiving jobs from the relay client
and dispatching them to registered :class:`BaseWorkerPlugin` instances
based on ``job_type``. Jobs run in subprocess isolation with configurable
timeout and resource limit enforcement.
"""

from edgekit.workers.executor import WorkerExecutor
from edgekit.workers.plugins.base import BaseWorkerPlugin, WorkerResult

__all__ = ["BaseWorkerPlugin", "WorkerExecutor", "WorkerResult"]
