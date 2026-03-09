# Copyright 2025 ByBren, LLC
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

"""Stripe webhook handler with signature verification.

Receives and verifies Stripe webhook events. All events are logged
for audit purposes. Signature verification is mandatory -- unsigned
or forged requests are rejected with 400.

Security hardening (REN-69):
- Catches ``stripe.error.SignatureVerificationError`` specifically
  (not a bare ``Exception``).
- Validates that the ``stripe-signature`` header is present before
  attempting verification.
- Uses ``core.config.get_settings()`` for Stripe secrets instead of
  module-level ``os.environ`` access (avoids import-time crashes).
- Logs every webhook event with ``event_type`` and ``event_id`` for
  audit trail.
- Does NOT log PII or payment details.

Testing:
    Use the Stripe CLI for local development::

        stripe listen --forward-to localhost:8000/api/v1/webhooks/stripe
        stripe trigger checkout.session.completed
"""

from __future__ import annotations

import stripe
import structlog
from fastapi import APIRouter, HTTPException, Request, status

from core.config import get_settings

logger = structlog.get_logger(__name__)

router = APIRouter()

# Credit SKU mapping. Kept here for backward compatibility; will be
# moved to database-driven configuration in a future story.
CREDIT_MAP: dict[str, int] = {"cred10": 100, "cred50": 550}


@router.post("/webhooks/stripe")
async def stripe_hook(req: Request) -> dict[str, object]:
    """Handle incoming Stripe webhook events.

    Verifies the webhook signature using the endpoint secret,
    then dispatches the event based on its type. All events are
    acknowledged with ``{"received": True}`` to prevent Stripe
    retries for successfully received (but possibly unhandled)
    event types.

    Returns:
        dict: ``{"received": True}`` on successful processing.

    Raises:
        HTTPException(400): If the signature header is missing,
            the signature is invalid, or the payload cannot be parsed.
    """
    settings = get_settings()

    # -- 1. Validate signature header presence --
    sig = req.headers.get("stripe-signature")
    if not sig:
        logger.warning("stripe_webhook_missing_signature")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing stripe-signature header",
        )

    payload = await req.body()

    # -- 2. Verify signature with specific exception handling --
    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig,
            settings.stripe_webhook_secret,
        )
    except stripe.error.SignatureVerificationError:
        logger.warning("stripe_webhook_invalid_signature")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature",
        ) from None
    except ValueError:
        logger.warning("stripe_webhook_invalid_payload")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payload",
        ) from None

    # -- 3. Audit log: record every received event --
    logger.info(
        "stripe_webhook_received",
        event_type=event["type"],
        event_id=event["id"],
    )

    # -- 4. Route to event-specific handlers --
    if event["type"] == "checkout.session.completed":
        logger.info("stripe_checkout_completed", event_id=event["id"])
        # TODO(REN-79): Implement credit allocation via event handler.
        # The previous implementation used `from ledger.credit import credit`
        # which no longer exists. Credit allocation with idempotency
        # checks will be implemented in REN-79.

    return {"received": True}
