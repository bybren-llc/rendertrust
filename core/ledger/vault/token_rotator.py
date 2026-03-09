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

"""Edge-node token rotation service.

Generates short-lived JWTs for edge nodes and stores them in HashiCorp Vault.
Tokens are rotated on demand via the ``/rotate`` endpoint.
"""

import datetime
import os

import hvac
import structlog
from fastapi import FastAPI
from jose import jwt

logger = structlog.get_logger(__name__)

app = FastAPI()
VAULT = hvac.Client(url="http://vault:8200", token=os.environ["VAULT_TOKEN"])
JWT_SECRET = os.environ["JWT_SIGNING_KEY"]


@app.post("/rotate")
async def rotate(node_id: str):
    """Rotate the JWT for a given edge node.

    Creates a new 24-hour token, stores it in Vault, and returns it to the caller.

    Args:
        node_id: Unique identifier of the edge node requesting rotation.

    Returns:
        Dictionary containing the newly issued JWT.
    """
    now = datetime.datetime.now(tz=datetime.UTC)
    token = jwt.encode(
        {
            "sub": node_id,
            "iat": now,
            "exp": now + datetime.timedelta(hours=24),
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    VAULT.secrets.kv.v2.create_or_update_secret(
        path=f"edge/{node_id}", secret={"token": token}
    )
    logger.info("edge_token_rotated", node_id=node_id)
    return {"token": token}
