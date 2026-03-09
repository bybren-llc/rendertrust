import datetime
import os

import hvac
import jwt
from fastapi import FastAPI

app = FastAPI()
VAULT = hvac.Client(url="http://vault:8200", token=os.environ["VAULT_TOKEN"])
JWT_SECRET = os.environ["JWT_SIGNING_KEY"]


@app.post("/rotate")
async def rotate(node_id: str):
    token = jwt.encode(
        {
            "sub": node_id,
            "iat": datetime.datetime.utcnow(),
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    VAULT.secrets.kv.v2.create_or_update_secret(path=f"edge/{node_id}", secret={"token": token})
    return {"token": token}
