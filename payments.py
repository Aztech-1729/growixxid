"""Razorpay integration: UPI QR codes + webhook signature verification.

Flow: user clicks Add Funds -> we create a Razorpay *UPI QR code* (single-use,
fixed amount) -> bot sends the QR image -> user scans & pays via any UPI app
-> Razorpay POSTs a webhook (event `payment.captured`) to /webhook/razorpay
-> we verify the HMAC signature and credit the wallet.
"""
import time

import razorpay

from config import config


_client = None


def client():
    global _client
    if _client is None:
        _client = razorpay.Client(auth=(config.RAZORPAY_KEY_ID, config.RAZORPAY_KEY_SECRET))
    return _client


def create_qr_code(user_id: int, amount_inr: float, note: str = "Wallet top-up"):
    """Create a single-use UPI QR code. Returns (qr_image_url, qr_code_id)."""
    amount_paise = int(round(amount_inr * 100))
    res = client().qr_code.create({
        "type": "upi_qr",
        "name": "GROWIXX Top-up",
        "usage": "single_use",
        "fixed_amount": True,
        "payment_amount": amount_paise,
        "description": note,
        "notes": {"user_id": str(user_id)},
        "close_by": int(time.time()) + 1800,
    })
    return res.get("qr_code_url"), res.get("id")


def verify_webhook(body, signature: str) -> bool:
    secret = config.RAZORPAY_WEBHOOK_SECRET
    # Dev/test mode: no secret configured -> accept but flag as unverified.
    if not secret or secret == "xxxxxxxxxxxx":
        print("⚠️  Webhook signature NOT verified (RAZORPAY_WEBHOOK_SECRET not set). "
              "Set it in .env before going to production.")
        return True
    try:
        razorpay.Utility.verify_webhook_signature(
            body.decode("utf-8") if isinstance(body, bytes) else body,
            signature, secret)
        return True
    except Exception as e:
        print("❌ Webhook signature verification failed:", e)
        return False
