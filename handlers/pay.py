"""Razorpay "Add Funds" flow: choose amount -> UPI QR code -> auto-credit via webhook."""
import html

from aiogram import Router, F
from aiogram.enums import ButtonStyle
from aiogram.types import URLInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext

from core.states import PayState

from core.db import get_wallet, get_currency_pref
from ui.keyboards import kb_back, kb_add_funds_choice
from utils.payments import create_qr_code
from utils.nowpayments import create_invoice
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
async def cb_addfunds(call: CallbackQuery):
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
        
    await _edit(
        call.message,
        f"💰 <b>Add Funds</b>\n"
        f"Wallet balance: {symbol}{display:.2f} {code}\n\n"
        f"Please select your preferred payment method:",
        reply_markup=kb_add_funds_choice(), parse_mode="HTML")


@router.callback_query(F.data.startswith("fund_gateway:"))
async def cb_fund_gateway(call: CallbackQuery, state: FSMContext):
    await call.answer()
    gateway = call.data.split(":")[1]
    await state.update_data(gateway=gateway)
    await state.set_state(PayState.waiting_for_amount)
    
    b = InlineKeyboardBuilder()
    b.button(text="Back", callback_data="addfunds", style=ButtonStyle.DANGER, icon_custom_emoji_id="5352759161945867747")
    b.adjust(1)
    
    if gateway == "upi":
        msg_text = "🇮🇳 <b>UPI Top-up</b>\nPlease type the amount in <b>INR (₹)</b> you want to add (min 1, max 100,000):"
    else:
        msg_text = "🪙 <b>Crypto Top-up</b>\nPlease type the amount in <b>USD ($)</b> you want to add (min 1.0, max 10,000):"
        
    await _edit(call.message, msg_text, reply_markup=b.as_markup(), parse_mode="HTML")


@router.message(PayState.waiting_for_amount)
async def process_amount(msg: Message, state: FSMContext):
    data = await state.get_data()
    gateway = data.get("gateway", "upi")
    text = msg.text.strip()
    
    # Validation
    try:
        amt = float(text)
    except ValueError:
        await msg.answer("❌ Invalid amount. Please type a valid number.", reply_markup=kb_back("addfunds"))
        return
        
    if gateway == "upi":
        if amt < 1 or amt > 100000:
            await msg.answer("❌ UPI Amount must be between ₹1 and ₹100,000.", reply_markup=kb_back("addfunds"))
            return
            
        await state.clear()
        try:
            qr_url, qr_id = create_qr_code(msg.from_user.id, int(amt))
            if not qr_url:
                raise RuntimeError("Razorpay did not return a QR image URL.")
        except Exception as e:
            await msg.answer(f"❌ Payment init failed: {html.escape(str(e))}", reply_markup=kb_back("addfunds"))
            return
            
        status_msg = await msg.answer("⏳ Generating QR code...", reply_markup=None)
        try:
            await status_msg.delete()
        except:
            pass
            
        try:
            await msg.answer_photo(
                URLInputFile(qr_url),
                caption=f"💰 <b>Add ₹{int(amt)}</b>\n\nScan this QR with any UPI app to pay.\nYour wallet will be credited automatically once confirmed.",
                parse_mode="HTML")
        except Exception as e:
            await msg.answer(f"❌ Failed to load QR: {html.escape(str(e))}", reply_markup=kb_back("addfunds"))

    else:
        # Crypto
        if amt < 1.0 or amt > 10000.0:
            await msg.answer("❌ Crypto Amount must be between $1.0 and $10,000.0.", reply_markup=kb_back("addfunds"))
            return
            
        await state.clear()
        status_msg = await msg.answer("⏳ Generating Crypto Invoice...", reply_markup=None)
        
        try:
            inv_url, inv_id = await create_invoice(msg.from_user.id, amt)
            await status_msg.delete()
            
            b = InlineKeyboardBuilder()
            b.button(text="Pay with Crypto 💳", url=inv_url)
            b.button(text="Back", callback_data="addfunds", style=ButtonStyle.DANGER)
            b.adjust(1)
            
            await msg.answer(
                f"🪙 <b>Deposit ${amt:.2f} via Crypto</b>\n\n"
                f"Click the button below to complete your payment on the secure NOWPayments portal. "
                f"Your balance will be updated automatically once the blockchain confirms your transaction.",
                reply_markup=b.as_markup(), parse_mode="HTML"
            )
        except Exception as e:
            await status_msg.edit_text(f"❌ Failed to generate crypto invoice: {html.escape(str(e))}", reply_markup=kb_back("addfunds"))
