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

"""CPU worker plugins for echo testing and CPU benchmarking.

Provides two concrete :class:`~edgekit.workers.plugins.base.BaseWorkerPlugin`
implementations:

- :class:`EchoPlugin` -- returns the input payload as output, used for
  end-to-end connectivity and integration testing.
- :class:`CpuBenchmarkPlugin` -- runs a deterministic CPU benchmark
  (prime sieve) and returns a performance score.
"""

from __future__ import annotations

import json
import math
import time
from typing import TYPE_CHECKING

from edgekit.workers.plugins.base import BaseWorkerPlugin, WorkerResult

if TYPE_CHECKING:
    import uuid


class EchoPlugin(BaseWorkerPlugin):
    """Echo plugin that returns the input payload as output.

    Used for end-to-end validation of the worker pipeline. The plugin
    serializes the incoming ``payload`` dict to JSON and returns it as
    the ``result_ref`` field.

    Expected payload keys:
        ``message`` (str, optional): A message to echo back. If omitted,
            the entire payload dict is echoed.

    Returns:
        :class:`WorkerResult` with ``success=True`` and the echoed
        content as ``result_ref``.
    """

    job_type = "echo"

    async def execute(self, job_id: uuid.UUID, payload: dict) -> WorkerResult:
        """Echo the payload back as the result.

        Args:
            job_id: Unique job identifier.
            payload: Job data dict. If a ``"message"`` key is present,
                only that value is echoed; otherwise the full payload
                is serialized.

        Returns:
            A successful :class:`WorkerResult` with the echoed content.
        """
        try:
            if "message" in payload:
                echo_content = str(payload["message"])
            else:
                echo_content = json.dumps(payload, sort_keys=True, default=str)

            return WorkerResult(
                success=True,
                result_ref=echo_content,
            )
        except (TypeError, ValueError) as exc:
            return WorkerResult(
                success=False,
                error=f"Echo payload serialization failed: {exc}",
            )


class CpuBenchmarkPlugin(BaseWorkerPlugin):
    """CPU benchmark plugin that computes a prime sieve and returns a score.

    Runs a Sieve of Eratosthenes up to a configurable limit and reports
    the number of primes found and the wall-clock duration as a score.

    Expected payload keys:
        ``limit`` (int, optional): Upper bound for the prime sieve.
            Defaults to 100,000. Must be a positive integer <= 10,000,000.

    Returns:
        :class:`WorkerResult` with ``success=True`` and a JSON-encoded
        result containing ``primes_found``, ``limit``, and
        ``duration_seconds``.
    """

    job_type = "cpu_benchmark"

    #: Maximum allowed sieve limit to prevent resource exhaustion.
    MAX_LIMIT = 10_000_000

    #: Default sieve limit when none is specified.
    DEFAULT_LIMIT = 100_000

    async def execute(self, job_id: uuid.UUID, payload: dict) -> WorkerResult:
        """Run a CPU benchmark and return the score.

        Args:
            job_id: Unique job identifier.
            payload: Job data dict. ``"limit"`` controls sieve size.

        Returns:
            A :class:`WorkerResult` with benchmark results as JSON in
            ``result_ref``, or a failure if the payload is invalid.
        """
        # -- Parse and validate limit --
        raw_limit = payload.get("limit", self.DEFAULT_LIMIT)

        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            return WorkerResult(
                success=False,
                error=f"Invalid limit value: {raw_limit!r} (must be a positive integer)",
            )

        if limit < 2:
            return WorkerResult(
                success=False,
                error=f"Limit must be >= 2, got {limit}",
            )

        if limit > self.MAX_LIMIT:
            return WorkerResult(
                success=False,
                error=(
                    f"Limit {limit} exceeds maximum allowed value "
                    f"of {self.MAX_LIMIT}"
                ),
            )

        # -- Run the sieve --
        start_time = time.monotonic()
        primes_found = self._sieve_of_eratosthenes(limit)
        duration = time.monotonic() - start_time

        result = json.dumps({
            "job_id": str(job_id),
            "primes_found": primes_found,
            "limit": limit,
            "duration_seconds": round(duration, 6),
        })

        return WorkerResult(success=True, result_ref=result)

    @staticmethod
    def _sieve_of_eratosthenes(limit: int) -> int:
        """Count primes up to *limit* using the Sieve of Eratosthenes.

        Args:
            limit: Upper bound (inclusive) for the sieve.

        Returns:
            The number of primes found in ``[2, limit]``.
        """
        if limit < 2:
            return 0

        is_prime = bytearray(b"\x01") * (limit + 1)
        is_prime[0] = 0
        is_prime[1] = 0

        for i in range(2, math.isqrt(limit) + 1):
            if is_prime[i]:
                # Mark multiples of i starting from i*i
                is_prime[i * i :: i] = bytearray(len(is_prime[i * i :: i]))

        return sum(is_prime)
