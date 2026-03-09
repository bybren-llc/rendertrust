<!-- SPDX-License-Identifier: MIT -->
<!-- Copyright 2025-2026 ByBren, LLC. See LICENSE-MIT for terms. -->

# Legacy Billing Code Migration Audit

**Date**: 2026-03-09
**Author**: Backend Developer Agent
**Linear**: REN-87
**Status**: Complete

## Summary

5 files across `core/billing/` and `core/gateway/` import from a nonexistent `db` module
that was part of a prior codebase (likely the original WTFB/AgentSpace prototype). None of
these files can execute in the current RenderTrust project. All must be migrated to use the
project's SQLAlchemy 2.x + Alembic async patterns before any billing or fleet functionality
is operational.

No `core/database.py` module exists yet. No SQLAlchemy ORM models exist for `Ledger`,
`UsageEvent`, or `Creator`. The only database artifacts are raw SQL migration files at
`core/billing/migrations/20240501_usage_events.sql` and
`core/gateway/web/ui/migrations/20240503_fleet_view.sql`.

## File-by-File Analysis

### 1. core/billing/webhook.py

- **Purpose**: Receives AgentSpace usage webhook events. Records usage, computes platform
  fees based on a tiered threshold, and writes three-way ledger entries (debit creator,
  credit module owner, credit platform).
- **Lines of code**: 37
- **Legacy imports**: `from db import async_session, UsageEvent, Ledger`
- **Models used**: `UsageEvent` (ORM), `Ledger` (ORM) -- neither model exists anywhere in
  the codebase.
- **Database patterns**:
  - Uses `async with async_session() as s:` (context-manager factory pattern from legacy `db`)
  - ORM-based queries: `select(UsageEvent)`, `func.sum(UsageEvent.gross_usd)`
  - Direct `s.add()` / `s.add_all()` / `s.commit()`
- **Business logic**:
  - Idempotency check via `event_id` lookup
  - `PLATFORM_FEE = 0.15` (15%) applied only after module exceeds `THRESHOLD = 1000.0` USD
  - Three ledger entries per usage event (debit creator, credit module, credit platform)
- **Security issues**:
  - No authentication or authorization check on the webhook endpoint
  - No input validation (trusts `req.json()` blindly; no Pydantic/Zod schema)
  - No webhook signature verification
  - Hardcoded fee constants instead of configuration
  - No rate limiting
  - Account IDs constructed from user input without sanitization (`f"module:{ue.module_id}"`)
- **Test coverage**: `core/billing/tests/test_webhook.py` exists but uses `TestClient`
  synchronously against the async endpoint, imports `from webhook import router` (relative
  import that would also fail), and does not mock the database.
- **Migration effort**: **HIGH**
  - Requires `UsageEvent` and `Ledger` SQLAlchemy models to be created
  - Requires `async_session` to be replaced with `core.database` async session factory
  - Needs Pydantic request validation schema
  - Needs webhook authentication (signature verification or API key)
  - Needs structured logging
  - Test must be rewritten with proper async test fixtures and database mocking
- **Recommendation**: Rewrite as part of the Credit Ledger System work (REN-21) and
  Credit-Ledger Integration (REN-47). This file encapsulates core billing logic that
  should be designed alongside the ledger models.
- **Depends on**: REN-21 (Credit Ledger System), REN-29 (Database Schema)

---

### 2. core/billing/stripe/ledger/credit.py

- **Purpose**: Single function `credit()` that adds a positive ledger entry for a creator
  when they purchase credits via Stripe.
- **Lines of code**: 5
- **Legacy imports**: `from db import async_session, Ledger`
- **Models used**: `Ledger` (ORM) -- does not exist.
- **Database patterns**:
  - `async with async_session() as s:` -- same legacy factory pattern
  - `s.add(Ledger(...))` / `s.commit()`
- **Business logic**: Creates a single `Ledger` row with `account_id=creator_id` and
  `delta_usd=amount`. No validation on amount sign or magnitude.
