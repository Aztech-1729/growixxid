"""aiohttp webhook server for Razorpay (runs in the same loop as the bot)."""
import json

from aiohttp import web

from core.config import config
from core.db import credit_wallet
from utils.payments import verify_webhook

_bot = None


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
        content_type="text/html; charset=utf-8")


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
            await _bot.send_message(
                user_id,
                f"✅ <b>Payment received!</b>\n₹{amount_inr:.2f} added to your wallet.",
                parse_mode="HTML")
        except Exception:
            pass


def make_app():
    app = web.Application()
    app.router.add_post("/webhook/razorpay", razorpay_webhook)
    app.router.add_get("/webhook/razorpay", razorpay_callback)
    app.router.add_get("/healthz", lambda r: web.Response(text="ok"))
    return app
