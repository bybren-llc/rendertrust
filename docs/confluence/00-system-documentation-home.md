# RenderTrust System Documentation — v1.0.0-alpha

**Version**: v1.0.0-alpha | **Released**: 2026-03-13 | **Author**: ByBren, LLC

---

## What is RenderTrust?

RenderTrust is a **distributed compute trust platform** that enables users to submit computational jobs (rendering, AI inference, data processing) to a decentralized network of edge nodes, with every transaction recorded on an immutable, blockchain-anchored credit ledger.

The platform provides:

- **Job submission and dispatch** — Submit jobs via desktop app, SDK, or API; they're routed to the best available node
- **Edge node network** — Operators run nodes that execute jobs and earn credits
- **Credit-based billing** — Stripe-powered credit purchases, automatic usage deduction, and transparent ledger
- **Blockchain anchoring** — Merkle-tree proofs anchored on-chain for tamper-evident auditability
- **Real-time relay** — WebSocket connections between gateway and edge nodes for instant job delivery

---

## System Architecture

```
                    ┌──────────────────────────────┐
                    │       Cloudflare CDN/WAF      │
                    │   (DNS, SSL, Rate Limiting)    │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │     FastAPI Gateway (core/)    │
                    │  ┌─────────────────────────┐  │
                    │  │ Auth  │ Credits │  Jobs  │  │
                    │  │ Relay │ Ledger  │ Sched  │  │
                    │  └─────────────────────────┘  │
                    │  Middleware: CORS, Security,   │
                    │  Rate Limit, Prometheus        │
                    └──┬──────────┬──────────┬──────┘
                       │          │          │
              ┌────────▼──┐  ┌───▼───┐  ┌───▼────────┐
              │ PostgreSQL │  │ Redis │  │ S3/R2      │
              │    16      │  │   7   │  │ (MinIO dev)│
              └────────────┘  └───────┘  └────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │    WebSocket Relay Server      │
                    └──────────────┬───────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
        ┌─────▼─────┐      ┌──────▼─────┐       ┌──────▼─────┐
        │ Edge Node  │      │ Edge Node  │       │ Edge Node  │
        │ (edgekit)  │      │ (edgekit)  │       │ (edgekit)  │
        └────────────┘      └────────────┘       └────────────┘
```

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | React 18, Electron 28, Vite 5, Tailwind CSS 3.4 |
| **Backend** | FastAPI (Python 3.11+), Pydantic v2 |
| **Database** | PostgreSQL 16, SQLAlchemy 2.x, Alembic |
| **Cache/Queue** | Redis 7 |
| **Object Storage** | S3-compatible (Cloudflare R2 prod, MinIO dev) |
| **Authentication** | JWT with refresh token rotation, Ed25519 node crypto |
| **Payments** | Stripe Checkout + Webhooks |
| **Blockchain** | Solidity (LedgerAnchor.sol), Hardhat, Web3.py |
| **Monitoring** | Prometheus, Grafana, Loki, Promtail |
| **Deployment** | Coolify (Hetzner VPS), Cloudflare Tunnel, Docker |
| **CI/CD** | GitHub Actions (lint, test, SAST, Docker build) |
| **SDK** | Python (httpx), TypeScript (planned) |
| **Community** | Next.js 14 (leaderboard portal) |

---

## Child Pages

| Page | Description |
|------|-------------|
| [Architecture Overview](01-architecture-overview.md) | System components, data flow, deployment topology |
| [Core Platform (Gateway API)](02-core-platform.md) | FastAPI endpoints, middleware, configuration |
| [Authentication & Security](03-authentication-security.md) | JWT, Ed25519, mTLS, OWASP, WAF |
| [Credit & Billing System](04-credit-billing.md) | Stripe, credit ledger, packages, usage tracking |
| [Global Scheduler & Job Dispatch](05-scheduler-dispatch.md) | Node fleet, dispatch algorithm, job lifecycle |
| [Edge Node System](06-edge-node-system.md) | Relay, workers, plugins, registration, Docker |
| [Object Storage](07-object-storage.md) | S3/R2 abstraction, presigned URLs, encryption |
| [Blockchain Anchoring](08-blockchain-anchoring.md) | Merkle tree, bundler, proof verification, Solidity |
| [Infrastructure & Deployment](09-infrastructure-deployment.md) | Coolify, Docker, Cloudflare, monitoring |
| [API Reference](10-api-reference.md) | Complete endpoint catalog with request/response shapes |
| [User Guide — Creator (Job Submitter)](11-user-guide-creator.md) | Desktop app, submitting jobs, managing credits |
| [User Guide — Node Operator](12-user-guide-node-operator.md) | Running an edge node, registration, monitoring |
| [User Guide — Administrator](13-user-guide-administrator.md) | Fleet management, monitoring, troubleshooting |
| [User Guide — Developer (SDK & API)](14-user-guide-developer.md) | Python SDK, API integration, examples |

---

## Delivery Summary

| Metric | Value |
|--------|-------|
| **Story Points** | 133 across 40 stories |
| **Tests** | 716 passing |
| **Program Increments** | 3 (PI 1-3) |
| **Cycles** | 8 (Cycles 14-23) |
| **PRs Merged** | 22+ |
| **API Endpoints** | 24 (REST + WebSocket) |
| **Database Tables** | 7 |
| **Alembic Migrations** | 6 |

---

*MIT License | Copyright (c) 2026 ByBren, LLC*