- **Callers**: Called by `core/billing/stripe/stripe_webhook.py` (Stripe webhook handler)
  via `from ledger.credit import credit`.
- **Security issues**:
  - No validation that `amount > 0` (could credit negative amounts)
  - No validation that `creator_id` is a valid account
  - No idempotency protection (double-credit possible if Stripe delivers duplicate events)
- **Migration effort**: **LOW**
  - Tiny function; straightforward once `Ledger` model and `async_session` are available
  - Needs amount validation guard
  - Needs idempotency key parameter
- **Recommendation**: Migrate as part of Stripe integration work. Smallest file, but
  blocked on `Ledger` model creation. Should be one of the first files migrated as a
  proof-of-concept for the new patterns.
- **Depends on**: REN-21 (Credit Ledger System -- Ledger model)

---

### 3. core/billing/stripe/stripe_webhook.py

- **Purpose**: Stripe checkout webhook handler. Verifies Stripe signature, maps SKU to
  credit amount, calls `credit()`.
- **Lines of code**: 22
- **Legacy imports**: None from `db`. Imports `from ledger.credit import credit` (relative).
- **Note**: This file does NOT import from `db` directly but is tightly coupled to
  `credit.py` which does. Included in this audit because it is part of the same call chain
  and will break when `credit.py` breaks.
- **Security issues**:
  - Has Stripe signature verification (good)
  - Uses deprecated `display_items` field (Stripe API v2023-10-16 uses `line_items`)
  - Bare `except Exception` swallows all errors
  - `CREDIT_MAP` hardcoded (should be configuration or database lookup)
  - No structured logging of webhook events
- **Migration effort**: **MEDIUM** (not a `db` import issue, but needs cleanup)
- **Recommendation**: Update alongside `credit.py` migration. Fix Stripe API deprecations.

---

### 4. core/billing/invoice/invoice_builder.py

- **Purpose**: Generates PDF invoices for a given account. Queries ledger entries for the
  previous month, renders an HTML template with Jinja2, converts to PDF with WeasyPrint,
  uploads to S3, returns a pre-signed URL.
- **Lines of code**: 17
- **Legacy imports**: `from db import async_session, Ledger`
- **Models used**: `Ledger` is imported but not used as an ORM model -- the function
  executes a **raw SQL string** against the `ledger_entries` table instead.
- **Database patterns**:
  - `async with async_session() as s:` -- legacy factory
  - `s.execute("""SELECT ... FROM ledger_entries ...""")` -- raw SQL string, not
    parameterized via SQLAlchemy `text()`. Potential SQL injection vector via format
    string interpolation (uses named parameter `:a`, which is safe, but the query is
    passed as a bare string without `text()` wrapper).
- **External dependencies**: `weasyprint`, `jinja2`, `boto3` -- none of these are in
  any `requirements.txt` visible in the billing module.
- **Business logic**:
  - Queries all ledger activity for the previous calendar month
  - Renders using `templates/invoice.html` (Jinja2 template exists at
    `core/billing/invoice/templates/invoice.html`)
  - Uploads PDF to `wtfb-invoices` S3 bucket with 30-day pre-signed URL
- **Security issues**:
  - S3 credentials read from environment variables at module load time (not per-request)
  - `S3_URL`, `S3_KEY`, `S3_SEC` are non-standard env var names (should follow
    `AWS_*` conventions or use IAM roles)
  - Raw SQL query without `text()` wrapper
  - No error handling for S3 upload failures
  - Module-level date calculation (`PERIOD`) means the value is fixed at import time,
    not at invocation time -- stale if process runs across month boundaries
  - Pre-signed URL has 30-day expiry with no access logging
- **Migration effort**: **HIGH**
  - Needs ORM query or properly wrapped `text()` query
  - Needs `async_session` replacement
  - S3 client initialization needs to move to a proper service/dependency injection
  - Date calculation must be moved into the function body
  - Template path needs to be configurable (currently relative to CWD)
  - External dependencies need to be added to project requirements
