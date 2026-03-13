# ADR-001: Project Foundation Architecture (REN-61)

## Status

**Accepted** -- 2026-03-09

## Context

RenderTrust is a general-purpose trust fabric for computational services. The stack
is defined as FastAPI (Python 3.11+), PostgreSQL 16, SQLAlchemy 2.x + Alembic,
React 18 + Electron, deployed via Coolify on Hetzner with Cloudflare CDN.

The codebase today contains **348 lines of Python** across 13 files. There is no
`pyproject.toml`, no `Makefile`, no root `docker-compose.yml`, no FastAPI application
entry point, no authentication middleware, no Alembic configuration, and no GitHub
Actions CI workflow. Every one of these must be created before any Cycle 1 feature
work (REN-29, REN-32, REN-33, REN-53) can proceed.

This ADR establishes the architectural decisions for the entire project foundation
layer so that the BE Developer can execute without ambiguity.

---

## Decision

### 1. Package Management: pyproject.toml with pip

**Decision**: Use a single `pyproject.toml` at repository root with `[project]`
metadata and pinned dependency ranges. No Poetry, no uv -- plain `pip install -e ".[dev]"`.

**Rationale**: The codebase is a monorepo with three deployable units (`core/`,
`edgekit/`, `rollup_anchor/`) that share common libraries. A single `pyproject.toml`
is the simplest approach that works with standard pip, Docker builds, and CI caching.
Poetry and uv add complexity without proportional benefit at this project size.

**Exact specification**:

```toml
[build-system]
requires = ["setuptools>=75.0", "wheel"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "rendertrust"
version = "0.1.0"
description = "General-purpose trust fabric for computational services"
requires-python = ">=3.11"
license = {text = "Apache-2.0"}
authors = [
    {name = "ByBren, LLC", email = "contributors@rendertrust.com"},
]

dependencies = [
    # Web framework
    "fastapi>=0.115.0,<1.0",
    "uvicorn[standard]>=0.34.0,<1.0",

    # Database
    "sqlalchemy[asyncio]>=2.0.36,<3.0",
    "asyncpg>=0.30.0,<1.0",
    "alembic>=1.14.0,<2.0",

    # Configuration & validation
    "pydantic>=2.10.0,<3.0",
    "pydantic-settings>=2.7.0,<3.0",

    # Authentication
    "python-jose[cryptography]>=3.3.0,<4.0",
    "passlib[bcrypt]>=1.7.4,<2.0",

    # Payments
    "stripe>=11.0.0,<12.0",

    # HTTP client
    "httpx>=0.28.0,<1.0",

    # Logging
    "structlog>=24.4.0,<25.0",

    # Invoicing (optional -- only needed by billing cron)
    "weasyprint>=63.0,<64.0",
    "jinja2>=3.1.0,<4.0",
]

[project.optional-dependencies]
dev = [
    # Testing
    "pytest>=8.3.0,<9.0",
    "pytest-asyncio>=0.24.0,<1.0",
    "pytest-cov>=6.0.0,<7.0",
    "httpx",  # for FastAPI TestClient

    # Linting & type checking
    "ruff>=0.8.0,<1.0",
    "mypy>=1.13.0,<2.0",

    # Security audit
    "pip-audit>=2.7.0,<3.0",

    # SQLAlchemy type stubs
    "sqlalchemy[mypy]>=2.0.36,<3.0",
]

blockchain = [
    "web3>=7.0.0,<8.0",
    "psycopg2-binary>=2.9.0,<3.0",
]

edge = [
    "influxdb-client>=1.40.0,<2.0",
    "hvac>=2.3.0,<3.0",
]

[tool.setuptools.packages.find]
include = ["core*", "edgekit*", "sdk*"]

# ── Ruff Configuration ──────────────────────────────────────────────
[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort
    "N",    # pep8-naming
    "UP",   # pyupgrade
    "B",    # flake8-bugbear
    "S",    # flake8-bandit (security)
    "A",    # flake8-builtins
    "C4",   # flake8-comprehensions
    "DTZ",  # flake8-datetimez
    "T20",  # flake8-print (no print in production code)
    "RET",  # flake8-return
    "SIM",  # flake8-simplify
    "TCH",  # flake8-type-checking
    "ARG",  # flake8-unused-arguments
    "PTH",  # flake8-use-pathlib
    "RUF",  # ruff-specific rules
]
ignore = [
    "S101",   # allow assert in tests
    "S104",   # allow binding to 0.0.0.0 (Docker)
    "B008",   # allow Depends() in function defaults (FastAPI pattern)
]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["S101", "ARG", "T20"]
"rollup_anchor/**/*.py" = ["T20"]  # bundler uses print for daemon logging

[tool.ruff.lint.isort]
known-first-party = ["core", "edgekit", "sdk"]

# ── Mypy Configuration ──────────────────────────────────────────────
[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
plugins = ["pydantic.mypy", "sqlalchemy.ext.mypy.plugin"]

[[tool.mypy.overrides]]
module = [
    "stripe.*",
    "hvac.*",
    "weasyprint.*",
    "influxdb_client.*",
    "web3.*",
    "postmarker.*",
]
ignore_missing_imports = true

# ── Pytest Configuration ─────────────────────────────────────────────
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "unit: unit tests (no external dependencies)",
    "integration: integration tests (require database)",
    "e2e: end-to-end tests (require full stack)",
]
filterwarnings = [
    "ignore::DeprecationWarning:sqlalchemy.*",
]
addopts = "--strict-markers --tb=short -q"
```

