# Core Platform (Gateway API)

**Parent**: [RenderTrust System Documentation](00-system-documentation-home.md)

---

## Overview

The core platform is a **FastAPI** application that serves as the central gateway for all RenderTrust operations. It handles authentication, credit management, job dispatch, edge node coordination, and blockchain anchoring.

**Entry Point**: `core/main.py` → `create_app()` factory

---

## Application Bootstrap

```python
# core/main.py
app = create_app()  # Module-level instance for uvicorn

def create_app() -> FastAPI:
    # 1. Load settings from .env
    # 2. Configure structlog (JSON in production, console in dev)
    # 3. Create FastAPI with lifespan manager
    # 4. Add middleware stack (order matters)
    # 5. Include API v1 router
    # 6. Add convenience endpoints (/health, /version, /metrics)
    # 7. Optionally mount x402 PoC routes
```

**Lifespan Events:**
- **Startup**: Configures logging, logs environment info
- **Shutdown**: Logs clean shutdown

---

## Configuration (core/config.py)

All settings loaded from environment variables via Pydantic `BaseSettings`:

| Setting | Default | Description |
|---------|---------|-------------|
| `APP_NAME` | rendertrust | Application name |
| `APP_ENV` | development | Environment (development/staging/production) |
| `APP_DEBUG` | false | Debug mode (NEVER true in production) |
| `APP_HOST` | 0.0.0.0 | Bind address |
| `APP_PORT` | 8000 | Bind port |
| `SECRET_KEY` | (required) | Application secret |
| `DATABASE_URL` | postgresql+asyncpg://... | PostgreSQL connection |
| `DB_POOL_SIZE` | 10 | Connection pool size |
| `DB_MAX_OVERFLOW` | 20 | Max overflow connections |
| `REDIS_URL` | redis://redis:6379/0 | Redis connection |
| `JWT_SECRET_KEY` | (required) | JWT signing key |
| `JWT_ALGORITHM` | HS256 | JWT algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | Access token TTL |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | 7 | Refresh token TTL |
| `STRIPE_SECRET_KEY` | | Stripe API key |
| `STRIPE_WEBHOOK_SECRET` | | Stripe webhook signing secret |
| `CORS_ORIGINS` | localhost:3000,8000 | Allowed CORS origins |
| `ENCRYPTION_MASTER_KEY` | (required) | 32-byte hex key for data-at-rest |
| `X402_ENABLED` | false | Enable x402 payment protocol PoC |

**Production Validator**: `validate_production_secrets()` — Ensures default/development secrets are NOT used when `APP_ENV=production`.

---

## Convenience Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| `GET /health` | None | Liveness probe: `{"status": "healthy"}` |
| `GET /version` | None | App metadata: name, version, environment |
| `GET /metrics` | None | Prometheus scrape endpoint (text format) |
| `GET /docs` | None | Swagger UI (OpenAPI interactive docs) |
| `GET /redoc` | None | ReDoc API documentation |
| `GET /openapi.json` | None | Raw OpenAPI 3.1 specification |

---

## API Router Structure

All API routes live under `/api/v1/` via `core/api/v1/router.py`:

```
/api/v1/
├── /auth/          → Authentication (register, login, refresh, logout)
├── /health/        → Health checks (liveness, readiness)
├── /credits/       → Credit balance, history, deduction
├── /jobs/          → Job listing, detail, cancel, result download
├── /jobs/dispatch  → Job dispatch to edge nodes
├── /nodes/         → Node registration, heartbeat
├── /relay/         → WebSocket relay for edge nodes
├── /webhooks/      → Stripe webhook receiver
├── /certs/         → Certificate management
└── /ledger/        → Blockchain proof and anchor queries
```

See [API Reference](10-api-reference.md) for complete endpoint documentation.

---

## Database Layer

**Engine**: SQLAlchemy 2.x async with `asyncpg` driver (PostgreSQL) or `aiosqlite` (tests)

```python
# core/database.py
engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=20)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession)

# FastAPI dependency injection
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
```

**Base Models**:
- `Base` — SQLAlchemy DeclarativeBase
- `TimestampMixin` — `created_at`, `updated_at` auto-managed
- `BaseModel` — UUID primary key + timestamps (abstract)

---

## Prometheus Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `http_requests_total` | Counter | method, endpoint, status_code | Total HTTP requests |
| `http_request_duration_seconds` | Histogram | method, endpoint | Request latency |
| `jobs_dispatched_total` | Counter | job_type | Jobs sent to nodes |
| `jobs_completed_total` | Counter | job_type, status | Completed/failed jobs |
| `fleet_nodes_total` | Gauge | status | Nodes by health status |
| `credits_consumed_total` | Counter | — | Total credits spent |
| `active_websocket_connections` | Gauge | — | Live WebSocket connections |

**PrometheusMiddleware** normalizes paths (e.g., `/api/v1/jobs/abc-123` → `/api/v1/jobs/{id}`) and skips recording `/metrics` to avoid self-referential noise.

---

## Security Headers

Applied by `SecurityHeadersMiddleware` on every response:

| Header | Value |
|--------|-------|
| `X-Content-Type-Options` | nosniff |
| `X-Frame-Options` | DENY |
| `X-XSS-Protection` | 1; mode=block |
| `Referrer-Policy` | strict-origin-when-cross-origin |
| `Permissions-Policy` | camera=(), microphone=(), geolocation=() |
| `Strict-Transport-Security` | max-age=31536000; includeSubDomains (production only) |

---

*MIT License | Copyright (c) 2026 ByBren, LLC*
