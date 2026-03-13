from db import Ledger, async_session  # TODO(REN-87): Migrate from legacy db module to core.database


async def credit(creator_id: str, amount: float):
    async with async_session() as s:
        s.add(Ledger(account_id=creator_id, delta_usd=amount))
        await s.commit()
