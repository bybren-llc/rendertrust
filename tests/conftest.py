# Copyright 2025 ByBren, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared pytest fixtures for the RenderTrust test suite.

Provides:
- ``test_engine``  -- session-scoped async SQLAlchemy engine (SQLite in-memory)
- ``db_session``   -- per-test async session with automatic rollback isolation
- ``client``       -- async HTTP client wired to a fresh FastAPI app instance
- ``test_user``    -- pre-created ``User`` row available for auth tests
- ``admin_user``   -- pre-created admin ``User`` row
- ``auth_headers`` -- ``Authorization: Bearer <jwt>`` headers for the test user
- ``admin_auth_headers`` -- same for admin user

All async fixtures use **pytest-asyncio** with ``asyncio_mode = "auto"``
(configured in ``pyproject.toml``).
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Environment overrides -- MUST come before any application imports so that
# ``core.config.get_settings()`` picks up the test values.
# ---------------------------------------------------------------------------
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-not-for-production")
os.environ.setdefault(
    "DATABASE_URL",
    "sqlite+aiosqlite:///:memory:",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_fake")

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
from httpx import ASGITransport, AsyncClient
from passlib.hash import bcrypt
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.auth.jwt import create_access_token
from core.database import Base, get_db_session
from core.ledger.anchor.models import Base as AnchorBase
from core.main import create_app
from core.models.base import User

# ---------------------------------------------------------------------------
# Test database URL -- uses in-memory SQLite so no external DB server needed.
# Override with ``TEST_DATABASE_URL`` env-var to point at a real Postgres
# instance when running integration tests against a live database.
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "sqlite+aiosqlite:///:memory:",
)

TEST_USER_PASSWORD = "testpassword123"  # noqa: S105  -- test-only secret


# ---------------------------------------------------------------------------
# Session-scoped engine: created once, tables created once, torn down at end.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
async def test_engine():
    """Create a session-scoped async engine and bootstrap the schema."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    # When running against PostgreSQL (CI), Alembic migrations have already
    # created the schema (including PostgreSQL-specific ENUM types).  Calling
    # metadata.create_all on top of that causes "type already exists" errors.
    # Only bootstrap via create_all for SQLite (unit tests).
    _is_sqlite = TEST_DATABASE_URL.startswith("sqlite")

    if _is_sqlite:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Anchor models use a separate Base — create those tables too.
            await conn.run_sync(AnchorBase.metadata.create_all)

    yield engine

    if _is_sqlite:
        async with engine.begin() as conn:
            await conn.run_sync(AnchorBase.metadata.drop_all)
            await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ---------------------------------------------------------------------------
# Per-test session with savepoint rollback for full isolation.
# ---------------------------------------------------------------------------
@pytest.fixture
async def db_session(
    test_engine,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a per-test database session that rolls back after each test.

    Uses a nested transaction (savepoint) so that even if test code
    calls ``session.commit()``, the outer transaction still rolls back.
    """
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        # Use begin_nested() for savepoint isolation — prevents commit()
        # inside tests from breaking the rollback strategy.
        nested = await connection.begin_nested()
        session_factory = async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with session_factory() as session:
            yield session

        # Roll back the savepoint, then the outer transaction.
        if nested.is_active:
            await nested.rollback()
        await transaction.rollback()


# ---------------------------------------------------------------------------
# Async HTTP test client with dependency overrides.
# ---------------------------------------------------------------------------
@pytest.fixture
async def client(
    db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client with database session override."""
    app = create_app()

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test user fixtures.
# ---------------------------------------------------------------------------
@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Insert and return a test user with a known password."""
    user = User(
        email="test@rendertrust.com",
        name="Test User",
        hashed_password=bcrypt.hash(TEST_USER_PASSWORD),
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Insert and return an admin test user."""
    user = User(
        email="admin@rendertrust.com",
        name="Admin User",
        hashed_password=bcrypt.hash(TEST_USER_PASSWORD),
        is_active=True,
        is_admin=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# ---------------------------------------------------------------------------
# JWT auth header fixtures.
# ---------------------------------------------------------------------------
@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    """Return ``Authorization: Bearer <token>`` headers for ``test_user``."""
    token = create_access_token({"sub": str(test_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_auth_headers(admin_user: User) -> dict[str, str]:
    """Return ``Authorization: Bearer <token>`` headers for ``admin_user``."""
    token = create_access_token({"sub": str(admin_user.id)})
    return {"Authorization": f"Bearer {token}"}
