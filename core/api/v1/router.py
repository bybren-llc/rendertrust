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

Includes health checks, authentication, credits, billing, and scheduler.
"""

from fastapi import APIRouter

from core.api.v1.auth import router as auth_router
from core.api.v1.credits import router as credits_router
from core.api.v1.health import router as health_router
from core.billing.stripe.stripe_webhook import router as stripe_webhook_router
from core.scheduler.router import router as scheduler_router

api_v1_router = APIRouter(prefix="/api/v1")

# Health checks
api_v1_router.include_router(health_router, tags=["health"])

# Authentication
api_v1_router.include_router(auth_router, tags=["auth"])

# Billing webhooks
api_v1_router.include_router(stripe_webhook_router, tags=["billing"])

# Credits
api_v1_router.include_router(credits_router, tags=["credits"])

# Scheduler (edge node management)
api_v1_router.include_router(scheduler_router, tags=["scheduler"])
