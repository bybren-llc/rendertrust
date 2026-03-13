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

"""Worker plugins for the edge execution framework.

Each plugin implements :class:`BaseWorkerPlugin` and declares a ``job_type``
class attribute. The :class:`~edgekit.workers.executor.WorkerExecutor`
auto-discovers plugins by their ``job_type`` at init time.
"""

from edgekit.workers.plugins.base import BaseWorkerPlugin, WorkerResult
from edgekit.workers.plugins.cpu import CpuBenchmarkPlugin, EchoPlugin

__all__ = [
    "BaseWorkerPlugin",
    "CpuBenchmarkPlugin",
    "EchoPlugin",
    "WorkerResult",
]
