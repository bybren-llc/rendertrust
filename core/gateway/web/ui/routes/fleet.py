from db import async_session
from fastapi import APIRouter
from sqlalchemy import text

router=APIRouter()
@router.get('/fleet')
async def fleet():
    async with async_session() as s:
        rows=await s.execute(text('SELECT * FROM fleet_overview'))
        return [dict(r) for r in rows]
