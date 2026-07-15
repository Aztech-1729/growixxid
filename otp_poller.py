"""Background OTP poller.

The VNHOTP API has no webhooks, so after placing an order we poll until the
OTP arrives (or the timeout expires) and then update the user's message.
"""
import asyncio

from config import config
from db import update_order
from keyboards import kb_back
from vnhotp import VNHOTPError, vnhotp


async def poll_and_update(bot, user_id, chat_id, message_id, service, ref, number):
    interval = config.OTP_POLL_INTERVAL
    tries = max(1, int(config.OTP_TIMEOUT / interval))

    for _ in range(tries):
        try:
            if service == "tg":
                d = await vnhotp.tg_get_code(number)
                code = d.get("code")
                pwd = d.get("password")
                if code:
                    await update_order(ref, status="completed", otp=code, password=pwd)
                    await bot.edit_message_text(
                        f"✅ <b>OTP Received!</b>\n\nNumber: <code>{number}</code>\n"
                        f"OTP: <b>{code}</b>\nPassword: <code>{pwd or '—'}</code>",
                        chat_id=chat_id, message_id=message_id, parse_mode="HTML",
                        reply_markup=kb_back("menu"))
                    return
            else:
                code = await vnhotp.wp_get_status(service, ref)
                if code:
                    await update_order(ref, status="completed", otp=code)
                    await bot.edit_message_text(
                        f"✅ <b>OTP Received!</b>\n\nOrder: <code>{ref}</code>\nOTP: <b>{code}</b>",
                        chat_id=chat_id, message_id=message_id, parse_mode="HTML",
                        reply_markup=kb_back("menu"))
                    return
        except VNHOTPError:
            # "OTP not ready yet" -> keep polling
            pass
        await asyncio.sleep(interval)

    await update_order(ref, status="expired")
    try:
        await bot.edit_message_text(
            "⌛ OTP not received within the time limit. Order expired.",
            chat_id=chat_id, message_id=message_id, reply_markup=kb_back("menu"))
    except Exception:
        pass
