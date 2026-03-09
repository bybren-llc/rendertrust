import datetime
import os

import jinja2
import weasyprint
from boto3 import client as s3
from db import async_session  # TODO(REN-87): Migrate from legacy db module to core.database
from sqlalchemy import text

S3 = s3(
    "s3",
    endpoint_url=os.environ["S3_URL"],
    aws_access_key_id=os.environ["S3_KEY"],
    aws_secret_access_key=os.environ["S3_SEC"],
)
TEMPL = jinja2.Environment(loader=jinja2.FileSystemLoader("templates")).get_template("invoice.html")
PERIOD = (datetime.date.today().replace(day=1) - datetime.timedelta(days=1)).strftime("%B %Y")


async def build(account_id: str):
    async with async_session() as s:
        rows = await s.execute(
            text("SELECT created_at, delta_usd FROM ledger_entries WHERE account_id=:a AND date_trunc('month', created_at)=date_trunc('month', now()-interval '1 month')"),
            {"a": account_id},
        )
        items = [
            {"date": r.created_at.date(), "desc": "Ledger activity", "amount": r.delta_usd}
            for r in rows
        ]
        total = sum(i["amount"] for i in items)
    html = TEMPL.render(
        account={"id": account_id, "name": account_id}, items=items, total=total, period=PERIOD
    )
    pdf = weasyprint.HTML(string=html).write_pdf()
    key = f"invoices/{account_id}/{PERIOD.replace(' ', '_')}.pdf"
    S3.put_object(Bucket="wtfb-invoices", Key=key, Body=pdf, ContentType="application/pdf")
    url = S3.generate_presigned_url(
        "get_object", Params={"Bucket": "wtfb-invoices", "Key": key}, ExpiresIn=2592000
    )
    return url, total
