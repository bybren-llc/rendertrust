# RenderTrust

<p align="center">
  <img src="diagrams/RenderTrust_prime_logo.png" alt="RenderTrust Logo" width="300"/>
</p>

<p align="center">
  <strong>The distributed compute trust platform.</strong><br>
  Submit jobs, dispatch to edge nodes, pay with credits, verify on-chain.
</p>

<p align="center">
  <a href="https://github.com/bybren-llc/rendertrust/releases/tag/v1.0.0-alpha">
    <img src="https://img.shields.io/github/v/release/bybren-llc/rendertrust?include_prereleases&label=release&style=flat-square" alt="Release">
  </a>
  <img src="https://img.shields.io/badge/tests-716%20passing-brightgreen?style=flat-square" alt="Tests">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT%20%2F%20Apache--2.0-blue?style=flat-square" alt="License">
  <a href="https://deepwiki.com/ByBren-LLC/rendertrust">
    <img src="https://img.shields.io/badge/DeepWiki-ByBren--LLC%2Frendertrust-blue?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCI+PHBhdGggZD0iTTEyIDJMNCAyQzIuOSAyIDIgMi45IDIgNHY4YzAgMS4xLjkgMiAyIDJoOCI+PC9wYXRoPjxwYXRoIGQ9Ik0yMCAyaC04djEyaDhjMS4xIDAgMi0uOSAyLTJWNGMwLTEuMS0uOS0yLTItMnoiPjwvcGF0aD48cGF0aCBkPSJNMTIgMTR2OCI+PC9wYXRoPjxwYXRoIGQ9Ik04IDIyaDgiPjwvcGF0aD48L3N2Zz4=" alt="DeepWiki">
  </a>
</p>

<p align="center">
  <strong>Built with</strong><br>
  <a href="https://github.com/bybren-llc/safe-agentic-workflow">
    <img src="https://img.shields.io/badge/SAFe_Agent_Harness-ByBren-purple?style=flat-square" alt="SAFe Agent Harness">
  </a>
  <img src="https://img.shields.io/badge/agents-11%20specialized-purple?style=flat-square" alt="Agents">
  <img src="https://img.shields.io/badge/skills-18%20model--invoked-orange?style=flat-square" alt="Skills">
  <img src="https://img.shields.io/badge/patterns-18%20reusable-green?style=flat-square" alt="Patterns">
</p>

---

## What is RenderTrust?

RenderTrust enables users to submit computational jobs (rendering, AI inference, data processing) to a decentralized network of edge nodes. Every transaction is recorded on an immutable, blockchain-anchored credit ledger.

**For creators**: Submit jobs via desktop app, Python SDK, or REST API. Pay with credits. Download results.

**For node operators**: Run an edge node, earn credits for every completed job.

**For developers**: Integrate via Python SDK (sync + async) or the 24-endpoint REST API.

---

## Quick Start

```bash
# Clone
git clone https://github.com/bybren-llc/rendertrust.git
cd rendertrust

# Install (Python 3.11+)
pip install -e '.[dev]'

# Run development stack
docker compose up

# Run tests
pytest tests/ -v

# API docs
open http://localhost:8000/docs
```

---

## Architecture

```
Cloudflare CDN/WAF (DNS, SSL, Rate Limiting)
        |
FastAPI Gateway (core/)
  Auth | Credits | Jobs | Relay | Ledger | Scheduler
  Middleware: CORS, Security Headers, Rate Limit, Prometheus
    /          |          \
PostgreSQL   Redis      S3/R2
   16          7       (MinIO dev)
               |
    WebSocket Relay Server
     /         |         \
Edge Node   Edge Node   Edge Node
(edgekit)   (edgekit)   (edgekit)
```

