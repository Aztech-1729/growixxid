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
from utils.session_maker import AutoSessionManager, SessionMakerError
from aiogram.types import FSInputFile


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

    session_maker = None
    if service == "tg":
        session_maker = AutoSessionManager(number)
        try:
            await session_maker.connect_and_send_code()
        except SessionMakerError as e:
            await _edit_msg(bot, chat_id, message_id, f"❌ Failed to request code from Telegram:\n{e}", reply_markup=kb_back("menu"))
            return

    for _ in range(tries):
        try:
            if service == "tg":
                d = await vnhotp.tg_get_code(number)
                code = d.get("code")
                pwd = d.get("password")
                if code:
                    await _edit_msg(bot, chat_id, message_id, "✅ <b>OTP Received! Generating session...</b>", parse_mode="HTML")
                    try:
                        session_file = await session_maker.sign_in_and_get_file(code)
                        
                        doc = FSInputFile(session_file)
                        await bot.send_document(
                            chat_id=chat_id,
                            document=doc,
                            caption=f"🎉 Here is your `.session` file for +{number}!\nPassword: <code>{pwd or '—'}</code>",
                            parse_mode="HTML",
                            reply_markup=kb_back("menu")
                        )
                        await bot.delete_message(chat_id, message_id)
                        await update_order(ref, status="completed", otp=code, password=pwd)
                    except SessionMakerError as e:
                        await _edit_msg(bot, chat_id, message_id, f"❌ Failed to create session:\n{e}", reply_markup=kb_back("menu"))
                        # Let's still save the order, but it's completed on provider side. The user can't use it, so we should probably refund.
                        # However, VNHOTP charged us. We can't refund the provider. We'll just complete the order.
                        await update_order(ref, status="completed", otp=code, password=pwd)
                        
                    if session_maker:
                        session_maker.cleanup()
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
    if session_maker:
        session_maker.cleanup()
    try:
        await _edit_msg(
            bot, chat_id, message_id,
            "⌛ OTP not received within the time limit. Order expired.",
            reply_markup=kb_back("menu"))
    except Exception:
        pass
