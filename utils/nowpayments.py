"""NOWPayments (Crypto) integration: generate invoice + webhook signature verification.

Flow: user clicks Add Funds -> chooses Crypto -> enters amount -> we call NOWPayments API
-> generate an invoice URL -> user clicks and pays on NOWPayments page
-> NOWPayments POSTs IPN to /webhook/nowpayments -> verify HMAC -> credit wallet.
"""
import hmac
import hashlib
import json
import logging
import aiohttp
import time

from core.config import config


async def create_invoice(user_id: int, amount_usd: float, description: str = "Wallet Top-up"):
    """
    Creates a NOWPayments invoice.
    Returns (invoice_url, payment_id).
    """
    if not config.NOWPAYMENTS_API_KEY:
        raise RuntimeError("NOWPAYMENTS_API_KEY not configured.")
        
    url = "https://api.nowpayments.io/v1/invoice"
    
    headers = {
        "x-api-key": config.NOWPAYMENTS_API_KEY,
        "Content-Type": "application/json"
    }
    
    # We use order_id to store the user_id so the IPN callback knows who to credit.
    # We can format it as "uid_{user_id}_{timestamp}" to keep it unique, but just user_id is fine 
    # since NOWPayments generates its own unique payment_id.
    order_ref = f"U{user_id}-{int(time.time())}"
    
    payload = {
        "price_amount": float(amount_usd),
        "price_currency": "usd",
        "order_id": order_ref,
        "order_description": description,
        "success_url": f"https://t.me/{config.BOT_USERNAME}"
    }
    
    # Send request
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()
            
            if resp.status not in (200, 201):
                logging.error(f"NOWPayments create_invoice failed: {data}")
                raise Exception(data.get("message", "API Error"))
                
            return data.get("invoice_url"), data.get("id")


def verify_ipn(body: str | bytes, signature: str) -> bool:
    """
    Verifies the HMAC-SHA512 signature from NOWPayments webhook.
    NOWPayments hashes the sorted JSON body keys using the IPN secret.
    """
    secret = config.NOWPAYMENTS_IPN_SECRET
    if not secret:
        logging.warning("NOWPAYMENTS_IPN_SECRET not set. IPN signature NOT verified.")
        return True
        
    try:
        # NOWPayments sorts the keys alphabetically before hashing
        if isinstance(body, bytes):
            body_str = body.decode("utf-8")
        else:
            body_str = body
            
        request_data = json.loads(body_str)
        sorted_data = dict(sorted(request_data.items()))
        sorted_json_str = json.dumps(sorted_data, separators=(',', ':'))
        
        expected_sig = hmac.new(
            secret.encode("utf-8"), 
            sorted_json_str.encode("utf-8"), 
            hashlib.sha512
        ).hexdigest()
        
        if hmac.compare_digest(expected_sig, signature):
            return True
            
        raise Exception("Signature mismatch")
    except Exception as e:
        logging.error(f"NOWPayments webhook signature verification failed: {e}")
        return False