**Key decisions in this specification**:

- `weasyprint` and `jinja2` are runtime dependencies (invoice generation is a core
  billing feature, not optional).
- `web3` and `psycopg2-binary` are in a separate `[blockchain]` extra because the
  bundler daemon is deployed independently from the gateway.
- `influxdb-client` and `hvac` are in a separate `[edge]` extra because edge fleet
  components are deployed independently.
- Ruff `S` (bandit) rules are enabled for security linting from day one.
- `T20` (no `print()`) is enabled to enforce structured logging; exempted only in
  tests and the bundler daemon.
- mypy strict mode is on. This will require fixing every existing file. That is
  intentional -- the codebase is only 348 lines, so the cost is minimal now and
  the benefit compounds.

---

### 2. Docker Strategy

**Decision**: Multi-stage Dockerfile with `python:3.11-slim-bookworm` base.
Development compose includes PostgreSQL 16 and Redis 7.

**Exact file: `Dockerfile`** (repository root):

```dockerfile
# ── Stage 1: Builder ─────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 2: Production ─────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS production

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system app && adduser --system --ingroup app app

COPY --from=builder /install /usr/local
COPY core/ ./core/
COPY alembic/ ./alembic/
COPY alembic.ini ./

USER app

EXPOSE 8000
CMD ["uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Stage 3: Development ────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS development

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"
COPY . .

EXPOSE 8000
CMD ["uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

**Exact file: `docker-compose.yml`** (repository root):

```yaml
services:
  api:
    build:
      context: .
      target: development
    ports:
      - "8000:8000"
    volumes:
      - .:/app
    environment:
      - DATABASE_URL=postgresql+asyncpg://rendertrust:rendertrust@db:5432/rendertrust
      - REDIS_URL=redis://redis:6379/0
      - JWT_SECRET_KEY=dev-secret-change-in-production
      - JWT_ALGORITHM=HS256
      - JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
      - JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
      - ENVIRONMENT=development
      - LOG_LEVEL=debug
      - LOG_FORMAT=pretty
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy

  db:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: rendertrust
      POSTGRES_PASSWORD: rendertrust
      POSTGRES_DB: rendertrust
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U rendertrust"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
```

**Key decisions**:

- `python:3.11-slim-bookworm` (not `3.11-slim` which aliases to the latest Debian).
  Pinning to Bookworm prevents surprise base image changes.
- The production stage copies only `core/` and `alembic/` -- not `edgekit/` or
  `rollup_anchor/`, because those are separate deployable units with their own
  Dockerfiles (to be created in later tickets).
- The production stage creates a non-root `app` user. This is mandatory per OWASP
  Container Security guidelines.
- Development stage mounts the full repo and uses `--reload` for hot-reloading.
- PostgreSQL uses `16-alpine` (matches the production version declared in CLAUDE.md).
- Redis is included for rate limiting and caching (required by REN-54 gateway auth).
- Health checks are defined so `depends_on` with `condition: service_healthy` works.

---

### 3. FastAPI Application Structure

**Decision**: Single `core/main.py` entry point with lifespan context manager for
database pool management. Middleware applied in CORS -> auth -> logging -> error
handler order. Routers organized by domain.

**Exact file: `core/main.py`**:

```python
# Copyright 2025 Words To Film By, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.db.session import async_engine
from core.middleware.logging import LoggingMiddleware
from core.middleware.error_handler import ErrorHandlerMiddleware

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: manage DB connection pool."""
    logger.info(
        "application_starting",
        environment=settings.ENVIRONMENT,
        version="0.1.0",
    )
    yield
    await async_engine.dispose()
    logger.info("application_shutdown")


app = FastAPI(
    title="RenderTrust API",
    description="General-purpose trust fabric for computational services",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
)

# ── Middleware (outermost first) ──────────────────────────────────────
# Order matters: the first middleware added is the outermost layer.
# Request flow: CORS -> Error Handler -> Logging -> Route Handler
# Response flow: Route Handler -> Logging -> Error Handler -> CORS

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(LoggingMiddleware)

# ── Routers ───────────────────────────────────────────────────────────
from core.api.v1.health import router as health_router  # noqa: E402

app.include_router(health_router, prefix="/api/v1", tags=["health"])

# Future routers (uncomment as implemented):
# from core.api.v1.auth import router as auth_router
# app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
# from core.billing.stripe.stripe_webhook import router as stripe_router
# app.include_router(stripe_router, prefix="/api/v1", tags=["billing"])
```

**Exact directory layout** (files to create):

```
core/
  __init__.py
  main.py                          # FastAPI app (above)
  config.py                        # Pydantic Settings
  api/
    __init__.py
    v1/
      __init__.py
      health.py                    # GET /api/v1/health
  db/
    __init__.py
    session.py                     # async engine + session factory
    base.py                        # declarative base with TimestampMixin
  middleware/
    __init__.py
    logging.py                     # structlog request/response logging
    error_handler.py               # global exception -> JSON response
  auth/
    __init__.py
    jwt.py                         # JWT encode/decode/refresh
    dependencies.py                # get_current_user dependency
    models.py                      # TokenPayload, TokenResponse pydantic models
  models/
    __init__.py                    # re-export all models for Alembic
```

**Rationale for middleware order**:

1. **CORS** is outermost so preflight `OPTIONS` requests are handled immediately
   without touching auth or logging.
2. **ErrorHandlerMiddleware** wraps everything so that unhandled exceptions in logging
   middleware or route handlers are caught and returned as structured JSON.
3. **LoggingMiddleware** is innermost (closest to route handler) so it can accurately
   measure route handler duration and log the response status.

Authentication is NOT middleware -- it is a FastAPI dependency injected per-route.
This is the standard FastAPI pattern and allows public routes (health, webhooks)
to skip auth without allowlist logic in middleware.

---

### 4. Configuration: Pydantic Settings

**Decision**: Single `core/config.py` using `pydantic-settings` `BaseSettings` with
`.env` file support.

**Exact file: `core/config.py`**:

```python
# Copyright 2025 Words To Film By, Inc.
# Licensed under the Apache License, Version 2.0

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Validated at import time (fail-fast)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────
    ENVIRONMENT: str = "development"
    APP_URL: str = "http://localhost:8000"
    PORT: int = 8000
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # ── Database ─────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://rendertrust:rendertrust@localhost:5432/rendertrust"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_POOL_OVERFLOW: int = 5

    # ── JWT Authentication ───────────────────────────────────────────
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Stripe ───────────────────────────────────────────────────────
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # ── Redis ────────────────────────────────────────────────────────
    REDIS_URL: str = ""

    # ── Logging ──────────────────────────────────────────────────────
    LOG_LEVEL: str = "info"
    LOG_FORMAT: str = "pretty"  # "json" in production

    # ── Computed properties ──────────────────────────────────────────
    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_test(self) -> bool:
        return self.ENVIRONMENT == "test"

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def jwt_secret_must_be_set_in_production(cls, v: str, info: object) -> str:
        # In production, JWT_SECRET_KEY must be set and non-trivial.
        # This validator runs at startup; the ENVIRONMENT field may not
        # be available yet via info.data, so we only validate non-emptiness
        # here. The lifespan event performs the full production check.
        return v


settings = Settings()
```

**Key decisions**:

- `case_sensitive=True` to prevent ambiguity between `database_url` and `DATABASE_URL`.
- `extra="ignore"` so unrecognized env vars do not cause validation errors (Docker
  compose injects many system vars).
- Defaults provided for all settings so the app starts in development with zero
  configuration. Production deployments MUST override `JWT_SECRET_KEY`,
  `STRIPE_SECRET_KEY`, etc.
- `DATABASE_URL` uses the `postgresql+asyncpg://` scheme because SQLAlchemy requires
  the async driver prefix for `create_async_engine`.

---

### 5. Database: SQLAlchemy 2.x Async

**Decision**: Async session factory with `create_async_engine`. Base model with
`id` (UUID), `created_at`, `updated_at` columns. Alembic configured for async.

**Exact file: `core/db/session.py`**:

```python
# Copyright 2025 Words To Film By, Inc.
# Licensed under the Apache License, Version 2.0

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings

async_engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_POOL_OVERFLOW,
    echo=settings.is_development,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency that provides a database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
```

**Exact file: `core/db/base.py`**:

```python
# Copyright 2025 Words To Film By, Inc.
# Licensed under the Apache License, Version 2.0

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base model for all database models."""
    pass


