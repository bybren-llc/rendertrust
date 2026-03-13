# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0-alpha] - 2026-03-12

### Added

#### PI 1 — Foundation & Deployability (84 pts)
- **Authentication**: JWT with refresh token rotation, API key auth for edge nodes
- **Credit Ledger**: Stripe-integrated billing with credit purchase, deduction, and history
- **Security Hardening**: CORS, rate limiting, security headers, OWASP compliance
- **Test Infrastructure**: 142-test suite, E2E Docker framework, CI pipeline
- **Global Scheduler**: Edge node registration, fleet management, job dispatch with Redis queue
- **x402 PoC**: HTTP 402 payment protocol evaluation (GO decision for v2)

#### PI 2 — Edge Execution & Storage (66 pts)
- **Edge Relay**: WebSocket server for real-time node communication
- **Worker Execution**: Plugin-based execution framework with CPU worker
- **Object Storage**: S3/R2 abstraction with presigned URLs, MinIO for dev
- **Job Lifecycle**: Status transitions (QUEUED→RUNNING→COMPLETED/FAILED), cancel, retry
- **Error Handling**: Exponential backoff retry, dead letter queue, circuit breaker
- **Billing**: Usage tracking with auto-deduct, monthly payout calculation
- **Edge Packaging**: Docker container for edge nodes, registration CLI
- **Auto-Scale**: Load-based scale triggers via Redis pubsub
- **E2E Test**: Full job execution flow validated end-to-end

#### PI 3 — Production & UX (67 pts)
- **Infrastructure**: Coolify setup on Hetzner, Cloudflare DNS/tunnel, production Docker Compose
- **Observability**: Prometheus metrics, Grafana dashboards (API/jobs/fleet), Loki logging, alerting rules
- **Security**: mTLS for edge nodes (internal CA), AES-256-GCM data-at-rest encryption with per-user keys
- **Disaster Recovery**: Backup/restore scripts, runbook (RPO 24h DB, RTO 4h)
- **Creator App**: Electron + React 18 + Vite desktop app with auth flow, job submission, credit dashboard
- **Python SDK**: `rendertrust` package with sync/async clients for job management
- **OpenAPI**: Always-available `/docs` and `/redoc`, exported spec
- **Blockchain**: Merkle tree anchoring service with background bundler, proof verification API
- **Community Portal**: Next.js 14 leaderboard with operator rankings and network stats

### Stats
- **Total story points delivered**: 217 across 40 stories in 8 cycles
- **Test count**: 716 passing tests
- **PRs merged**: 22+ (PI 1) + direct commits (PI 2/3)
- **Technology**: FastAPI, PostgreSQL 16, SQLAlchemy 2.x, Redis, React 18, Electron, Next.js 14, Solidity

[1.0.0-alpha]: https://github.com/bybren-llc/rendertrust/releases/tag/v1.0.0-alpha