| Layer | Technology |
|-------|-----------|
| **Backend** | FastAPI (Python 3.11+), Pydantic v2, SQLAlchemy 2.x |
| **Database** | PostgreSQL 16, Alembic migrations |
| **Cache/Queue** | Redis 7 |
| **Frontend** | React 18, Electron 28, Vite 5, Tailwind CSS |
| **Payments** | Stripe Checkout + Webhooks |
| **Auth** | JWT (refresh rotation) + Ed25519 node crypto |
| **Storage** | S3-compatible (Cloudflare R2 / MinIO) |
| **Blockchain** | Solidity (LedgerAnchor.sol), Hardhat, Web3.py |
| **Monitoring** | Prometheus, Grafana, Loki, Promtail |
| **Deployment** | Coolify (Hetzner), Cloudflare Tunnel, Docker |
| **SDK** | Python (httpx), sync + async clients |
| **Community** | Next.js 14 (operator leaderboard) |

---

## Core Subsystems

### Authentication & Security (`core/auth/`)

- JWT access tokens (30 min) + refresh tokens (7 day) with rotation
- Ed25519 keypair authentication for edge nodes
- Redis-backed token blacklist and rate limiting
- OWASP security headers, CORS, input validation (Pydantic v2)
- AES-256-GCM encryption at rest for stored payloads

> **Docs**: [docs/confluence/03-authentication-security.md](docs/confluence/03-authentication-security.md)

### Credit & Billing (`core/billing/`)

- Stripe Checkout for credit purchases (100/$10, 500/$40, 1000/$70)
- Immutable credit ledger with `SELECT FOR UPDATE` row locking
- Idempotent operations via `UNIQUE(reference_id, direction)` constraint
- `CHECK(balance_after >= 0)` — balance can never go negative
- Automatic deduction on job completion, pre-flight credit check on dispatch

> **Docs**: [docs/confluence/04-credit-billing.md](docs/confluence/04-credit-billing.md)

### Global Scheduler (`core/scheduler/`)

- Least-loaded dispatch algorithm across healthy nodes
- Ed25519 node registration with challenge-response
- Heartbeat-based health monitoring (REGISTERED → HEALTHY → UNHEALTHY → OFFLINE)
- Redis job queues per node (`queue:node:{node_id}`)
- Fleet listing and admin endpoints

> **Docs**: [docs/confluence/05-scheduler-dispatch.md](docs/confluence/05-scheduler-dispatch.md)

### Edge Node System (`edgekit/`)

- WebSocket relay client with auto-reconnect (exponential backoff)
- Worker executor with resource limits (timeout, memory, CPU)
- Plugin system: `BaseWorkerPlugin` → implement `execute()` for any job type
- Built-in plugins: Echo (test), CPU Benchmark
- Docker deployment with health checks

> **Docs**: [docs/confluence/06-edge-node-system.md](docs/confluence/06-edge-node-system.md)

### Object Storage (`core/storage/`)

- S3-compatible abstraction (Cloudflare R2 prod, MinIO dev)
- User-scoped keys: `{user_id}/{job_id}/{filename}`
- Presigned download URLs (1 hour default, max 24 hours)
- Path traversal protection (no `..`, no leading `/`, no null bytes)
- AES-256-GCM encryption at rest

> **Docs**: [docs/confluence/07-object-storage.md](docs/confluence/07-object-storage.md)

### Blockchain Anchoring (`core/ledger/anchor/`)

- SHA-256 Merkle tree over batches of ledger entries
- Background bundler task (hourly, configurable batch size)
- LedgerAnchor.sol smart contract (Ethereum/L2)
- Proof verification API: get proof, verify on-chain, list anchors
- NoOpChainClient for development, Web3ChainClient for production

> **Docs**: [docs/confluence/08-blockchain-anchoring.md](docs/confluence/08-blockchain-anchoring.md)

### Error Handling & Resilience (`core/scheduler/`)

- Job retry with exponential backoff (3 attempts: 1s, 2s, 4s)
- Dead letter queue for exhausted retries
- Circuit breaker: 3 consecutive node failures → UNHEALTHY
- Auto-scale triggers via Redis pubsub

> **Docs**: [docs/confluence/05-scheduler-dispatch.md](docs/confluence/05-scheduler-dispatch.md)

### Creator Desktop App (`frontend/`)

- Electron 28 + React 18 + Vite 5 + Tailwind CSS
- Auth flow: login, register, JWT auto-refresh
- Job submission, status tracking (auto-refresh), result download
- Credit dashboard: balance, 7-day usage chart, transaction history, Stripe checkout
- Responsive design (desktop table + mobile cards)

