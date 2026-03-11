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

"""x402 PoC endpoints for payment-gated compute.

These endpoints demonstrate x402 integration. In production, these would
be replaced by actual edge node compute endpoints.
"""

from __future__ import annotations

import hashlib
import time
import uuid

import structlog
from fastapi import APIRouter

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/x402", tags=["x402-poc"])


@router.post("/compute")
async def x402_compute():
    """PoC compute endpoint behind x402 payment wall.

    When x402 middleware is active, this endpoint returns 402 Payment Required
    for unpaid requests. Paid requests receive a simulated compute result.

    Returns:
        dict with job_id, result hash, compute time, and status.
    """
    # Simulate compute work
    job_id = str(uuid.uuid4())
    start = time.monotonic()

    # Simulate a lightweight hash computation
    data = f"compute-result-{job_id}-{time.time()}"
    result_hash = hashlib.sha256(data.encode()).hexdigest()

    elapsed_ms = (time.monotonic() - start) * 1000

    logger.info(
        "x402_compute_completed",
        job_id=job_id,
        elapsed_ms=round(elapsed_ms, 2),
    )

    return {
        "job_id": job_id,
        "result_hash": result_hash,
        "compute_time_ms": round(elapsed_ms, 2),
        "status": "completed",
        "payment_verified": True,
    }


@router.get("/pricing")
async def x402_pricing():
    """Return current x402 pricing information.

    This is a free endpoint (not behind x402 wall) that returns
    the current pricing for paid endpoints.
    """
    return {
        "endpoints": {
            "POST /api/v1/x402/compute": {
                "price_usd": "0.01",
                "network": "eip155:84532",
                "asset": "USDC",
                "scheme": "exact",
            },
        },
        "facilitator": "https://x402.org/facilitator",
        "note": "PoC -- Base Sepolia testnet only",
    }
