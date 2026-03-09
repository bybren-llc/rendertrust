import datetime
import os

import jwt
from fastapi import FastAPI, Header
from influxdb_client import InfluxDBClient, Point

app = FastAPI()
client = InfluxDBClient(url="http://influxdb:8086", token="root:root", org="wtfb")
write = client.write_api()

SECRET = os.getenv("FLEET_JWT_SECRET", "changeme")


def auth_check(tok):
    try:
        return jwt.decode(tok.split()[1], SECRET, algorithms=["HS256"])["sub"]
    except Exception:
        raise HTTPException(status_code=401)


@app.post("/heartbeat")
async def hb(stats: dict, authorization: str = Header(...)):
    node = auth_check(authorization)
    p = Point("gpuFleet").tag("node", node)
    for k, v in stats.items():
        p = p.field(k, v)
    p = p.time(datetime.datetime.utcnow())
    write.write("gpu", record=p)
    return {"ok": True}