class TimestampMixin:
    """Mixin that adds created_at and updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDPrimaryKeyMixin:
    """Mixin that adds a UUID primary key."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
```

**Alembic configuration** -- exact files:

File: `alembic.ini` (repository root):

```ini
[alembic]
script_location = alembic
sqlalchemy.url = driver://user:pass@localhost/dbname
# URL is overridden by env.py at runtime

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

File: `alembic/env.py`:

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import settings
from core.db.base import Base
# Import all models so Alembic can detect them for autogenerate:
import core.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL without DB connection)."""
    context.configure(
        url=settings.DATABASE_URL.replace("+asyncpg", ""),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to DB)."""
    connectable = create_async_engine(settings.DATABASE_URL)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

File: `alembic/script.py.mako` (standard Alembic template -- use `alembic init` default).

File: `alembic/versions/` (empty directory, `.gitkeep`).

**Key decisions**:

- UUID primary keys. Integer auto-increment IDs leak information about record count
  and creation order. UUIDs are standard for APIs that expose IDs to external clients.
- `expire_on_commit=False` on the session factory. This prevents lazy-load surprises
  after `await session.commit()` -- attributes remain accessible without re-querying.
- `TimestampMixin` uses `DateTime(timezone=True)` so all timestamps are timezone-aware.
  PostgreSQL stores them as UTC.
