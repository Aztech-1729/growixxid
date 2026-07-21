from aiogram import Router, F
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, InputMediaPhoto, BufferedInputFile
from aiogram.exceptions import TelegramBadRequest

from core.config import config
from core.db import register_user
from ui.keyboards import kb_back, kb_main, kb_support

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
    text = _get_main_menu_text(first_name)
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

def _get_main_menu_text(first_name: str) -> str:
    return (
        "HI 🫲<tg-emoji emoji-id='5456258317477230911'>😎</tg-emoji>🫱 —_ 𝙂𝙍𝙊𝙒𝙄𝙓𝙓 !!\n"
        "WELCOME TO <tg-emoji emoji-id='5895242866057286055'>🔘</tg-emoji>\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "𝐆𝐑𝐎𝐖𝐈𝐗𝐗 𝐎𝐓𝐏 𝐁𝐎𝐓 <tg-emoji emoji-id='5314391089514291948'>🤖</tg-emoji>\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "<tg-emoji emoji-id='5222444124698853913'>🔖</tg-emoji> QUICK GUIDE :\n"
        "<tg-emoji emoji-id='5346105514575025401'>▶️</tg-emoji> 𝚃𝙰𝙿 '𝚜𝚎𝚛𝚟𝚒𝚌𝚎𝚜' 𝙱𝚄𝚃𝚃𝙾𝙽.\n"
        "<tg-emoji emoji-id='5346105514575025401'>▶️</tg-emoji> 𝚃𝙰𝙿 '𝚙𝚕𝚊𝚝𝚏𝚘𝚛𝚖' 𝚃𝙾 𝙱𝚁𝙾𝚆𝚂𝙴 𝙿𝚁𝙾𝙳𝚄𝙲𝚃𝚂.\n"
        "<tg-emoji emoji-id='5346105514575025401'>▶️</tg-emoji> 𝙲𝙷𝙾𝙾𝚂𝙴 𝚃𝙷𝙴 '𝚌𝚘𝚞𝚗𝚝𝚛𝚢' 𝚈𝙾𝚄 𝚆𝙰𝙽𝚃.\n"
        "<tg-emoji emoji-id='5346105514575025401'>▶️</tg-emoji> 𝙲𝙾𝙼𝙿𝙻𝙴𝚃𝙴 𝚃𝙷𝙴 '𝚙𝚊𝚢𝚖𝚎𝚗𝚝'\n"
        "<tg-emoji emoji-id='5346105514575025401'>▶️</tg-emoji> 𝚈𝙾𝚄𝚁 '𝚜𝚎𝚛𝚟𝚒𝚌𝚎𝚜' 𝚆𝙸𝙻𝙻 𝙱𝙴 𝙳𝙴𝙻𝙸𝚅𝙴𝚁𝙴𝙳 𝙸𝙽𝚂𝚃𝙰𝙽𝚃𝙻𝚈.\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "PLEASE CHOOSE A MENU BELOW\n"
        "<tg-emoji emoji-id='5406745015365943482'>⬇️</tg-emoji><tg-emoji emoji-id='5406745015365943482'>⬇️</tg-emoji><tg-emoji emoji-id='5406745015365943482'>⬇️</tg-emoji>"
    )

async def send_start_to_user_id(bot, user_id: int, first_name: str):
    text = _get_main_menu_text(first_name)
    kb = kb_main(user_id in config.ADMIN_IDS)
    try:
        with open(config.START_IMAGE, "rb") as f:
            photo_data = f.read()
        photo_input = BufferedInputFile(photo_data, filename="start.jpg")
    except Exception:
        photo_input = config.START_IMAGE
    try:
        await bot.send_photo(chat_id=user_id, photo=photo_input, caption=text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


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
        "<tg-emoji emoji-id='5222444124698853913'>🔖</tg-emoji> 𝐇𝐎𝐖 𝐓𝐎 𝐔𝐒𝐄\n\n"
        "1. Browse Numbers → pick a service\n"
        "2. Choose a country\n"
        "3. Confirm & buy\n"
        "4. OTP is delivered automatically\n\n"
        "<tg-emoji emoji-id='5440660757194744323'>‼️</tg-emoji> Telegram orders cannot be cancelled. \n\n"
        "<tg-emoji emoji-id='5440660757194744323'>‼️</tg-emoji> WhatsApp orders can be refunded via the Cancel button."
    )
    await _edit(call.message, text, reply_markup=kb_back("menu"), parse_mode="HTML")


@router.callback_query(F.data == "support")
async def cb_support(call: CallbackQuery):
    await call.answer()
    text = (
        "CUSTOMER SUPPORT <tg-emoji emoji-id='5870692618244984670'>📞</tg-emoji>\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "NEED HELP WITH YOUR DIGITAL PRODUCTS OR PAYMENT ? OUR ELITE SUPPORT TEAM IS READY TO ASSIST YOU 24/7 <tg-emoji emoji-id='5208573502046610594'>🕛</tg-emoji>\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "Admin Contact:\n"
        "@ur_Growixx222 <tg-emoji emoji-id='5352825278672412291'>✅</tg-emoji>\n\n"
        "PLEASE KEEP YOUR ORDER ID READY FOR FASTER RESOLUTION. <tg-emoji emoji-id='5188481279963715781'>🚀</tg-emoji><tg-emoji emoji-id='5188481279963715781'>🚀</tg-emoji>\n"
        "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
        "CLICK THE BUTTON BELOW TO START THE CHAT <tg-emoji emoji-id='5406745015365943482'>⬇️</tg-emoji><tg-emoji emoji-id='5406745015365943482'>⬇️</tg-emoji><tg-emoji emoji-id='5406745015365943482'>⬇️</tg-emoji>"
    )
    await _edit(call.message, text, reply_markup=kb_support(), parse_mode="HTML")


@router.callback_query(F.data == "join_check")
async def cb_join_check(call: CallbackQuery):
    joined = await _is_member(call.bot, call.from_user.id)
    if joined:
        await call.answer("✅ Verified!", show_alert=True)
        await _send_main_menu(call, call.from_user.id, call.from_user.first_name)
    else:
        await call.answer("Still not joined!", show_alert=True)
