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
Anchoring configuration.

All values can be overridden via environment variables prefixed with
``ANCHOR_``.  When ``anchor_enabled`` is ``False`` the background
bundler task is a no-op so anchoring can be safely disabled in
development and CI environments.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AnchorConfig:
    """Configuration for the blockchain anchoring subsystem."""

    # Master switch: set to True to enable background anchoring.
    enabled: bool = False

    # Ethereum JSON-RPC endpoint (e.g. http://127.0.0.1:8545).
    rpc_url: str = ""

    # Address of the deployed LedgerAnchor contract (0x-prefixed).
    contract_address: str = ""

    # Private key of the signer account (hex, no 0x prefix).
    # In production this should come from a secrets manager (e.g. Vault).
    private_key: str = ""

    # Maximum number of un-anchored entries to include in a single batch.
    batch_size: int = 100

    # Interval between anchoring runs (seconds).
    interval_seconds: int = 300

    @classmethod
    def from_env(cls) -> AnchorConfig:
        """Create a config instance from environment variables.

        Recognised variables (all optional):
            ANCHOR_ENABLED            - "true" / "1" to enable
            ANCHOR_RPC_URL            - Ethereum RPC URL
            ANCHOR_CONTRACT_ADDRESS   - deployed contract address
            ANCHOR_PRIVATE_KEY        - signer private key
            ANCHOR_BATCH_SIZE         - entries per batch (int)
            ANCHOR_INTERVAL_SECONDS   - loop interval (int)
        """
        enabled_raw = os.environ.get("ANCHOR_ENABLED", "false").lower()
        return cls(
            enabled=enabled_raw in ("true", "1", "yes"),
            rpc_url=os.environ.get("ANCHOR_RPC_URL", ""),
            contract_address=os.environ.get("ANCHOR_CONTRACT_ADDRESS", ""),
            private_key=os.environ.get("ANCHOR_PRIVATE_KEY", ""),
            batch_size=int(os.environ.get("ANCHOR_BATCH_SIZE", "100")),
            interval_seconds=int(
                os.environ.get("ANCHOR_INTERVAL_SECONDS", "300")
            ),
        )
