import html

from aiogram import Router, F
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, InputMediaPhoto, BufferedInputFile
from aiogram.exceptions import TelegramBadRequest

from core.config import config
from core.db import register_user
from ui.keyboards import kb_back, kb_main

router = Router()


async def _is_member(bot, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member("@" + config.FORCE_JOIN_CHANNEL, user_id)
        return m.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED)
    except Exception:
        return False


async def _edit(msg, text, reply_markup=None, parse_mode=None):
    try:
        await msg.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest:
        try:
            await msg.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TelegramBadRequest:
            pass


async def _send_main_menu(call_or_msg, user_id: int, first_name: str):
    text = (
        f"<tg-emoji emoji-id='5780560530515171033'>💎</tg-emoji> <b>𝙂𝙍𝙊𝙒𝙄𝙓𝙓 𝚸𝚪𝚵𝚳𝚰𝐔𝚳</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Welcome, <b>{html.escape(first_name)}</b>!\n"
        f"Your premier gateway for instant virtual numbers.\n\n"
        f"<tg-emoji emoji-id='5330237710655306682'>📱</tg-emoji> <b>Top Services:</b> Telegram, WhatsApp, & 3000+ more!\n"
        f"<tg-emoji emoji-id='6028517788606272241'>💰</tg-emoji> <b>Automated:</b> Get your OTPs instantly 24/7.\n\n"
        f"<i>Tap <b>Services</b> below to begin.</i>"
    )
    kb = kb_main(user_id in config.ADMIN_IDS)
    
    try:
        with open(config.START_IMAGE, "rb") as f:
            photo_data = f.read()
        photo_input = BufferedInputFile(photo_data, filename="start.jpg")
    except Exception:
        photo_input = config.START_IMAGE

    if isinstance(call_or_msg, Message):
        await call_or_msg.answer_photo(photo=photo_input, caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        call = call_or_msg
        try:
            await call.message.edit_media(
                media=InputMediaPhoto(media=photo_input, caption=text, parse_mode="HTML"),
                reply_markup=kb
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                pass
            else:
                try:
                    await call.message.delete()
                except Exception:
                    pass
                
                # Re-read because BufferedInputFile might have been consumed
                try:
                    with open(config.START_IMAGE, "rb") as f:
                        photo_data = f.read()
                    photo_input_fallback = BufferedInputFile(photo_data, filename="start.jpg")
                except Exception:
                    photo_input_fallback = config.START_IMAGE
                    
                await call.message.answer_photo(photo=photo_input_fallback, caption=text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("start"))
async def cmd_start(msg: Message):
    await register_user(msg.from_user)
    await _send_main_menu(msg, msg.from_user.id, msg.from_user.first_name)


@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery):
    await call.answer()
    await _send_main_menu(call, call.from_user.id, call.from_user.first_name)


@router.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery):
    await call.answer()
    text = (
        "📖 <b>How to use</b>\n\n"
        "<b>1.</b> Browse Numbers → pick a service\n"
        "<b>2.</b> Choose a country\n"
        "<b>3.</b> Confirm & buy\n"
        "<b>4.</b> OTP is delivered automatically\n\n"
        "ℹ️ <b>Telegram orders cannot be cancelled.</b>\n"
        "ℹ️ <b>WhatsApp orders can be refunded via the Cancel button.</b>"
    )
    await _edit(call.message, text, reply_markup=kb_back("menu"), parse_mode="HTML")


@router.callback_query(F.data == "join_check")
async def cb_join_check(call: CallbackQuery):
    joined = await _is_member(call.bot, call.from_user.id)
    if joined:
        await call.answer("✅ Verified!", show_alert=True)
        await _send_main_menu(call, call.from_user.id, call.from_user.first_name)
    else:
        await call.answer("Still not joined!", show_alert=True)
