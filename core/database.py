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

"""SQLAlchemy 2.x async database setup.

Provides async engine, session factory, and dependency injection
for FastAPI endpoints via get_db_session().
"""

import datetime
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy models.

    Provides common columns (id, created_at, updated_at) via TimestampMixin.
    All models should inherit from Base.
    """


def _utcnow() -> datetime.datetime:
    """Return current UTC time with microsecond precision.

    Used as Python-level default for timestamps. This ensures entries
    created in quick succession (e.g. in tests with SQLite) have
    distinct timestamps, unlike server_default=func.now() which may
    have only second-level precision in SQLite.
    """
    return datetime.datetime.now(tz=datetime.UTC)


class TimestampMixin:
    """Mixin providing created_at and updated_at timestamp columns.

    created_at is set automatically on insert.
    updated_at is set automatically on insert and update.
    """

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        onupdate=_utcnow,
        nullable=False,
    )


class BaseModel(TimestampMixin, Base):
    """Abstract base model with UUID primary key and timestamps.

    All domain models should inherit from this class.
    Provides: id (UUID), created_at, updated_at.
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )


def _create_engine() -> AsyncEngine:
    """Create an async SQLAlchemy engine from application settings.

    Pool size and overflow are configured from environment variables.
    SQLite (used in tests) does not support pool_size/max_overflow,
    so those parameters are omitted for sqlite:// URLs.
    """
    settings = get_settings()
    kwargs: dict[str, object] = {"echo": settings.app_debug}

    # SQLite uses StaticPool and doesn't accept pool_size/max_overflow.
    if not settings.database_url.startswith("sqlite"):
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow

    return create_async_engine(settings.database_url, **kwargs)


# Module-level engine and session factory.
# Initialized lazily on first import; overridden in tests.
engine = _create_engine()
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session.

    Usage:
        @router.get("/items")
        async def list_items(session: AsyncSession = Depends(get_db_session)):
            ...

    The session is automatically closed when the request completes.
    """
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
