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

"""FastAPI application factory and entry point.

Uses a lifespan context manager for clean startup/shutdown of
database connections and other resources.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.api.v1.router import api_v1_router
from core.config import get_settings
from core.database import engine

logger = structlog.get_logger(__name__)


def _configure_logging() -> None:
    """Configure structlog for structured JSON logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context manager.

    Handles startup and shutdown tasks:
    - Startup: configure logging, verify database engine
    - Shutdown: dispose database engine connections
    """
    _configure_logging()
    logger.info("application_startup", app_name=get_settings().app_name)

    yield

    # Cleanup: dispose database engine
    logger.info("application_shutdown")
    await engine.dispose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    settings = get_settings()

    application = FastAPI(
        title="RenderTrust API",
        description="A general-purpose trust fabric for any computational service",
        version="0.1.0",
        docs_url="/docs" if settings.app_debug else None,
        redoc_url="/redoc" if settings.app_debug else None,
        lifespan=lifespan,
    )

    # CORS middleware
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API v1 routes
    application.include_router(api_v1_router)

    # Root-level convenience endpoints
    @application.get("/health")
    async def root_health() -> dict[str, str]:
        """Root health check (alias for /api/v1/health)."""
        return {
            "status": "healthy",
            "version": "0.1.0",
        }

    @application.get("/version")
    async def version() -> dict[str, str]:
        """Return application version information."""
        return {
            "name": settings.app_name,
            "version": "0.1.0",
            "environment": settings.app_env,
        }

    return application


# Module-level app instance for uvicorn
app = create_app()
