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
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from core.api.v1.router import api_v1_router
from core.config import get_settings
from core.database import engine
from core.metrics import setup_metrics
from core.middleware.request_id import RequestIdMiddleware

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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add OWASP-recommended security headers to all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # HSTS only in production (requires HTTPS)
        if get_settings().is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


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
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS middleware
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    # Security headers middleware (wraps CORS so it runs on all responses)
    application.add_middleware(SecurityHeadersMiddleware)

    # Prometheus metrics middleware and /metrics endpoint
    setup_metrics(application)

    # Request ID must be outermost (added last) so all logging has request_id
    application.add_middleware(RequestIdMiddleware)

    # Include API v1 routes
    application.include_router(api_v1_router)

    # x402 payment middleware (PoC -- disabled by default)
    if settings.x402_enabled:
        from core.gateway.x402.middleware import configure_x402
        from core.gateway.x402.routes import router as x402_router

        application.include_router(x402_router, prefix="/api/v1")
        configure_x402(
            application,
            pay_to=settings.x402_pay_to,
            facilitator_url=settings.x402_facilitator_url,
            network=settings.x402_network,
            routes={
                "POST /api/v1/x402/compute": {
                    "price": settings.x402_compute_price,
                    "description": "Compute job (x402 PoC)",
                },
            },
        )

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