> **Docs**: [docs/confluence/11-user-guide-creator.md](docs/confluence/11-user-guide-creator.md)

### Python SDK (`sdk/python/`)

- Sync client: `RenderTrustClient` + Async client: `AsyncRenderTrustClient`
- Methods: `login()`, `submit_job()`, `get_job()`, `list_jobs()`, `cancel_job()`, `download_result()`, `get_balance()`
- Typed exceptions: `AuthenticationError`, `InsufficientCreditsError`, `NotFoundError`
- Context manager support, httpx-based

> **Docs**: [docs/confluence/14-user-guide-developer.md](docs/confluence/14-user-guide-developer.md)

### Community Portal (`community/`)

- Next.js 14 with App Router
- Public operator leaderboard (jobs completed, uptime, earnings)
- Real-time data refresh (60-second polling)

### Monitoring (`ci/grafana/`, `ci/loki/`)

- Prometheus metrics: HTTP requests, job pipeline, fleet health, credits, WebSocket connections
- Grafana dashboards: API performance, job pipeline, fleet health, credits
- Alerting: FleetTooFewNodes, HighErrorRate, HighJobFailureRate, APILatencyHigh
- Loki + Promtail: structured JSON logging with request_id correlation

> **Docs**: [docs/confluence/09-infrastructure-deployment.md](docs/confluence/09-infrastructure-deployment.md)

---

## API Endpoints (24 total)

