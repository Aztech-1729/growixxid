"""Razorpay "Add Funds" flow: choose amount -> UPI QR code -> auto-credit via webhook."""
import html

from aiogram import Router, F
from aiogram.enums import ButtonStyle
from aiogram.types import URLInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext

from core.states import PayState

from core.db import get_wallet, get_currency_pref
from ui.keyboards import kb_back
from utils.payments import create_qr_code
from utils.rates import RateFetchError, usd_to_inr
from aiogram.exceptions import TelegramBadRequest

router = Router()

async def _edit(msg, text, reply_markup=None, parse_mode=None):
    try:
        await msg.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest:
        try:
            await msg.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TelegramBadRequest:
            pass

_PRESETS = (1, 10, 50, 100, 500)


@router.callback_query(F.data == "addfunds")
async def cb_addfunds(call: CallbackQuery, state: FSMContext):
    await call.answer()
    bal = await get_wallet(call.from_user.id)
    currency = await get_currency_pref(call.from_user.id)
    try:
        rate = await usd_to_inr()
    except RateFetchError:
        await _edit(call.message, "❌ Could not fetch live rate. Please try again later.")
        return
    if currency == "USD":
        display = bal / rate
        symbol, code = "$", "USD"
    else:
        display = bal
        symbol, code = "₹", "INR"
        
    await state.set_state(PayState.waiting_for_amount)
    
    b = InlineKeyboardBuilder()
    b.button(text="Back", callback_data="wallet", style=ButtonStyle.DANGER, icon_custom_emoji_id="5352759161945867747")
    b.adjust(1)
    
    await _edit(
        call.message,
        f"💰 <b>Add Funds</b>\n"
        f"Wallet balance: {symbol}{display:.2f} {code}\n\n"
        f"Please type the amount in INR (₹) you want to add (min 1, max 100,000):",
        reply_markup=b.as_markup(), parse_mode="HTML")


@router.message(PayState.waiting_for_amount)
async def process_amount(msg: Message, state: FSMContext):
    text = msg.text.strip()
    if not text.isdigit():
        await msg.answer("❌ Invalid amount. Please type a number (e.g. 50).", reply_markup=kb_back("wallet"))
        return
        
    amt = int(text)
    if amt < 1 or amt > 100000:
        await msg.answer("❌ Amount must be between ₹1 and ₹100,000.", reply_markup=kb_back("wallet"))
        return
        
    await state.clear()
    try:
        qr_url, qr_id = create_qr_code(msg.from_user.id, amt)
        if not qr_url:
            raise RuntimeError("Razorpay did not return a QR image URL.")
    except Exception as e:
        await msg.answer(
            f"❌ Payment init failed: {html.escape(str(e))}",
            reply_markup=kb_back("wallet"))
        return
        
    status_msg = await msg.answer("⏳ Generating QR code...", reply_markup=None)
    try:
        await status_msg.delete()
    except:
        pass
        
    try:
        await msg.answer_photo(
            URLInputFile(qr_url),
            caption=f"💰 <b>Add ₹{amt}</b>\n\n"
                    f"Scan this QR with any UPI app to pay.\n"
                    f"Your wallet will be credited automatically once confirmed.",
            parse_mode="HTML")
    except Exception as e:
        await msg.answer(
            f"❌ Failed to load QR: {html.escape(str(e))}",
            reply_markup=kb_back("wallet"))
