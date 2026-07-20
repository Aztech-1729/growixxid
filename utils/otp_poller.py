"""Background OTP poller.

The VNHOTP API has no webhooks, so after placing an order we poll until the
OTP arrives (or the timeout expires) and then update the user's message.
"""
import asyncio

from aiogram.exceptions import TelegramBadRequest

from core.config import config
from core.db import update_order
from ui.keyboards import kb_back
from services.vnhotp import VNHOTPError, vnhotp


async def _edit_msg(bot, chat_id, message_id, text, reply_markup=None, parse_mode=None):
    try:
        await bot.edit_message_text(
            text, chat_id=chat_id, message_id=message_id,
            reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest:
        try:
            await bot.edit_message_caption(
                chat_id=chat_id, message_id=message_id,
                caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TelegramBadRequest:
            pass


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
                    await _edit_msg(
                        bot, chat_id, message_id,
                        f"✅ <b>OTP Received!</b>\n\nNumber: <code>{number}</code>\n"
                        f"OTP: <b>{code}</b>\nPassword: <code>{pwd or '—'}</code>",
                        reply_markup=kb_back("menu"), parse_mode="HTML")
                    return
            else:
                code = await vnhotp.wp_get_status(service, ref)
                if code:
                    await update_order(ref, status="completed", otp=code)
                    await _edit_msg(
                        bot, chat_id, message_id,
                        f"✅ <b>OTP Received!</b>\n\nOrder: <code>{ref}</code>\nOTP: <b>{code}</b>",
                        reply_markup=kb_back("menu"), parse_mode="HTML")
                    return
        except VNHOTPError:
            pass
        await asyncio.sleep(interval)

    await update_order(ref, status="expired")
    try:
        await _edit_msg(
            bot, chat_id, message_id,
            "⌛ OTP not received within the time limit. Order expired.",
            reply_markup=kb_back("menu"))
    except Exception:
        pass