| Group | Endpoints | Auth |
|-------|-----------|------|
| **Health** | `GET /health`, `/version`, `/metrics`, `/api/v1/health/ready` | None |
| **Auth** | `POST /api/v1/auth/{register,login,refresh,logout}` | Varies |
| **Credits** | `GET /api/v1/credits/{balance,history}`, `POST .../deduct` | Bearer |
| **Jobs** | `POST .../dispatch`, `GET .../jobs`, `GET .../{id}`, `POST .../{id}/cancel`, `GET .../{id}/result` | Bearer |
| **Nodes** | `POST /api/v1/nodes/{register,heartbeat}` | None / Node JWT |
| **Relay** | `WS /api/v1/relay/ws/{node_id}` | Query JWT |
| **Webhooks** | `POST /api/v1/webhooks/stripe` | Stripe Signature |
| **Ledger** | `GET /api/v1/ledger/{id}/proof`, `.../verify`, `/anchors` | Bearer |

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs) (Swagger UI) | [http://localhost:8000/redoc](http://localhost:8000/redoc) (ReDoc)

> **Full Reference**: [docs/confluence/10-api-reference.md](docs/confluence/10-api-reference.md)

---

## Repository Structure

```
rendertrust/
├── core/                        # FastAPI gateway (Apache 2.0)
│   ├── main.py                  #   App factory, middleware, lifespan
│   ├── config.py                #   Pydantic settings from .env
│   ├── database.py              #   Async SQLAlchemy engine + sessions
│   ├── metrics.py               #   Prometheus metric definitions
│   ├── models/                  #   SQLAlchemy domain models
│   ├── api/v1/                  #   REST API routes (9 routers)
│   ├── auth/                    #   JWT, blacklist, rate limiting
│   ├── billing/                 #   Stripe webhook, credit ledger, usage, payout
│   ├── scheduler/               #   Edge node models, crypto, dispatch, fleet
│   ├── storage/                 #   S3 abstraction, encryption
│   ├── relay/                   #   WebSocket server, manager, TLS
│   ├── ledger/                  #   Blockchain anchoring, Merkle tree
│   └── gateway/                 #   x402 payment protocol (PoC)
├── edgekit/                     # Edge node runtime (Apache 2.0)
│   ├── relay/client.py          #   WebSocket relay client
│   ├── workers/executor.py      #   Job execution with resource limits
│   ├── workers/plugins/         #   Echo, CPU benchmark plugins
│   └── cli/register.py          #   Node registration CLI
├── frontend/                    # Creator desktop app (MIT)
│   ├── electron/                #   Electron main process
│   └── src/                     #   React 18 + Vite + Tailwind
├── community/                   # Next.js 14 leaderboard portal (MIT)
├── sdk/python/                  # Python SDK — sync + async (MIT)
├── rollup_anchor/               # Solidity smart contracts (Enterprise)
│   ├── contracts/               #   LedgerAnchor.sol
│   └── bundler.py               #   Merkle root submission
├── alembic/                     # Database migrations (6 versions)
├── tests/                       # 716 tests (unit + integration + e2e)
├── docs/                        # Documentation
│   ├── confluence/              #   15-page system documentation suite
│   ├── api/openapi.json         #   Pre-exported OpenAPI 3.1 spec
│   ├── adr/                     #   Architecture Decision Records
│   ├── arch/                    #   Architecture manual
│   ├── dr/                      #   Disaster recovery runbook
│   ├── spikes/                  #   Technical spikes (x402 evaluation)
│   └── security/                #   Security documentation
├── ci/                          # CI/CD and infrastructure (MIT)
│   ├── grafana/                 #   Dashboard provisioning
│   ├── loki/                    #   Loki, Promtail, Grafana datasource configs
│   └── deploy.sh                #   Zero-downtime deploy script
├── loadtest/                    # k6 load testing harness (MIT)
├── specs/                       # SAFe specifications
├── patterns_library/            # Reusable code patterns (7 categories)
├── CLAUDE.md                    # AI assistant context
├── AGENTS.md                    # SAFe agent team reference
├── CONTRIBUTING.md              # Git workflow, commit standards, PR process
├── CHANGELOG.md                 # v1.0.0-alpha release notes
├── docker-compose.yml           # Development stack
├── docker-compose.prod.yml      # Production (hardened)
├── docker-compose.test.yml      # Test runner (ephemeral)
├── docker-compose.edge.yml      # Edge node deployment
└── pyproject.toml               # Python project config + dependencies
```

---

## Development

### Prerequisites

- Python 3.11+
- Docker & Docker Compose v2
- Node.js 18+ (for frontend and contracts)
- PostgreSQL 16 (or use Docker)

### Setup

```bash
# Install Python dependencies
pip install -e '.[dev]'

# Start infrastructure (PostgreSQL, Redis, MinIO)
docker compose up -d db redis minio

# Run database migrations
alembic upgrade head

# Start the gateway
uvicorn core.main:app --reload --port 8000

# Start the frontend (separate terminal)
cd frontend && npm install && npm run dev
```

### Testing

```bash
# Unit tests (SQLite, no external deps)
pytest tests/ -v

# Integration tests (requires PostgreSQL + Redis)
pytest tests/integration/ -v

# E2E tests (Docker)
make test-e2e

# With Docker (recommended for CI parity)
docker run --rm -v $(pwd):/app -w /app python:3.11-slim \
  bash -c "pip install -q '.[dev]' && python -m pytest tests/ -v"
```

### Code Quality

```bash
ruff check .              # Lint
ruff check . --fix        # Auto-fix
mypy .                    # Type check
make ci                   # Full CI validation (REQUIRED before PR)
```

### Database Migrations

```bash
alembic revision --autogenerate -m "description"   # Create
alembic upgrade head                                # Apply
alembic downgrade -1                                # Rollback
```

---

## Deployment

### Production (Coolify + Hetzner)

```bash
./ci/deploy.sh              # Standard deploy
./ci/deploy.sh --build      # Build from source
./ci/deploy.sh --rollback   # Rollback to previous
```

See [docs/confluence/09-infrastructure-deployment.md](docs/confluence/09-infrastructure-deployment.md) for full Coolify, Cloudflare, and monitoring setup.

### Edge Node

```bash
pip install rendertrust[edge]
edgekit register --gateway-url https://api.rendertrust.com --name "my-node" --capabilities render,inference
docker compose -f docker-compose.edge.yml up -d
```

See [docs/confluence/12-user-guide-node-operator.md](docs/confluence/12-user-guide-node-operator.md) for operator guide.

---

## Documentation

### In-Repo

| Document | Location | Description |
|----------|----------|-------------|
| **System Documentation** | [docs/confluence/](docs/confluence/) | 15-page comprehensive suite |
| **API Reference** | [docs/confluence/10-api-reference.md](docs/confluence/10-api-reference.md) | All 24 endpoints |
| **OpenAPI Spec** | [docs/api/openapi.json](docs/api/openapi.json) | Machine-readable API spec |
| **Architecture Manual** | [docs/arch/](docs/arch/) | System architecture deep-dive |
| **ADRs** | [docs/adr/](docs/adr/) | Architecture Decision Records |
| **Disaster Recovery** | [docs/dr/runbook.md](docs/dr/runbook.md) | DR procedures |
| **x402 Evaluation** | [docs/spikes/x402-poc-report.md](docs/spikes/x402-poc-report.md) | Payment protocol spike |
| **Changelog** | [CHANGELOG.md](CHANGELOG.md) | v1.0.0-alpha release notes |
| **Contributing** | [CONTRIBUTING.md](CONTRIBUTING.md) | Git workflow, commit standards |

### Confluence (External)

Full documentation with rich formatting is published to the [RenderTrust Confluence Space](https://cheddarfox.atlassian.net/wiki/spaces/RenderTrust/pages/436043780):

- Architecture Overview
- Core Platform (Gateway API)
- Authentication & Security
- Credit & Billing System
- Global Scheduler & Job Dispatch
- Edge Node System
- Object Storage
- Blockchain Anchoring
- Infrastructure & Deployment
- API Reference
- User Guide: Creator
- User Guide: Node Operator
- User Guide: Administrator
- User Guide: Developer (SDK & API)

### User Guides

| Role | Guide | What You'll Learn |
|------|-------|-------------------|
| **Creator** | [User Guide: Creator](docs/confluence/11-user-guide-creator.md) | Desktop app, job submission, credits, results |
| **Node Operator** | [User Guide: Node Operator](docs/confluence/12-user-guide-node-operator.md) | Registration, running a node, earning credits |
| **Administrator** | [User Guide: Administrator](docs/confluence/13-user-guide-administrator.md) | Fleet management, monitoring, alerts, DR |
| **Developer** | [User Guide: Developer](docs/confluence/14-user-guide-developer.md) | Python SDK, API integration, examples |

---

## Delivery Summary (v1.0.0-alpha)

| Metric | Value |
|--------|-------|
| **Story Points** | 133 across 40 stories |
| **Tests** | 716 passing |
| **Program Increments** | 3 (PI 1 Foundation, PI 2 Edge Execution, PI 3 Production & UX) |
| **Cycles** | 8 (Cycles 14-23) |
| **PRs Merged** | 22+ |
| **API Endpoints** | 24 (REST + WebSocket) |
| **Database Tables** | 7 + 6 Alembic migrations |

---

## Licensing

RenderTrust uses a multi-license model:

### Open Source

| License | Modules |
|---------|---------|
| **MIT** | `sdk/`, `frontend/`, `community/`, `loadtest/`, `ci/`, `docs/`, `diagrams/` |
| **Apache 2.0** | `core/`, `edgekit/relay/`, `sdk/mcp/` |

### Enterprise (Commercial)

| Module | Description |
|--------|-------------|
| `rollup_anchor/paymaster/` | Paymaster & bundler service |
| `edgekit/workers/premium_*/` | Premium worker plugins |
| `core/gateway/web/enterprise/` | Enterprise UI extensions |

See [LICENSE-MIT](./LICENSE-MIT), [LICENSE-APACHE-2.0](./LICENSE-APACHE-2.0), and [LICENSE-ENTERPRISE](./LICENSE-ENTERPRISE) for full texts.

---

## Contact & Support

- **Company**: [ByBren, LLC](https://bybren.com)
- **Author**: J. Scott Graham ([@cheddarfox](https://github.com/cheddarfox))
- **Email**: [scott@cheddarfox.com](mailto:scott@cheddarfox.com)
- **GitHub**: [github.com/bybren-llc/rendertrust](https://github.com/bybren-llc/rendertrust)
- **Linear**: [linear.app/cheddarfox](https://linear.app/cheddarfox)
