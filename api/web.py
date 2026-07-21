"""aiohttp webhook server for Razorpay (runs in the same loop as the bot)."""
import json

from aiohttp import web

from core.db import credit_wallet, get_user
from utils.payments import verify_webhook
from utils.nowpayments import verify_ipn
from utils.rates import usd_to_inr
from handlers.common import send_start_to_user_id
import logging

_bot = None
PENDING_PAYMENT_MESSAGES = {}


def set_bot(bot) -> None:
    global _bot
    _bot = bot


async def razorpay_callback(request: web.Request):
    # GET redirect target after a successful payment (payment link callback_url,
    # callback_method="get"). Razorpay bounces the user's browser here with
    # query params; we just show a friendly confirmation.
    return web.Response(
        text="✅ Payment received! Your wallet will be credited automatically "
             "within a few seconds.",
        content_type="text/html",
        charset="utf-8")


async def razorpay_webhook(request: web.Request):
    body = await request.read()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not verify_webhook(body, signature):
        return web.Response(status=400, text="invalid signature")
    try:
        data = json.loads(body)
    except Exception:
        return web.Response(status=400, text="bad json")

    event = data.get("event")
    if event in ("payment_link.paid", "payment.captured"):
        await _credit_from_payment(data)
    return web.Response(status=200, text="ok")


async def _credit_from_payment(data: dict) -> None:
    try:
        payment = data["payload"]["payment"]["entity"]
        notes = payment.get("notes", {})
        user_id = int(notes.get("user_id", 0))
        amount_inr = (payment.get("amount") or 0) / 100.0
    except Exception:
        return
    if not user_id:
        return
    await credit_wallet(user_id, amount_inr, "Razorpay top-up")
    if _bot:
        try:
            msg_id = PENDING_PAYMENT_MESSAGES.pop(user_id, None)
            if msg_id:
                try:
                    await _bot.delete_message(chat_id=user_id, message_id=msg_id)
                except Exception:
                    pass
            
            await _bot.send_message(
                user_id,
                f"✅ <b>Payment received!</b>\n₹{amount_inr:.2f} added to your wallet.",
                parse_mode="HTML")
                
            user = await get_user(user_id)
            first_name = user.get("first_name", "User") if user else "User"
            await send_start_to_user_id(_bot, user_id, first_name)
        except Exception:
            pass


async def nowpayments_webhook(request: web.Request):
    body = await request.read()
    signature = request.headers.get("x-nowpayments-sig", "")
    
    if not verify_ipn(body, signature):
        logging.error("NOWPayments IPN signature mismatch")
        return web.Response(status=400, text="invalid signature")
        
    try:
        data = json.loads(body)
    except Exception:
        return web.Response(status=400, text="bad json")
        
    status = data.get("payment_status")
    # Only credit on successful payment
    if status == "finished":
        order_id = data.get("order_id", "")
        # order_id format: U{user_id}-{timestamp}
        if not order_id.startswith("U"):
            return web.Response(status=200, text="ok (ignored)")
            
        try:
            user_id = int(order_id.split("-")[0][1:])
            amount_usd = float(data.get("price_amount", 0))
            
            # Convert USD deposit amount back to INR based on live rate
            rate = await usd_to_inr()
            amount_inr = amount_usd * rate
            
            await credit_wallet(user_id, amount_inr, "NOWPayments Crypto Top-up")
            
            if _bot:
                try:
                    msg_id = PENDING_PAYMENT_MESSAGES.pop(user_id, None)
                    if msg_id:
                        try:
                            await _bot.delete_message(chat_id=user_id, message_id=msg_id)
                        except Exception:
                            pass
                            
                    await _bot.send_message(
                        user_id,
                        f"🪙 <b>Crypto Payment Confirmed!</b>\n"
                        f"${amount_usd:.2f} (₹{amount_inr:.2f}) has been added to your wallet.",
                        parse_mode="HTML")
                        
                    user = await get_user(user_id)
                    first_name = user.get("first_name", "User") if user else "User"
                    await send_start_to_user_id(_bot, user_id, first_name)
                except Exception:
                    pass
        except Exception as e:
            logging.error(f"Error processing NOWPayments IPN: {e}")
            
    return web.Response(status=200, text="ok")


def make_app():
    app = web.Application()
    app.router.add_post("/webhook/razorpay", razorpay_webhook)
    app.router.add_get("/webhook/razorpay", razorpay_callback)
    app.router.add_post("/webhook/nowpayments", nowpayments_webhook)
    app.router.add_get("/healthz", lambda r: web.Response(text="ok"))
    return app
