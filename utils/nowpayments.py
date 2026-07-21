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


async def get_min_amount(coin: str, fiat_currency: str = "usd") -> float:
    """
    Fetches the minimum allowed deposit amount for a specific coin in fiat.
    Returns the amount as a float.
    """
    if not config.NOWPAYMENTS_API_KEY:
        return 0.0
        
    url = f"https://api.nowpayments.io/v1/min-amount?currency_from={coin}&currency_to={fiat_currency}"
    headers = {"x-api-key": config.NOWPAYMENTS_API_KEY}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            data = await resp.json()
            if resp.status == 200:
                return float(data.get("fiat_equivalent", 0.0))
            return 0.0


async def create_payment(user_id: int, amount_usd: float, coin: str, description: str = "Wallet Top-up"):
    """
    Creates a direct NOWPayments transaction for a specific coin.
    Returns (pay_address, pay_amount, payment_id).
    """
    if not config.NOWPAYMENTS_API_KEY:
        raise RuntimeError("NOWPAYMENTS_API_KEY not configured.")
        
    url = "https://api.nowpayments.io/v1/payment"
    
    headers = {
        "x-api-key": config.NOWPAYMENTS_API_KEY,
        "Content-Type": "application/json"
    }
    
    order_ref = f"U{user_id}-{int(time.time())}"
    
    payload = {
        "price_amount": float(amount_usd),
        "price_currency": "usd",
        "pay_currency": coin.lower(),
        "order_id": order_ref,
        "order_description": description,
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json()
            
            if resp.status not in (200, 201):
                logging.error(f"NOWPayments create_payment failed: {data}")
                raise Exception(data.get("message", "API Error"))
                
            return data.get("pay_address"), data.get("pay_amount"), data.get("payment_id")


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