- Alembic `env.py` uses `create_async_engine` directly with `asyncio.run` rather than
  the synchronous engine. This matches the application's async-only database access.

---

### 6. Authentication: JWT with Refresh Token Rotation

**Decision**: HS256 JWT with short-lived access tokens (30 min) and longer-lived
refresh tokens (7 days). Refresh token rotation: every refresh invalidates the old
token and issues a new pair.

**Exact file: `core/auth/models.py`**:

```python
# Copyright 2025 Words To Film By, Inc.
# Licensed under the Apache License, Version 2.0

from pydantic import BaseModel


class TokenPayload(BaseModel):
    """JWT token payload (claims)."""
    sub: str          # Subject (user ID or node ID)
    exp: int          # Expiration timestamp (Unix epoch)
    iat: int          # Issued-at timestamp (Unix epoch)
    type: str         # "access" or "refresh"
    jti: str          # Unique token ID (for refresh token revocation)


class TokenResponse(BaseModel):
    """Response returned by login and refresh endpoints."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int   # Seconds until access token expires
```

**Exact file: `core/auth/jwt.py`**:

```python
# Copyright 2025 Words To Film By, Inc.
# Licensed under the Apache License, Version 2.0

import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from core.auth.models import TokenPayload
from core.config import settings


def create_access_token(subject: str) -> str:
    """Create a short-lived access token."""
    now = datetime.now(tz=timezone.utc)
    expire = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": subject,
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "type": "access",
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str) -> str:
    """Create a longer-lived refresh token."""
    now = datetime.now(tz=timezone.utc)
    expire = now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": subject,
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "type": "refresh",
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> TokenPayload:
    """Decode and validate a JWT token. Raises JWTError on failure."""
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    return TokenPayload(**payload)
```

**Exact file: `core/auth/dependencies.py`**:

