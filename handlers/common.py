"""Common handlers: /start, main menu, help, join verification."""
from aiogram import Router, F
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import config
from db import register_user
from keyboards import kb_back, kb_join, kb_main

router = Router()


async def _is_member(bot, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member("@" + config.FORCE_JOIN_CHANNEL, user_id)
        return m.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED)
    except Exception:
        return False


@router.message(Command("start"))
async def cmd_start(msg: Message):
    await register_user(msg.from_user)
    await msg.answer(
        "⚡️ <b>𝙂𝙍𝙊𝙒𝙄𝙓𝙓 !! Acc Store Bot</b>\n\n"
        f"Welcome {msg.from_user.first_name or 'there'}!\n"
        "Buy Telegram & WhatsApp activation numbers instantly.\n\n"
        "Tap <b>Browse Numbers</b> to begin.",
        reply_markup=kb_main(msg.from_user.id in config.ADMIN_IDS),
        parse_mode="HTML")


@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        "🏠 Main Menu:",
        reply_markup=kb_main(call.from_user.id in config.ADMIN_IDS))


@router.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery):
    await call.answer()
    text = (
        "<b>How to use</b>\n"
        "1. Browse Numbers → pick a service\n"
        "2. Choose a country\n"
        "3. Confirm & buy\n"
        "4. OTP is delivered automatically\n\n"
        "ℹ️ Telegram orders cannot be cancelled.\n"
        "ℹ️ WhatsApp orders can be refunded via the Cancel button."
    )
    await call.message.edit_text(text, reply_markup=kb_back("menu"), parse_mode="HTML")


@router.callback_query(F.data == "join_check")
async def cb_join_check(call: CallbackQuery):
    joined = await _is_member(call.bot, call.from_user.id)
    if joined:
        await call.answer("✅ Verified!", show_alert=True)
        await call.message.edit_text(
            "🏠 Main Menu:",
            reply_markup=kb_main(call.from_user.id in config.ADMIN_IDS))
    else:
        await call.answer("Still not joined!", show_alert=True)
