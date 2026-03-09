import os

import stripe
from fastapi import APIRouter, HTTPException, Request
from ledger.credit import credit

router = APIRouter()
stripe.api_key = os.environ['STRIPE_SECRET']
ENDPOINT_SECRET = os.environ['STRIPE_WEBHOOK_SECRET']
CREDIT_MAP = { 'cred10': 100, 'cred50': 550 }
@router.post('/webhooks/stripe')
async def stripe_hook(req: Request):
    sig = req.headers.get('stripe-signature')
    payload = await req.body()
    try:
        event = stripe.Webhook.construct_event(payload, sig, ENDPOINT_SECRET)
    except Exception:
        raise HTTPException(status_code=400)
    if event['type'] == 'checkout.session.completed':
        sess = event['data']['object']
        sku = sess['display_items'][0]['price']['nickname']
        credits = CREDIT_MAP[sku]
        creator_id = sess['client_reference_id']
        await credit(creator_id, credits)
    return {'received': True}