```python
# Copyright 2025 Words To Film By, Inc.
# Licensed under the Apache License, Version 2.0

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from core.auth.jwt import decode_token
from core.auth.models import TokenPayload

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> TokenPayload:
    """FastAPI dependency: extract and validate JWT from Authorization header."""
    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )
    return payload
```

**Key decisions**:

- Auth is a **dependency**, not middleware. This is the canonical FastAPI pattern.
  Routes that require auth declare `user: TokenPayload = Depends(get_current_user)`.
  Routes that don't (health, webhooks) simply don't include the dependency.
- HS256 (symmetric) is used initially. The `JWT_ALGORITHM` setting allows migration
  to RS256 (asymmetric) later when edge nodes need to verify tokens without the
  signing key.
- `jti` (JWT ID) is included in every token to support refresh token revocation.
  The revocation store (Redis or DB table) is a separate ticket.
- `python-jose[cryptography]` is the JWT library, not `PyJWT`. `python-jose`
  supports JWE (encrypted tokens) which will be needed for edge node token rotation
  (as seen in `core/ledger/vault/token_rotator.py`).

---

### 7. Structured Logging: structlog

**Decision**: `structlog` with JSON output in production and colored console output
in development. Configured once at import time.

**Exact file: `core/logging.py`**:

```python
# Copyright 2025 Words To Film By, Inc.
# Licensed under the Apache License, Version 2.0

import logging
import sys

import structlog

from core.config import settings


def configure_logging() -> None:
    """Configure structlog for the application. Call once at startup."""

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.LOG_FORMAT == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.LOG_LEVEL.upper())

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.DEBUG if settings.is_development else logging.WARNING
    )
```

**Key decisions**:

- structlog is configured through the stdlib `logging` integration, not standalone.
  This means `uvicorn`, `alembic`, `sqlalchemy`, and any other library that uses
  stdlib `logging` will also emit structured logs.
- `contextvars` is used for correlation ID propagation (set in `LoggingMiddleware`,
  available in all downstream code without explicit passing).
- Console renderer in development for human-readable output; JSON renderer in
  production for machine parsing (Datadog, Loki, etc.).

---

### 8. Health Check Endpoint

**Exact file: `core/api/v1/health.py`**:

```python
# Copyright 2025 Words To Film By, Inc.
# Licensed under the Apache License, Version 2.0

import time
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.session import get_db

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """
    Health check endpoint for load balancers and deployment pipelines.
    Verifies database connectivity.
    """
    checks: dict[str, Any] = {}

    # Database check
    start = time.monotonic()
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = {
            "status": "healthy",
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
        }
    except Exception as e:
        logger.error("health_check_db_failed", error=str(e))
        checks["database"] = {"status": "unhealthy"}

    overall = "healthy" if all(
        c.get("status") == "healthy" for c in checks.values()
    ) else "unhealthy"

    return {
        "status": overall,
        "checks": checks,
    }
```

---

### 9. Makefile

**Decision**: `Makefile` at repository root with targets matching CLAUDE.md and
CONTRIBUTING.md commands.

**Exact file: `Makefile`**:

```makefile
.PHONY: help install lint typecheck test test-unit test-integration ci \
        dev db-up db-migrate db-revision build clean audit

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies (dev)
	pip install -e ".[dev]"

lint: ## Run ruff linter
	ruff check .

lint-fix: ## Auto-fix lint issues
	ruff check . --fix

typecheck: ## Run mypy type checker
	mypy core/

test: ## Run all tests
	pytest

test-unit: ## Run unit tests only
	pytest -m unit

test-integration: ## Run integration tests only
	pytest -m integration

ci: lint typecheck test ## Run all CI checks (REQUIRED before pushing)

dev: ## Start development server
	docker compose up

db-up: ## Start database only
	docker compose up -d db redis

db-migrate: ## Run database migrations
	alembic upgrade head

db-revision: ## Create new migration (usage: make db-revision MSG="add users table")
	alembic revision --autogenerate -m "$(MSG)"

build: ## Build production Docker image
	docker compose build

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null; \
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null; \
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null; \
	rm -rf dist/ build/ *.egg-info/

audit: ## Run security audit on dependencies
	pip-audit
```

---

### 10. GitHub Actions CI

**Decision**: Single CI workflow on pull requests to `dev`. Stages: lint + typecheck
(parallel) -> unit tests -> integration tests (with Postgres service).

