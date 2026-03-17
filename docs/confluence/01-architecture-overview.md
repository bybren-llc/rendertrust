# Architecture Overview

**Parent**: [RenderTrust System Documentation](00-system-documentation-home.md)

---

## Component Architecture

RenderTrust is composed of five major subsystems:

### 1. Gateway (core/)

The central FastAPI application that handles all client requests, manages authentication, processes payments, dispatches jobs, and coordinates the edge network.

**Key Modules:**
- `core/main.py` — App factory with lifespan, middleware stack, and convenience endpoints
- `core/config.py` — Pydantic-based settings (loaded from `.env`)
- `core/database.py` — Async SQLAlchemy engine + session factory
- `core/metrics.py` — Prometheus metric definitions
- `core/api/v1/` — All REST API route groups (9 routers)
- `core/auth/` — JWT tokens, blacklist, rate limiting
- `core/billing/` — Stripe webhooks, credit ledger, usage tracking, payouts
- `core/scheduler/` — Node models, Ed25519 crypto, registration, fleet management, dispatch
- `core/storage/` — S3-compatible object storage abstraction
- `core/relay/` — WebSocket relay server for edge nodes
- `core/ledger/` — Blockchain anchoring with Merkle trees

### 2. Edge Kit (edgekit/)

The edge node runtime that runs on operator machines. Connects to the gateway via WebSocket, receives jobs, executes them via plugins, and reports results.

**Key Modules:**
- `edgekit/entrypoint.py` — Node startup and lifecycle management
- `edgekit/cli/register.py` — Node registration CLI
- `edgekit/relay/client.py` — WebSocket relay client with auto-reconnect
- `edgekit/workers/executor.py` — Job execution with resource limits
- `edgekit/workers/plugins/` — Plugin system (echo, CPU benchmark)
- `edgekit/health.py` — Health check HTTP server

### 3. Creator Desktop App (frontend/)

Electron + React 18 desktop application for job submitters. Provides authentication, job submission, status tracking, credit management, and result downloads.

**Key Modules:**
- `frontend/src/contexts/AuthContext.tsx` — JWT state management with auto-refresh
- `frontend/src/pages/` — Login, Register, Dashboard, Jobs, Credits, Settings
- `frontend/src/hooks/` — useJobs, useCredits custom hooks
- `frontend/src/lib/api.ts` — HTTP client with JWT auto-attach

### 4. Community Portal (community/)

Next.js 14 public-facing leaderboard showing top node operators by jobs completed, uptime, and earnings.

### 5. Blockchain Layer (rollup_anchor/)

Solidity smart contracts for anchoring credit ledger Merkle roots on-chain, providing tamper-evident auditability.

---

## Data Flow: Job Lifecycle

```
1. SUBMISSION
   Creator App/SDK → POST /api/v1/jobs/dispatch → Gateway

2. DISPATCH
   Gateway → find_best_node() (least-loaded, HEALTHY, matching capability)
          → Create JobDispatch record (status=DISPATCHED)
          → Push to Redis queue: queue:node:{node_id}

3. RELAY
   Gateway WebSocket Server → sends job_dispatch message → Edge Node

4. EXECUTION
   Edge Node → WorkerExecutor → Plugin.execute()
            → Sends status updates (RUNNING → COMPLETED/FAILED)

5. RESULT UPLOAD
   Edge Node → upload_result() → S3/R2 storage
            → Sets result_ref on JobDispatch

6. RETRIEVAL
   Creator App/SDK → GET /api/v1/jobs/{id}/result → presigned URL → download

7. BILLING
   Gateway → deduct_on_completion() → credit ledger entry
          → Bundler batches entries → Merkle root → on-chain anchor
```

---

## Database Schema

```
┌──────────────┐     ┌───────────────────────┐
│    users     │     │   credit_ledger_      │
│──────────────│     │      entries          │
│ id (UUID PK) │◄────│ user_id (FK)         │
│ email        │     │ amount               │
│ name         │     │ direction            │
│ hashed_pwd   │     │ source               │
│ is_active    │     │ reference_id         │
│ is_admin     │     │ balance_after        │
│ created_at   │     │ anchor_id (FK)       │
│ updated_at   │     └───────────┬──────────┘
└──────┬───────┘                 │
       │                  ┌──────▼──────────┐
       │                  │ anchor_records  │
┌──────▼───────┐          │─────────────────│
│   projects   │          │ merkle_root     │
│──────────────│          │ tx_hash         │
│ id (UUID PK) │          │ block_number    │
│ name         │          │ entry_count     │
│ description  │          │ anchored_at     │
│ owner_id(FK) │          └─────────────────┘
└──────────────┘
                          ┌─────────────────┐
┌──────────────┐          │  job_dispatches  │
│  edge_nodes  │◄─────────│─────────────────│
│──────────────│ node_id  │ id (UUID PK)    │
│ id (UUID PK) │          │ job_type        │
│ public_key   │          │ payload_ref     │
│ name         │          │ status          │
│ capabilities │          │ result_ref      │
│ status       │          │ error_message   │
│ last_heartbt │          │ retry_count     │
│ current_load │          │ queued_at       │
│ metadata     │          │ dispatched_at   │
└──────────────┘          │ completed_at    │
                          └────────┬────────┘
                                   │
                          ┌────────▼────────┐
                          │ dead_letter_    │
                          │     queue       │
                          │─────────────────│
                          │ job_id (FK)     │
                          │ original_payload│
                          │ error_history   │
                          │ failed_at       │
                          │ retry_count     │
                          └─────────────────┘

┌─────────────────┐
│  job_pricing    │
│─────────────────│
│ job_type (UQ)   │
│ credits_per_unit│
│ unit_type       │
│ is_active       │
└─────────────────┘
```

**Tables**: users, projects, credit_ledger_entries, edge_nodes, job_dispatches, dead_letter_queue, job_pricing, anchor_records

**Migrations**: 6 Alembic versions (0001-0006)

---

## Network Topology (Production)

```
Internet
    │
    ▼
Cloudflare (DNS + WAF + Tunnel)
    │ (encrypted, outbound-only)
    ▼
Hetzner VPS (Coolify)
    ├── FastAPI Gateway (:8000)
    ├── PostgreSQL 16 (:5432)
    ├── Redis 7 (:6379)
    ├── MinIO/R2 (object storage)
    ├── Prometheus (:9090)
    ├── Grafana (:3000)
    ├── Loki (:3100)
    └── Promtail (log shipper)

Edge Nodes (distributed)
    ├── Edge Node 1 (WebSocket → Gateway)
    ├── Edge Node 2 (WebSocket → Gateway)
    └── Edge Node N (WebSocket → Gateway)
```

---

## Middleware Stack (Request Processing Order)

1. **Cloudflare WAF** — SQL injection, XSS, path traversal blocking; rate limiting
2. **RequestIdMiddleware** — Adds `X-Request-ID` header for distributed tracing
3. **PrometheusMiddleware** — Records HTTP request count and latency
4. **SecurityHeadersMiddleware** — OWASP headers (nosniff, DENY, XSS protection, HSTS)
5. **CORSMiddleware** — Cross-origin request policy enforcement
6. **Route Handler** — FastAPI endpoint logic

---

*MIT License | Copyright (c) 2026 ByBren, LLC*
