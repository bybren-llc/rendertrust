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

"""Authentication middleware for FastAPI.

Optional middleware that extracts Bearer tokens and sets request.state.user.
Endpoints can also use Depends(get_current_user) directly for more explicit
dependency injection.
"""

import structlog
from fastapi import Request, Response
from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from core.auth.jwt import verify_token

logger = structlog.get_logger(__name__)

# Paths that skip authentication
_PUBLIC_PATHS = frozenset({
    "/health",
    "/health/ready",
    "/version",
    "/docs",
    "/redoc",
    "/openapi.json",
})


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that extracts JWT from Authorization header.

    Sets request.state.user_id if a valid token is present.
    Does not block requests without tokens -- use Depends(get_current_user)
    on endpoints that require authentication.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Process the request, extracting auth info if present."""
        request.state.user_id = None

        # Skip token extraction for public paths
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
            try:
                payload = verify_token(token)
                request.state.user_id = payload.sub
            except (JWTError, Exception):  # noqa: BLE001
                # Token is invalid; request.state.user_id stays None.
                # Endpoints requiring auth will return 401 via Depends().
                logger.debug("auth_middleware_token_invalid", path=request.url.path)

        return await call_next(request)