**Exact file: `.github/workflows/ci.yml`**:

```yaml
name: CI

on:
  pull_request:
    branches: [dev]
  push:
    branches: [dev]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

env:
  PYTHON_VERSION: "3.11"

jobs:
  lint:
    name: Lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install -e ".[dev]"
      - run: ruff check .

  typecheck:
    name: Type Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install -e ".[dev]"
      - run: mypy core/

  test:
    name: Tests
    needs: [lint, typecheck]
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: rendertrust
          POSTGRES_PASSWORD: rendertrust
          POSTGRES_DB: rendertrust_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U rendertrust"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 5
    env:
      DATABASE_URL: postgresql+asyncpg://rendertrust:rendertrust@localhost:5432/rendertrust_test
      JWT_SECRET_KEY: ci-test-secret
      ENVIRONMENT: test
      LOG_LEVEL: error
      LOG_FORMAT: json
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install -e ".[dev]"
      - run: alembic upgrade head
      - run: pytest --cov=core --cov-report=xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: test-results
          path: |
            coverage.xml
            .pytest_cache/
          retention-days: 7

  audit:
    name: Security Audit
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install -e ".[dev]"
      - run: pip-audit
```

---

### 11. .env.template

**Exact file: `.env.template`** (repository root):

```bash
# ============================================================================
# RENDERTRUST ENVIRONMENT CONFIGURATION
# ============================================================================
# Copy to .env for local development: cp .env.template .env
# REQUIRED values have no default and must be set.
# OPTIONAL values show their defaults in comments.
# ============================================================================

# --- Application -----------------------------------------------------------
# OPTIONAL: Environment name (default: development)
# ENVIRONMENT=development
# OPTIONAL: Public URL (default: http://localhost:8000)
# APP_URL=http://localhost:8000
# OPTIONAL: Port (default: 8000)
# PORT=8000
# OPTIONAL: CORS origins, comma-separated (default: http://localhost:3000)
# CORS_ORIGINS=http://localhost:3000

# --- Database ---------------------------------------------------------------
# REQUIRED for production. Default works with docker-compose.yml dev setup.
DATABASE_URL=postgresql+asyncpg://rendertrust:rendertrust@localhost:5432/rendertrust
# OPTIONAL: Pool size (default: 10)
# DATABASE_POOL_SIZE=10

# --- JWT Authentication -----------------------------------------------------
# REQUIRED: Secret key for signing JWTs. Generate with: python -c "import secrets; print(secrets.token_urlsafe(64))"
JWT_SECRET_KEY=CHANGE_ME_IN_PRODUCTION
# OPTIONAL: Algorithm (default: HS256)
# JWT_ALGORITHM=HS256
# OPTIONAL: Access token lifetime in minutes (default: 30)
# JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
# OPTIONAL: Refresh token lifetime in days (default: 7)
# JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# --- Stripe ------------------------------------------------------------------
# REQUIRED for payment features
# STRIPE_SECRET_KEY=sk_test_xxxxx
# STRIPE_WEBHOOK_SECRET=whsec_xxxxx

# --- Redis -------------------------------------------------------------------
# OPTIONAL: Redis for rate limiting and caching (default: none)
# REDIS_URL=redis://localhost:6379/0

# --- Logging -----------------------------------------------------------------
# OPTIONAL: Log level (default: info). Values: debug, info, warning, error
# LOG_LEVEL=info
# OPTIONAL: Log format (default: pretty). Values: json, pretty
# LOG_FORMAT=pretty
```

---

### 12. .gitignore Updates

The existing `.gitignore` is missing Python-specific entries. The following must
be added:

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
*.egg
.eggs/

# Virtual environments
.venv/
venv/
ENV/

# Type checking / linting caches
.mypy_cache/
.ruff_cache/
.pytest_cache/

# Coverage
htmlcov/
.coverage
coverage.xml

# Environment files
.env
.env.local
.env.*.local

