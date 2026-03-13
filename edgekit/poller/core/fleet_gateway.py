import datetime
import os

from fastapi import FastAPI, Header, HTTPException
from influxdb_client import InfluxDBClient, Point
from jose import JWTError, jwt

app = FastAPI()
client = InfluxDBClient(url="http://influxdb:8086", token="root:root", org="wtfb")
write = client.write_api()

SECRET = os.getenv("FLEET_JWT_SECRET", "changeme")


def auth_check(tok):
    try:
        return jwt.decode(tok.split()[1], SECRET, algorithms=["HS256"])["sub"]
    except JWTError:
        raise HTTPException(status_code=401)


@app.post("/heartbeat")
async def hb(stats: dict, authorization: str = Header(...)):
    node = auth_check(authorization)
    p = Point("gpuFleet").tag("node", node)
    for k, v in stats.items():
        p = p.field(k, v)
    p = p.time(datetime.datetime.now(tz=datetime.UTC))
    write.write("gpu", record=p)
    return {"ok": True}
