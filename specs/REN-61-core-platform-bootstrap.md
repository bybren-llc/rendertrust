<!-- Copyright 2026 ByBren, LLC. Licensed under the Apache License, Version 2.0. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# REN-61: Core Platform Bootstrap

| Field            | Value                                      |
|------------------|--------------------------------------------|
| **Linear Ticket**| [REN-61](https://linear.app/cheddarfox/issue/REN-61) |
| **SAFe Type**    | Enabler (Infrastructure)                   |
| **Status**       | COMPLETE                                   |
| **Priority**     | Urgent                                     |
| **Story Points** | 8                                          |
| **PI / Sprint**  | Phase I / Sprint 1                         |

---

## Overview

Bootstrap the RenderTrust core platform with production-grade project scaffolding, containerized development environment, and database migration infrastructure. This enabler establishes the foundational build, run, and test toolchain that all subsequent features depend on.

RenderTrust is a general-purpose trust fabric for computational services. This bootstrap provides the service chassis upon which trust verification, credit ledger, and edge node scheduling are built.

## Deliverables (Completed)

- `pyproject.toml` with dependency groups (dev, test, lint)
- Multi-stage `Dockerfile` (build + slim runtime)
- `docker-compose.yml` orchestrating FastAPI, PostgreSQL 16, and Redis
- `Makefile` with targets: `dev`, `build`, `lint`, `test`, `ci`, `migrate`
- Alembic migration scaffold with initial User model
- `core/main.py` FastAPI application factory with CORS, health check
- `core/database.py` async SQLAlchemy engine + session factory
- `core/config.py` Pydantic Settings with environment validation

## Acceptance Criteria

- [x] `docker compose up` starts FastAPI on :8000, PostgreSQL on :5432, Redis on :6379
- [x] `GET /health` returns `{"status": "ok"}` with DB connectivity check
- [x] `alembic upgrade head` applies migrations without error
- [x] `make ci` passes: ruff lint, mypy type-check, pytest suite, Docker build
- [x] Multi-stage Dockerfile produces image under 200 MB
- [x] All secrets loaded from environment variables, no hardcoded credentials
- [x] PostgreSQL connection uses async driver (asyncpg)

## Technical Approach

### Architecture

```
docker-compose.yml
├── api (FastAPI) ─── core/main.py
│   ├── core/config.py      # Pydantic Settings
│   ├── core/database.py     # async SQLAlchemy engine
│   └── core/models/base.py  # DeclarativeBase + User model
├── db (PostgreSQL 16)
└── redis (Redis 7)
```

### Key Decisions

- **#PATH_DECISION**: Selected asyncpg over psycopg3 for async PostgreSQL driver (better FastAPI integration, mature ecosystem)
- **#PATH_DECISION**: Pydantic Settings v2 for config validation (type-safe, `.env` support, no custom parsing)
- **#PATH_DECISION**: Multi-stage Docker build to minimize attack surface in production image

### Patterns Referenced

- `patterns_library/config/environment-config.md` -- env var loading
- `patterns_library/config/structured-logging.md` -- logging setup
- `patterns_library/database/` -- migration workflow

## Dependencies

| Dependency       | Status   | Notes                          |
|------------------|----------|--------------------------------|
| Python 3.11+     | Ready    | Runtime requirement            |
| Docker + Compose | Ready    | Local development requirement  |
| PostgreSQL 16    | Ready    | Via Docker Compose             |
| Redis 7          | Ready    | Via Docker Compose             |

## Testing Strategy

- **Unit**: Config validation, model schema checks (`pytest`)
- **Integration**: DB connection lifecycle, migration apply/rollback
- **Smoke**: `docker compose up` + health check endpoint verification
- **CI Gate**: `make ci` runs all checks in GitHub Actions (see REN-26)

## Security Considerations

- **OWASP A07 (Security Misconfiguration)**: No default passwords; all credentials via env vars
- **OWASP A09 (Security Logging)**: Structured JSON logging with request tracing
- **Container Security**: Non-root user in Dockerfile, minimal base image (python:3.11-slim)
- **Database**: Connection string never logged; SSL mode configurable via env
- **#EXPORT_CRITICAL**: `.env` file excluded via `.gitignore` and `.dockerignore`
