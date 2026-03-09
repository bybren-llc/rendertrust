from db import Ledger, UsageEvent, async_session
from fastapi import APIRouter, Request
from sqlalchemy import func, select

router = APIRouter()

PLATFORM_FEE = 0.15
THRESHOLD = 1000.0  # USD


@router.post("/webhooks/agentspace/usage")
async def usage_webhook(req: Request):
    payload = await req.json()
    eid = payload["eventId"]
    async with async_session() as s:
        exists = await s.scalar(select(UsageEvent).where(UsageEvent.event_id == eid))
        if exists:
            return {"status": "ignored"}  # idempotent
        ue = UsageEvent(
            event_id=eid,
            module_id=payload["moduleId"],
            creator_id=payload["creatorId"],
            units=payload["units"],
            unit_price_usd=payload["unitPriceUsd"],
        )
        s.add(ue)
        await s.flush()
        gross = ue.gross_usd
        total_sales = await s.scalar(
            select(func.sum(UsageEvent.gross_usd)).where(UsageEvent.module_id == ue.module_id)
        )
        fee_rate = 0.0 if total_sales < THRESHOLD else PLATFORM_FEE
        fee = gross * fee_rate
        s.add_all(
            [
                Ledger(account_id=ue.creator_id, delta_usd=-gross),
                Ledger(account_id=f"module:{ue.module_id}", delta_usd=gross - fee),
                Ledger(account_id="wtfb_platform", delta_usd=fee),
            ]
        )
        await s.commit()
    return {"status": "ok"}