- **Recommendation**: Rewrite as a proper service class with dependency injection for S3
  and database session. Part of Billing Service work (REN-20).
- **Depends on**: REN-20 (Billing Service), REN-21 (Credit Ledger System)

---

### 5. core/billing/invoice/cron_monthly.py

- **Purpose**: Monthly cron job that iterates all creators, generates invoices via
  `invoice_builder.build()`, and emails each creator their invoice link via Postmark.
- **Lines of code**: 11
- **Legacy imports**: `from db import async_session, Creator`
- **Models used**: `Creator` -- does not exist anywhere in the codebase. The function
  also executes raw SQL `'SELECT id,email FROM creators'` instead of using the ORM model.
- **Database patterns**:
  - `async with async_session() as s:` -- legacy factory
  - `s.execute('SELECT id,email FROM creators')` -- raw SQL, no `text()` wrapper
  - Session used outside of context manager (rows iterated after `async with` block exits,
    which would cause a detached instance error in SQLAlchemy 2.x)
- **External dependencies**: `postmarker` (Postmark email client) -- not in any visible
  `requirements.txt`.
- **Business logic**:
  - Queries all creators from a `creators` table (table does not exist in any migration)
  - Calls `build()` for each creator and emails the result
  - Runs as a standalone script via `asyncio.run(main())`
- **Security issues**:
  - `POSTMARK_KEY` from environment variable (acceptable but should use secrets manager)
  - No error handling -- if one invoice fails, entire cron job crashes
  - No logging of sent emails
  - Email sender is `billing@wtfb.ai` (legacy domain, should be RenderTrust domain)
  - Subject references "WTFB" (legacy branding)
  - Session scope bug: results consumed outside context manager
- **Migration effort**: **HIGH**
  - Needs `Creator` model or equivalent user/account model
  - Needs `async_session` replacement
  - Session scope bug must be fixed
  - Needs proper error handling per-creator (continue on failure)
  - Needs branding update (WTFB to RenderTrust)
  - Should be converted to a Celery/APScheduler task rather than standalone script
  - Email template should be configurable
- **Recommendation**: Rewrite as part of Billing Service work (REN-20). Low priority
  since invoicing is not needed until the platform has paying users.
- **Depends on**: REN-20 (Billing Service), REN-21 (Credit Ledger System),
  REN-29 (Database Schema -- creators table)

---

### 6. core/gateway/web/ui/routes/fleet.py

- **Purpose**: Fleet overview API endpoint. Returns all rows from a `fleet_overview`
  database view for the gateway admin UI.
- **Lines of code**: 9
- **Legacy imports**: `from db import async_session`
- **Models used**: None (raw SQL query against a view).
- **Database patterns**:
  - `async with async_session() as s:` -- legacy factory
  - `s.execute(text('SELECT * FROM fleet_overview'))` -- properly uses `text()` wrapper
  - `dict(r) for r in rows` -- row-to-dict conversion (SQLAlchemy 2.x compatible)
- **Related SQL**: `core/gateway/web/ui/migrations/20240503_fleet_view.sql` defines the
  `fleet_overview` view joining `nodes` and `ledger_entries` tables.
- **Business logic**: Simple read-only endpoint returning fleet node status with earnings.
- **Security issues**:
  - No authentication (fleet data exposed to any caller)
  - No pagination (returns all rows)
  - `SELECT *` may leak internal columns
- **Migration effort**: **LOW**
  - Only needs `async_session` replacement -- no ORM models required
  - Needs authentication middleware
  - Needs pagination
  - View dependency on `ledger_entries` table means it is blocked on ledger migration
- **Recommendation**: Migrate early as the simplest file. Can serve as the pattern
  exemplar for other migrations. Part of Gateway API Routes Integration (REN-55).
- **Depends on**: REN-53 (Gateway Framework), REN-55 (Gateway API Routes)

---

## Missing Models

The following ORM models are referenced by the legacy code but do not exist anywhere in
the codebase. No SQLAlchemy model classes or Alembic migrations exist.