# Distribution
dist/
```

---

## Existing Code Violations

The following violations in existing code MUST be addressed during foundation work:

### CRITICAL (Security)

1. **`core/billing/stripe/stripe_webhook.py` line 5**: `stripe.api_key = os.environ['STRIPE_SECRET']`
   -- reads secret directly from `os.environ` with no validation. Will crash with
   `KeyError` if unset. Must use `settings.STRIPE_SECRET_KEY`.

2. **`core/ledger/vault/token_rotator.py` line 5**: `VAULT=hvac.Client(url="http://vault:8200", token=os.environ["VAULT_TOKEN"])`
   -- hardcoded Vault URL. Must use settings.

3. **`core/ledger/vault/token_rotator.py` line 6**: `JWT_SECRET=os.environ["JWT_SIGNING_KEY"]`
   -- different env var name than the rest of the codebase (`JWT_SECRET_KEY`). Must
   be unified.

4. **`edgekit/poller/core/fleet_gateway.py` line 9**: `SECRET=os.getenv("FLEET_JWT_SECRET","changeme")`
   -- default secret value of `"changeme"` is a security vulnerability. Must fail
   if unset in non-development environments.

5. **`edgekit/poller/core/fleet_gateway.py` line 15**: Missing import for `HTTPException`.

6. **`core/billing/invoice/invoice_builder.py` line 4**: S3 credentials read directly
   from `os.environ` with no validation. Must use settings.

### HIGH (Architecture)

7. **All files**: No `__init__.py` files exist anywhere under `core/`, `edgekit/`, or
   `sdk/`. Python package imports will fail.

8. **`core/billing/webhook.py` line 3**: `from db import async_session, UsageEvent, Ledger`
   -- imports from a `db` module that does not exist. This file cannot run.

9. **`core/gateway/web/ui/routes/fleet.py` line 3**: Same issue -- `from db import async_session`.

10. **`core/billing/invoice/invoice_builder.py` line 2**: `from db import async_session, Ledger`
    -- same.

11. **`core/billing/invoice/cron_monthly.py`**: `from invoice_builder import build, PERIOD`
    -- relative import without package context. Will fail.

12. **`core/ledger/vault/token_rotator.py`**: Creates its own `FastAPI()` app instance.
    Must be converted to an `APIRouter` and included in the main app, or extracted
    to a separate microservice entry point.

13. **`edgekit/poller/core/fleet_gateway.py`**: Creates its own `FastAPI()` app instance.
    Same issue.

### MEDIUM (Code Quality)

14. **`core/billing/stripe/stripe_webhook.py` line 14**: Bare `except Exception` swallows
    the actual error. Should catch `stripe.error.SignatureVerificationError` specifically.

15. **`core/billing/invoice/invoice_builder.py` line 9**: Raw SQL string passed to
    `s.execute()` without using `text()`. SQLAlchemy 2.x requires `text()` for raw SQL.

16. **`rollup_anchor/bundler.py`**: Uses synchronous `psycopg2` while the rest of the
    codebase uses async SQLAlchemy. This is acceptable because the bundler is a
    standalone daemon, but it should be documented.

17. **`core/ledger/vault/token_rotator.py` line 11**: `datetime.datetime.utcnow()` is
    deprecated in Python 3.12+. Must use `datetime.datetime.now(tz=datetime.UTC)`.

18. **No license headers** on any existing Python file. All files under `core/` require
    the Apache 2.0 header per CONTRIBUTING.md.

---

## Consequences

### Positive

- **Zero-config development**: `docker compose up` starts everything. New developers
  (human or AI agent) can begin work immediately.
- **Fail-fast configuration**: Pydantic Settings validates all env vars at import time.
  Missing secrets are caught before the first request, not at 3 AM in production.
- **Consistent patterns**: Every Python file follows the same import structure, every
  database operation uses the same session factory, every route uses the same auth
  dependency.
- **Security from day one**: Ruff bandit rules, no print statements in production code,
  non-root Docker user, JWT with rotation, no default secrets in production.
- **CI prevents regressions**: No PR can merge to `dev` without passing lint, type
  check, tests, and security audit.

### Negative

- **mypy strict mode is painful initially**: Every existing file will have type errors.
  This is a one-time cost for 348 lines of code.
- **HS256 JWT is symmetric**: If the signing key leaks, all tokens are compromised.
  Migration to RS256 is a future ticket (REN-33 encryption enabler).
- **Single Dockerfile for core only**: `edgekit/` and `rollup_anchor/` need their own
  Dockerfiles. This ADR does not cover those -- they are separate deployable units
  with separate tickets.
- **No database models defined**: This ADR establishes the base classes and session
  factory but does NOT define the actual schema (users, jobs, ledger_entries, etc.).
  That is REN-29.

### Risk

- **WeasyPrint system dependencies**: WeasyPrint requires system libraries (`libcairo`,
  `libpango`, etc.) that are not yet in the Dockerfile. The invoice builder will not
  work until those are added. This is acceptable because invoicing is a Cycle 4 feature.
  When it becomes relevant, add a `weasyprint` stage to the Dockerfile or extract
  invoicing to a separate service.

---

## Alternatives Considered

1. **Poetry instead of pip**: Rejected. Poetry's lock file provides reproducibility but
   adds a dependency on the Poetry tool itself in Docker builds and CI. The project is
   not large enough to benefit from Poetry's workspace features. pip + pyproject.toml
   is sufficient.

2. **uv instead of pip**: Rejected for now. uv is fast but still evolving rapidly. The
   project can migrate to uv later by changing only the `pip install` commands in
   Dockerfile and CI. No code changes required.

3. **Middleware-based auth instead of dependency injection**: Rejected. Middleware auth
   requires maintaining a whitelist of public routes. FastAPI's dependency injection
   is more explicit, more testable, and the community-standard pattern.

4. **Separate services for each component**: Rejected for now. A monorepo with a
   single `core/main.py` entry point is appropriate for the current team size and
   traffic level. The router-based organization (each domain is an `APIRouter`) makes
   future extraction into separate services straightforward.

5. **RS256 JWT from day one**: Rejected. RS256 requires key pair management and
   distribution to edge nodes. HS256 is simpler and sufficient until edge nodes need
   to verify tokens independently. The `JWT_ALGORITHM` setting makes migration a
   configuration change, not a code change.

6. **PostgreSQL RLS (Row-Level Security) from day one**: Deferred. RLS is referenced
   in the patterns library (which was imported from the SAFe harness and targets a
   different stack). RLS is valuable but adds complexity to every migration. It should
   be evaluated as a separate ADR after the schema is defined (REN-29).

---

## Implementation Sequence

The BE Developer MUST implement these files in this order (dependencies flow downward):

```
1. pyproject.toml               -- everything depends on this
2. .env.template                -- documents all env vars
3. .gitignore updates           -- prevent committing secrets/caches
4. core/__init__.py             -- package initialization
5. core/config.py               -- settings (used by everything)
6. core/logging.py              -- structlog config
7. core/db/__init__.py
8. core/db/base.py              -- Base, mixins
9. core/db/session.py           -- engine, session factory
10. core/auth/__init__.py
11. core/auth/models.py         -- Pydantic models
12. core/auth/jwt.py            -- token create/decode
13. core/auth/dependencies.py   -- get_current_user
14. core/middleware/__init__.py
15. core/middleware/logging.py   -- request logging
16. core/middleware/error_handler.py -- exception -> JSON
17. core/api/__init__.py
18. core/api/v1/__init__.py
19. core/api/v1/health.py       -- health endpoint
20. core/models/__init__.py     -- model registry (empty for now)
21. core/main.py                -- FastAPI app
22. alembic.ini                 -- Alembic config
23. alembic/env.py              -- async Alembic
24. alembic/script.py.mako      -- migration template
25. alembic/versions/.gitkeep   -- empty versions dir
26. Dockerfile                  -- multi-stage build
27. docker-compose.yml          -- dev services
28. Makefile                    -- developer commands
29. .github/workflows/ci.yml   -- CI pipeline
30. tests/__init__.py           -- test package
31. tests/conftest.py           -- shared fixtures
32. tests/test_health.py        -- verify health endpoint
```

---

## References

- CLAUDE.md -- project standards (stack definition, commands, methodology)
- CONTRIBUTING.md -- git workflow, commit format, licensing
- DEPENDENCY_FLOW.md -- cycle planning and issue dependencies
- patterns_library/ci/github-actions-workflow.md -- CI pattern (adapted for Python)
- patterns_library/config/environment-config.md -- config pattern (adapted for Pydantic)
- patterns_library/config/structured-logging.md -- logging pattern (adapted for structlog)
- patterns_library/security/secrets-management.md -- secrets pattern
- Linear: REN-61 (this ticket), REN-29 (schema), REN-32 (docker), REN-53 (gateway)

---

**Reviewer**: System Architect (Opus)
**Review Date**: 2026-03-09
