# Copyright 2024 ByBren, LLC
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

"""
Async background bundler task.

This module provides the long-running coroutine
:func:`run_bundler_loop` which periodically:

1. Queries for un-anchored ``CreditLedgerEntry`` rows.
2. Batches them according to the configured ``batch_size``.
3. Calls :meth:`AnchoringService.anchor_batch` to submit the Merkle
   root on-chain.
4. Persists the resulting :class:`AnchorRecord` and updates each
   entry's ``anchor_id`` inside a single database transaction.

The loop is designed to be resilient: a failed anchoring attempt logs
the error and retries on the next cycle without losing any entries.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.ledger.anchor.config import AnchorConfig
    from core.ledger.anchor.models import AnchorRecord, CreditLedgerEntry
    from core.ledger.anchor.service import AnchoringService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database access protocol
# ---------------------------------------------------------------------------

class EntryRepository(Protocol):
    """Minimal interface for accessing ledger entries.

    Implementations can use SQLAlchemy async sessions, raw SQL, or any
    other data-access strategy.
    """

    async def fetch_unanchored(self, limit: int) -> Sequence[CreditLedgerEntry]:
        """Return up to *limit* entries where ``anchor_id IS NULL``."""
        ...

    async def save_anchor(
        self,
        record: AnchorRecord,
        entry_ids: Sequence[int],
    ) -> None:
        """Persist *record* and set ``anchor_id`` on each entry in *entry_ids*.

        This MUST be done atomically (single transaction).
        """
        ...


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------

async def run_bundler_loop(
    service: AnchoringService,
    repo: EntryRepository,
    config: AnchorConfig,
) -> None:
    """Run the anchoring loop until cancelled.

    This coroutine is intended to be launched as an ``asyncio.Task`` at
    application startup::

        task = asyncio.create_task(
            run_bundler_loop(service, repo, config)
        )

    Cancel the task during shutdown to stop gracefully.
    """
    if not config.enabled:
        logger.info("Anchoring is disabled (ANCHOR_ENABLED != true). Exiting loop.")
        return

    logger.info(
        "Bundler loop started: batch_size=%d, interval=%ds",
        config.batch_size,
        config.interval_seconds,
    )

    while True:
        try:
            await _run_once(service, repo, config.batch_size)
        except asyncio.CancelledError:
            logger.info("Bundler loop cancelled. Shutting down gracefully.")
            raise
        except Exception:
            logger.exception("Anchoring cycle failed. Will retry next interval.")

        await asyncio.sleep(config.interval_seconds)


async def _run_once(
    service: AnchoringService,
    repo: EntryRepository,
    batch_size: int,
) -> None:
    """Execute a single anchoring cycle.

    Fetches un-anchored entries, batches them, anchors, and persists
    results.  Multiple batches may be processed in a single cycle if
    there are more un-anchored entries than ``batch_size``.
    """
    entries = await repo.fetch_unanchored(limit=batch_size)

    if not entries:
        logger.debug("No un-anchored entries found. Sleeping.")
        return

    logger.info("Processing %d un-anchored entries.", len(entries))

    record = service.anchor_batch(entries)
    entry_ids = [e.id for e in entries]

    await repo.save_anchor(record, entry_ids)

    logger.info(
        "Anchor saved: record_id=%s tx=%s entries=%d",
        record.id,
        record.tx_hash,
        record.entry_count,
    )