| Model | Referenced In | DB Table | Raw SQL Migration |
|-------|--------------|----------|-------------------|
| `UsageEvent` | `webhook.py` | `usage_events` | `core/billing/migrations/20240501_usage_events.sql` |
| `Ledger` | `webhook.py`, `credit.py`, `invoice_builder.py` | `ledger_entries` | `core/billing/migrations/20240501_usage_events.sql` |
| `Creator` | `cron_monthly.py` | `creators` | None (no migration exists) |

### Schema from Raw SQL Migration (`20240501_usage_events.sql`)

```sql
CREATE TABLE IF NOT EXISTS usage_events (
    event_id      UUID PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    module_id     TEXT NOT NULL,
    creator_id    TEXT NOT NULL,
    units         INTEGER NOT NULL,
    unit_price_usd NUMERIC(10,4) NOT NULL,
    gross_usd     NUMERIC(12,4) GENERATED ALWAYS AS (units * unit_price_usd) STORED
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    account_id    TEXT NOT NULL,
    delta_usd     NUMERIC(12,4) NOT NULL,
    ref_event_id  UUID REFERENCES usage_events(event_id)
);
```

### Missing Database Infrastructure

- No `core/database.py` module (async engine, session factory, Base)
- No `core/models/` directory or model files
- No `alembic/` directory or Alembic configuration
- No `__init__.py` files in any `core/` subdirectory (Python package structure incomplete)

---

## Missing Database View

| View | Referenced In | Raw SQL Migration |
|------|--------------|-------------------|
| `fleet_overview` | `fleet.py` | `core/gateway/web/ui/migrations/20240503_fleet_view.sql` |

The view joins `nodes` (no migration exists) with `ledger_entries`:

```sql
CREATE OR REPLACE VIEW fleet_overview AS
SELECT n.id, n.vram, n.temp, n.uptime,
       COALESCE(SUM(l.delta_usd),0) AS earnings
FROM nodes n
LEFT JOIN ledger_entries l ON l.account_id = CONCAT('node:',n.id)
GROUP BY n.id;
```

---

## Migration Priority

| Priority | File | Effort | Blocking Stories | Rationale |
|----------|------|--------|-----------------|-----------|
| 1 | `core/gateway/web/ui/routes/fleet.py` | LOW | REN-55 | Simplest file; no ORM models needed; establishes migration pattern |
| 2 | `core/billing/stripe/ledger/credit.py` | LOW | REN-47 | 5-line function; proves Ledger model works; unblocks Stripe flow |
| 3 | `core/billing/stripe/stripe_webhook.py` | MEDIUM | REN-47 | Coupled to credit.py; has Stripe API deprecations to fix |
| 4 | `core/billing/webhook.py` | HIGH | REN-21, REN-47 | Core usage tracking; needs UsageEvent + Ledger models + validation |
| 5 | `core/billing/invoice/invoice_builder.py` | HIGH | REN-20 | Heavy rewrite; external deps (weasyprint, boto3); S3 refactor |
| 6 | `core/billing/invoice/cron_monthly.py` | HIGH | REN-20 | Depends on invoice_builder; needs Creator model; session scope bug |

### Prerequisite Work (Must Complete First)

These enablers must be completed before any file migration can begin:

1. **Create `core/database.py`** -- async engine, `async_session_factory`, `Base`
   declarative base (part of REN-29)
2. **Create `Ledger` SQLAlchemy model** in `core/models/ledger.py` (part of REN-21)
3. **Create `UsageEvent` SQLAlchemy model** in `core/models/usage_event.py` (part of REN-21)
4. **Create Alembic configuration** and initial migration (part of REN-29)
5. **Add `__init__.py` files** throughout `core/` for proper Python packaging

---

## Dependency Map

