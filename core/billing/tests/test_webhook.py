from fastapi import FastAPI
from fastapi.testclient import TestClient
from webhook import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

def test_idempotent():
    payload = {"eventId":"1111-2222","moduleId":"color","creatorId":"u1","units":10,"unitPriceUsd":0.10}
    r1 = client.post("/webhooks/agentspace/usage", json=payload)
    assert r1.status_code==200
    r2 = client.post("/webhooks/agentspace/usage", json=payload)
    assert r2.json()["status"]=="ignored"
