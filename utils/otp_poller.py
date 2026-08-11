"""Background OTP poller.

The VNHOTP API has no webhooks, so after placing an order we poll until the
OTP arrives (or the timeout expires) and then update the user's message.
"""
import asyncio
import time

from aiogram.exceptions import TelegramBadRequest

from core.config import config
from core.db import update_order
from ui.keyboards import kb_back
from services.vnhotp import VNHOTPError, vnhotp
from utils.session_maker import AutoSessionManager, SessionMakerError


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


async def poll_and_update(bot, user_id, chat_id, message_id, service, ref, number, collector=None, _accounted_flag=None):
    interval = config.OTP_POLL_INTERVAL
    tries = max(1, int(config.OTP_TIMEOUT / interval))
    start_time = time.time()

    session_maker = None
    if service == "tg":
        session_maker = AutoSessionManager(number)
        try:
            await session_maker.connect_and_send_code()
        except SessionMakerError as e:
            await _edit_msg(bot, chat_id, message_id, f"❌ Failed to request code from Telegram:\n{e}", reply_markup=None)
            return

    last_elapsed_min = -1
    for i in range(tries):
        try:
            if service == "tg":
                d = await vnhotp.tg_get_code(number)
                code = d.get("code")
                pwd = d.get("password")
                if code:
                    await _edit_msg(bot, chat_id, message_id, "✅ <b>OTP Received! Building session…</b>", parse_mode="HTML")
                    try:
                        session_file = await session_maker.sign_in_and_get_file(code, password=pwd)
                        session_str = session_maker.session_string

                        # Bulk mode: hand the built session to the shared collector
                        # (one zip with ALL sessions is shipped when every order is done)
                        if collector is not None:
                            meta = session_maker.build_meta(password=pwd)
                            note = f"✅ <code>+{number}</code> — OTP: <code>{code}</code>" + (f" | 🔐 2FA: <code>{pwd}</code>" if pwd else "")
                            await collector.add(session_file, meta, note)
                            if _accounted_flag is not None:
                                _accounted_flag[0] = True
                            try:
                                await bot.delete_message(chat_id, message_id)
                            except Exception:
                                pass
                            await update_order(ref, status="completed", otp=code, password=pwd, session_string=session_str or "")
                            return

                        zip_path = session_maker.build_package(password=pwd)
                        session_maker.zip_path = zip_path

                        caption = (
                            f"🎉 <b>Session Ready!</b>\n\n"
                            f"<b>Number:</b> <code>{number}</code>\n"
                            f"<b>OTP:</b> <code>{code}</code>"
                        )
                        if pwd:
                            caption += f"\n🔐 <b>2FA Password:</b> <code>{pwd}</code>"
                        caption += f"\n\n📦 Zip contains: <code>{number}.session</code> + <code>{number}.json</code>"

                        from aiogram.types import FSInputFile
                        from ui.keyboards import kb_get_otp
                        await bot.send_document(
                            chat_id=chat_id,
                            document=FSInputFile(zip_path),
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=kb_get_otp("vnhotp", ref, number)
                        )
                        try:
                            await bot.delete_message(chat_id, message_id)
                        except Exception:
                            pass
                        await update_order(ref, status="completed", otp=code, password=pwd, session_string=session_str or "")
                    except SessionMakerError as e:
                        if collector is not None:
                            await collector.fail(f"❌ <code>+{number}</code>: {e}")
                            if _accounted_flag is not None:
                                _accounted_flag[0] = True
                            await update_order(ref, status="completed", otp=code, password=pwd)
                            return
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"❌ <b>Session build failed.</b>\n\n<b>Error:</b> {e}\n\n<b>Here is your OTP anyway:</b> <code>{code}</code>" + (f"\n🔐 <b>2FA:</b> <code>{pwd}</code>" if pwd else ""),
                            parse_mode="HTML"
                        )
                        try:
                            await bot.delete_message(chat_id, message_id)
                        except Exception:
                            pass
                        await update_order(ref, status="completed", otp=code, password=pwd)
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

        # Show elapsed time periodically so user knows poller is alive
        elapsed = int(time.time() - start_time)
        elapsed_min = elapsed // 60
        remaining = max(0, config.OTP_TIMEOUT - elapsed)
        remaining_min = remaining // 60
        
        if elapsed_min != last_elapsed_min:
            last_elapsed_min = elapsed_min
            try:
                msg_text = "⏳ <b>Waiting for OTP…</b>"
                if service == "tg":
                    msg_text = "⏳ <b>Waiting for Telegram Session OTP…</b>"
                    
                await _edit_msg(
                    bot, chat_id, message_id,
                    f"{msg_text}\n\n"
                    f"<b>Number:</b> <code>{number}</code>\n"
                    f"<i>Waiting for {elapsed_min}m {elapsed % 60}s… Auto-expires in ~{remaining_min}m.</i>\n\n"
                    f"<i>Note: Sometimes Telegram does not send SMS to virtual numbers. If no SMS arrives, the order will automatically cancel and refund.</i>",
                    parse_mode="HTML",
                    reply_markup=None if service == "tg" else kb_back("menu")
                )
            except Exception:
                pass

        await asyncio.sleep(interval)

    from core.db import get_order, credit_wallet
    o = await get_order(ref)
    if o and o.get("status") != "expired" and not o.get("refunded"):
        if float(o.get("price_inr", 0)):
            await credit_wallet(o["user_id"], float(o["price_inr"]), f"Refund for expired order {ref}")
        await update_order(ref, status="expired", refunded=True)
    else:
        await update_order(ref, status="expired")
        
    if session_maker:
        session_maker.cleanup()
    try:
        await _edit_msg(
            bot, chat_id, message_id,
            "⌛ <b>OTP not received within the time limit.</b>\n\nOrder expired and refunded. Please try again.",
            reply_markup=None if service == "tg" else kb_back("menu"), parse_mode="HTML")
    except Exception:
        pass
