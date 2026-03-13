# Credit & Billing System

**Parent**: [RenderTrust System Documentation](00-system-documentation-home.md)

---

## Overview

RenderTrust uses a **credit-based billing model**. Users purchase credits via Stripe, which are consumed when jobs complete. Every credit transaction is recorded in an immutable ledger that is periodically anchored on-chain.

---

## Credit Packages

| SKU | Credits | Price (USD) | Per Credit |
|-----|---------|-------------|------------|
| `cred10` | 100 | $10.00 | $0.100 |
| `cred50` | 500 | $40.00 | $0.080 |
| `cred100` | 1,000 | $70.00 | $0.070 |

Larger packages offer volume discounts.

---

## Purchase Flow

```
1. User selects package in Creator App
   → CreditPackages component displays options

2. App calls POST /api/v1/credits/checkout { sku: "cred50" }
   → Gateway creates Stripe Checkout Session
   → Returns { url: "https://checkout.stripe.com/..." }

3. User completes payment on Stripe
   → Stripe redirects to app with ?checkout=success&session_id=...

4. Stripe sends webhook: checkout.session.completed
   POST /api/v1/webhooks/stripe
   → Verifies stripe-signature header
   → Extracts user_id from client_reference_id
   → Extracts sku from session metadata
   → Calls allocate_credits() with session ID as reference_id

5. Credits appear in user's balance
   → App detects ?checkout=success, refreshes balance
```

---

## Credit Ledger

### Model: `CreditLedgerEntry`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `user_id` | UUID (FK) | Owner of credits |
| `amount` | Decimal(12,4) | Credit amount (always positive) |
| `direction` | Enum | `CREDIT` (add) or `DEBIT` (subtract) |
| `source` | Enum | `STRIPE`, `USAGE`, `ADJUSTMENT`, `REFUND` |
| `reference_id` | String | Idempotency key (unique per direction) |
| `balance_after` | Decimal(12,4) | Running balance after this entry |
| `description` | String | Human-readable description |
| `anchor_id` | UUID (FK) | Link to blockchain anchor record |
| `created_at` | DateTime | Entry timestamp |

### Constraints

- `UNIQUE(reference_id, direction)` — Prevents duplicate credits/debits
- `CHECK(balance_after >= 0)` — Balance can never go negative

### Concurrency Control

All credit operations use `SELECT ... FOR UPDATE` row locking to prevent race conditions:

```python
# Simplified flow
async with session.begin():
    # Lock the user's latest ledger entry
    last_entry = await session.execute(
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.user_id == user_id)
        .order_by(CreditLedgerEntry.created_at.desc())
        .with_for_update()
        .limit(1)
    )
    current_balance = last_entry.balance_after if last_entry else Decimal("0")

    # For debits, check sufficient balance
    if direction == DEBIT and current_balance < amount:
        raise InsufficientCreditsError(available=current_balance, requested=amount)

    # Create new entry with calculated balance_after
    new_balance = current_balance + amount if direction == CREDIT else current_balance - amount
    entry = CreditLedgerEntry(balance_after=new_balance, ...)
```

---

## Usage Tracking

### Job Pricing

| Job Type | Credits Per Job |
|----------|----------------|
| `render` | 10.0 |
| `inference` | 5.0 |
| `cpu_benchmark` | 1.0 |
| `echo` | 0.0 (free, for testing) |
| Unknown types | 1.0 (fallback) |

Pricing can be overridden via the `job_pricing` database table.

### Deduction Flow

```
1. Job completes (status → COMPLETED)
2. deduct_on_completion() is called
3. Looks up price: DB → DEFAULT_PRICING → FALLBACK_PRICE
4. Creates DEBIT ledger entry with reference_id="job-{job_id}"
5. Idempotent: duplicate calls for same job are no-ops
```

### Pre-Flight Credit Check

Before dispatching a job, the system checks if the user has sufficient credits:

```python
async def check_sufficient_credits(session, user_id, job_type) -> bool:
    price = await get_job_price(session, job_type)
    if price == Decimal("0"):
        return True  # Free jobs always allowed
    balance = await get_balance(session, user_id)
    return balance >= price
```

If insufficient, the dispatch endpoint returns `402 Payment Required`.

---

## Stripe Integration

### Webhook Handler

**Endpoint**: `POST /api/v1/webhooks/stripe`

**Security**:
- Validates `stripe-signature` header presence
- Verifies signature using `stripe.Webhook.construct_event()`
- Catches `SignatureVerificationError` specifically
- Uses server-side settings (not environment variables at module level)
- Logs event_type + event_id for audit trail
- Does NOT log PII or payment details

**Handled Events**:

| Event | Action |
|-------|--------|
| `checkout.session.completed` | Extract user_id + sku → allocate credits |

**Credit Mapping**:
```python
CREDIT_MAP = {
    "cred10": 100,
    "cred50": 550,    # Bonus credits for larger packages
}
```

### Testing with Stripe CLI

```bash
# Terminal 1: Forward webhooks
stripe listen --forward-to localhost:8000/api/v1/webhooks/stripe

# Terminal 2: Trigger test events
stripe trigger checkout.session.completed
```

---

## API Endpoints

### GET /api/v1/credits/balance

Returns the current credit balance for the authenticated user.

**Response**:
```json
{
  "balance": "1000.0000",
  "user_id": "uuid"
}
```

### GET /api/v1/credits/history

Returns paginated transaction history.

**Query Parameters**:
- `limit` (1-100, default 50)
- `offset` (>=0, default 0)

**Response**:
```json
{
  "entries": [
    {
      "id": "uuid",
      "amount": "10.0000",
      "direction": "DEBIT",
      "source": "USAGE",
      "reference_id": "job-abc123",
      "balance_after": "990.0000",
      "description": "Job execution: render",
      "created_at": "2026-03-13T12:00:00Z"
    }
  ],
  "count": 42
}
```

### POST /api/v1/credits/deduct

Manually deducts credits (admin/system use).

**Request**:
```json
{
  "amount": "10.0000",
  "reference_id": "manual-adjustment-001",
  "description": "Manual adjustment"
}
```

**Error Responses**:
- `402 Payment Required` — Insufficient credits
- `422 Unprocessable Entity` — Invalid amount

---

## Payout Service

Monthly earnings calculation for node operators:

```python
# core/billing/payout.py
async def calculate_monthly_payouts(session, month, year):
    # 1. Query all completed jobs for the month
    # 2. Group by node operator
    # 3. Calculate earnings per operator
    # 4. Create payout records
```

---

*MIT License | Copyright (c) 2026 ByBren, LLC*