```
REN-29 (Database Schema & Migrations)
  |
  +---> core/database.py (async engine, session factory)
  +---> alembic/ (migration framework)
  |
  v
REN-21 (Credit Ledger System)
  |
  +---> core/models/ledger.py (Ledger model)
  +---> core/models/usage_event.py (UsageEvent model)
  |
  v
REN-47 (Credit-Ledger Integration)
  |
  +---> Migrate credit.py (#2 priority)
  +---> Migrate stripe_webhook.py (#3 priority)
  +---> Migrate webhook.py (#4 priority)
  |
  v
REN-20 (Billing Service)
  |
  +---> Migrate invoice_builder.py (#5 priority)
  +---> Migrate cron_monthly.py (#6 priority)

REN-53 (Gateway Framework)
  |
  v
REN-55 (Gateway API Routes)
  |
  +---> Migrate fleet.py (#1 priority)
```

---

## Cross-Cutting Concerns

### Legacy Branding

Multiple files reference "WTFB" or "wtfb" (the prior project name):

- `webhook.py`: account ID `"wtfb_platform"`
- `invoice_builder.py`: S3 bucket `'wtfb-invoices'`
- `cron_monthly.py`: email sender `billing@wtfb.ai`, subject `WTFB Invoice`
- `invoice.html`: heading `WTFB Invoice`

All must be updated to RenderTrust branding during migration.

### Missing External Dependencies

These packages are imported by legacy files but are not in any `requirements.txt` or
`pyproject.toml` in the project:

| Package | Used By | Purpose |
|---------|---------|---------|
| `weasyprint` | `invoice_builder.py` | HTML-to-PDF conversion |
| `jinja2` | `invoice_builder.py` | HTML template rendering |
| `boto3` | `invoice_builder.py` | S3 upload for invoice PDFs |
| `postmarker` | `cron_monthly.py` | Postmark transactional email |

### Test Gaps

- `test_webhook.py` is the only test file; it tests `webhook.py` (the AgentSpace
  usage webhook), not the Stripe webhook.
- The test uses `TestClient` synchronously against an async endpoint -- this works
  in FastAPI's test client but the test does not mock the database, so it would fail
  without a running database with the legacy `db` module.
- No tests exist for: `credit.py`, `stripe_webhook.py`, `invoice_builder.py`,
  `cron_monthly.py`, `fleet.py`.

---

## Recommendations

### Immediate Actions

1. **Create REN-29 sub-task**: Define and implement `core/database.py` with async
   engine configuration, session factory, and SQLAlchemy `Base`.
2. **Create REN-21 sub-task**: Define `Ledger` and `UsageEvent` SQLAlchemy models
   based on the existing raw SQL schema in `20240501_usage_events.sql`.
3. **Create enabler story**: Add `__init__.py` files and establish Python package
   structure across `core/`.

### Migration Strategy

1. **Phase 1 -- Infrastructure** (prerequisite): `core/database.py`, models,
   Alembic setup. Covered by REN-29 and REN-21.
2. **Phase 2 -- Quick wins**: Migrate `fleet.py` and `credit.py` as proof-of-concept.
   These are low-effort files that validate the new patterns work end-to-end.
3. **Phase 3 -- Core billing**: Migrate `webhook.py` with full input validation,
   authentication, and structured logging. Covered by REN-47.
4. **Phase 4 -- Invoice system**: Migrate `invoice_builder.py` and `cron_monthly.py`
   with proper service architecture. Covered by REN-20.

### Do NOT Do

- Do not add deprecation shims or create a fake `db` module as a bridge. The legacy
  files are small enough to rewrite directly.
- Do not attempt to run the legacy code as-is. It will fail on import.
- Do not create the `Creator` model separately from the main database schema design
  (REN-29). User/creator identity should be designed holistically.

---

## Evidence

### Grep Confirmation (all `from db import` references)

```
core/gateway/web/ui/routes/fleet.py:3:from db import async_session
core/billing/webhook.py:3:from db import async_session, UsageEvent, Ledger
core/billing/stripe/ledger/credit.py:1:from db import async_session, Ledger
core/billing/invoice/cron_monthly.py:3:from db import async_session, Creator
core/billing/invoice/invoice_builder.py:2:from db import async_session, Ledger
```

No other files in the repository import from `db`.
