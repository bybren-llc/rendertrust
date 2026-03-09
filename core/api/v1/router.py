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

"""API v1 router aggregating all sub-routers.

Includes health checks and authentication. Billing and fleet sub-routers
will be added as they are implemented.
"""

from fastapi import APIRouter

from core.api.v1.auth import router as auth_router
from core.api.v1.health import router as health_router

api_v1_router = APIRouter(prefix="/api/v1")

# Health checks
api_v1_router.include_router(health_router, tags=["health"])

# Authentication
api_v1_router.include_router(auth_router, tags=["auth"])
