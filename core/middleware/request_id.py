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

"""Request ID correlation middleware.

Generates a unique UUID for each request, binds it to the structlog
context via contextvars, and includes it in the response X-Request-ID header.
Accepts an incoming X-Request-ID header from the client to support
distributed tracing across services.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

if TYPE_CHECKING:
    from fastapi import Request, Response

logger = structlog.get_logger(__name__)

_REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware that generates and propagates request IDs.

    For each incoming request:
    1. Reads the client-provided X-Request-ID header, or generates a new UUID.
    2. Clears and rebinds structlog contextvars so every log statement
       within the request lifecycle includes ``request_id``.
    3. Stores the ID on ``request.state.request_id`` for route handlers.
    4. Sets the X-Request-ID response header for client correlation.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Use client-provided ID if present, otherwise generate
        request_id = request.headers.get(_REQUEST_ID_HEADER) or str(uuid.uuid4())

        # Bind to structlog context (available to all log calls in this request)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Store on request.state for access in route handlers
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[_REQUEST_ID_HEADER] = request_id

        return response
