<!-- Copyright 2026 ByBren, LLC. Licensed under the Apache License, Version 2.0. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# REN-47: Credit Ledger Integration

| Field            | Value                                      |
|------------------|--------------------------------------------|
| **Linear Ticket**| [REN-47](https://linear.app/cheddarfox/issue/REN-47) |
| **SAFe Type**    | Feature                                    |
| **Status**       | IN PROGRESS                                |
| **Priority**     | High                                       |
| **Story Points** | 13                                         |
| **PI / Sprint**  | Phase I / Sprint 2                         |

---

## Overview

Implement the credit ledger system that tracks computational service credits across the RenderTrust trust fabric. The ledger handles Stripe webhook-driven credit allocation, balance queries, usage metering, and provides the financial backbone for all billable operations regardless of the computational service type.

Every job dispatched through RenderTrust (rendering, inference, simulation, etc.) consumes credits. This feature ensures accurate, auditable, and idempotent credit accounting.

## User Story

As a **platform operator**, I want credits allocated automatically when a customer pays via Stripe, so that customers can immediately consume computational services without manual intervention.

As a **service consumer**, I want to query my credit balance and usage history, so that I can monitor spending and plan resource allocation.

## Acceptance Criteria

- [ ] Stripe `checkout.session.completed` webhook allocates credits to user ledger
- [ ] Stripe `invoice.paid` webhook allocates subscription credits
- [ ] All ledger mutations are idempotent (replay-safe via Stripe event ID)
- [ ] `GET /api/v1/credits/balance` returns current balance for authenticated user
- [ ] `GET /api/v1/credits/history` returns paginated ledger entries with filters
- [ ] `POST /api/v1/credits/deduct` atomically deducts credits (returns 402 if insufficient)
- [ ] Ledger entries record: amount, direction (credit/debit), source, reference_id, timestamp
- [ ] All balance mutations use database-level row locking (SELECT FOR UPDATE)
- [ ] Webhook signature verification rejects forged payloads
- [ ] Credit balance never goes negative (database CHECK constraint)

## Technical Approach

### Data Model

```
CreditLedgerEntry
├── id: UUID (PK)
├── user_id: UUID (FK → users)
├── amount: Decimal(12,4)
├── direction: Enum(CREDIT, DEBIT)
├── source: Enum(STRIPE, USAGE, ADJUSTMENT, REFUND)
├── reference_id: String (Stripe event ID / job ID)
├── balance_after: Decimal(12,4)
├── description: String
├── created_at: DateTime (UTC)
└── UNIQUE(reference_id, direction)  -- idempotency
```

### API Endpoints

| Method | Path                      | Auth     | Purpose                    |
|--------|---------------------------|----------|----------------------------|
| POST   | `/api/v1/webhooks/stripe` | Stripe sig | Webhook receiver          |
| GET    | `/api/v1/credits/balance` | JWT      | Current balance             |
| GET    | `/api/v1/credits/history` | JWT      | Paginated ledger entries    |
| POST   | `/api/v1/credits/deduct`  | JWT+internal | Atomic deduction (service-to-service) |

### Key Decisions

- **#PATH_DECISION**: Double-entry style ledger (running balance_after on each entry) over separate balance table -- enables audit trail, self-healing reconciliation
- **#PATH_DECISION**: Idempotency via UNIQUE(reference_id, direction) constraint -- database-enforced, no distributed locks needed
- **#PLAN_UNCERTAINTY**: Credit pricing model (flat rate vs. tiered) deferred to product decision; ledger is amount-agnostic

### Patterns Referenced

- `patterns_library/api/webhook-handler.md` -- Stripe webhook verification pattern
- `patterns_library/security/input-sanitization.md` -- request validation
- `patterns_library/security/rate-limiting.md` -- webhook endpoint protection

## Dependencies

| Dependency             | Status     | Notes                            |
|------------------------|------------|----------------------------------|
| REN-61 (Core Platform) | Complete   | FastAPI, SQLAlchemy, Alembic     |
| Stripe webhook handler | Exists     | `core/billing/stripe/`           |
| User model             | Exists     | `core/models/base.py`           |
| JWT auth middleware     | Exists     | `core/auth/`                    |
| Alembic migrations     | Ready      | Migration scaffold in place      |

## Implementation Plan

1. Create `core/ledger/models.py` -- CreditLedgerEntry SQLAlchemy model
2. Create Alembic migration for ledger table with CHECK constraints
3. Create `core/ledger/service.py` -- business logic (allocate, deduct, balance)
4. Create `core/ledger/router.py` -- FastAPI endpoints
5. Wire Stripe webhook handler to ledger service
6. Add integration tests against test PostgreSQL

## Testing Strategy

- **Unit**: Ledger service logic (allocate, deduct, insufficient balance)
- **Integration**: Stripe webhook → ledger entry creation (using Stripe test events)
- **Idempotency**: Replay same webhook event; verify no duplicate entries
- **Concurrency**: Parallel deduction requests; verify no race conditions
- **Edge Cases**: Zero-amount events, negative amounts rejected, overflow protection
- **Coverage Target**: 90%+ on `core/ledger/`

## Security Considerations

- **OWASP A01 (Broken Access Control)**: Users can only query their own balance/history; deduct endpoint is internal-only
- **OWASP A04 (Insecure Design)**: Database CHECK constraint prevents negative balances; row locking prevents race conditions
- **OWASP A08 (Software Integrity)**: Stripe webhook signature verification (`stripe.Webhook.construct_event`) on every request
- **OWASP A09 (Security Logging)**: All credit mutations logged with user_id, amount, source for audit trail
- **#EXPORT_CRITICAL**: Stripe webhook secret stored in environment variable, never in code
- **Financial Integrity**: Decimal(12,4) precision; no floating-point arithmetic on monetary values
