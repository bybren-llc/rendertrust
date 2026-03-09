import asyncio
import random

from fastapi import FastAPI

app = FastAPI()


@app.post("/execute")
async def exec(job: dict):
    await asyncio.sleep(random.uniform(0.1, 0.5))
    return {"ok": True, "jobId": job.get("id")}
