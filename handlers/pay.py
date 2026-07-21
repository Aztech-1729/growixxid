"""Razorpay "Add Funds" flow: choose amount -> UPI QR code -> auto-credit via webhook."""
import html

from aiogram import Router, F
from aiogram.enums import ButtonStyle
from aiogram.types import URLInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext

from core.states import PayState

from core.db import get_wallet, get_currency_pref
from ui.keyboards import kb_back, kb_add_funds_choice, kb_crypto_coins
from utils.payments import create_qr_code
from utils.nowpayments import create_payment, get_min_amount
from utils.rates import RateFetchError, usd_to_inr
from aiogram.exceptions import TelegramBadRequest
from api.web import PENDING_PAYMENT_MESSAGES

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
            b = InlineKeyboardBuilder()
            b.button(text="Cancel", callback_data="menu", style=ButtonStyle.DANGER)
            b.adjust(1)
            
            sent_msg = await msg.answer_photo(
                URLInputFile(qr_url),
                caption=f"💰 <b>Add ₹{int(amt)}</b>\n\nScan this QR with any UPI app to pay.\nYour wallet will be credited automatically once confirmed.",
                reply_markup=b.as_markup(),
                parse_mode="HTML")
            PENDING_PAYMENT_MESSAGES[msg.from_user.id] = sent_msg.message_id
        except Exception as e:
            await msg.answer(f"❌ Failed to load QR: {html.escape(str(e))}", reply_markup=kb_back("addfunds"))

    else:
        # Crypto - Step 1: Validate amount
        if amt < 1.0 or amt > 10000.0:
            await msg.answer("❌ Crypto Amount must be between $1.0 and $10,000.0.", reply_markup=kb_back("addfunds"))
            return
            
        await state.update_data(crypto_amount=amt)
        await state.set_state(PayState.waiting_for_crypto_coin)
        
        await msg.answer(
            f"🪙 <b>Deposit ${amt:.2f}</b>\n\n"
            f"Please select the cryptocurrency you want to pay with:",
            reply_markup=kb_crypto_coins(), parse_mode="HTML"
        )


@router.callback_query(PayState.waiting_for_crypto_coin, F.data.startswith("crypto_coin:"))
async def cb_crypto_coin(call: CallbackQuery, state: FSMContext):
    await call.answer()
    coin = call.data.split(":")[1]
    
    data = await state.get_data()
    amount_usd = data.get("crypto_amount", 0.0)
    if not amount_usd:
        await _edit(call.message, "❌ Session expired.", reply_markup=kb_back("addfunds"))
        return
        
    await state.clear()
    status_msg = await call.message.answer("⏳ Generating Crypto Payment Address...", reply_markup=None)
    
    try:
        min_fiat = await get_min_amount(coin)
        if amount_usd < min_fiat:
            await status_msg.edit_text(
                f"❌ The minimum deposit for <b>{coin.upper()}</b> is <b>${min_fiat:.2f}</b> due to network fees.\n"
                f"You entered ${amount_usd:.2f}. Please try again with a higher amount or choose a different coin (like LTC or TRX).",
                reply_markup=kb_back("addfunds"), parse_mode="HTML"
            )
            return
            
        pay_address, pay_amount, pay_id = await create_payment(call.from_user.id, amount_usd, coin)
        await status_msg.delete()
        
        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={pay_address}"
        
        b = InlineKeyboardBuilder()
        b.button(text="I have paid ✅", callback_data="wallet", style=ButtonStyle.SUCCESS)
        b.button(text="Cancel", callback_data="menu", style=ButtonStyle.DANGER)
        b.adjust(1)
        
        try:
            sent_msg = await call.message.answer_photo(
                URLInputFile(qr_url),
                caption=f"🪙 <b>Crypto Payment ({coin.upper()})</b>\n\n"
                        f"Please send EXACTLY:\n"
                        f"<code>{pay_amount}</code> <b>{coin.upper()}</b>\n\n"
                        f"To Address:\n<code>{pay_address}</code>\n\n"
                        f"<i>(Tap the amount and address to copy them)</i>\n\n"
                        f"⏳ <b>Waiting for payment...</b>\nYour wallet will be credited automatically once the network confirms your transaction.",
                reply_markup=b.as_markup(), parse_mode="HTML"
            )
            PENDING_PAYMENT_MESSAGES[call.from_user.id] = sent_msg.message_id
        except TelegramBadRequest:
            sent_msg = await call.message.answer(
                f"🪙 <b>Crypto Payment ({coin.upper()})</b>\n\n"
                f"Please send EXACTLY:\n"
                f"<code>{pay_amount}</code> <b>{coin.upper()}</b>\n\n"
                f"To Address:\n<code>{pay_address}</code>\n\n"
                f"<i>(Tap the amount and address to copy them)</i>\n\n"
                f"⏳ <b>Waiting for payment...</b>\nYour wallet will be credited automatically once the network confirms your transaction.",
                reply_markup=b.as_markup(), parse_mode="HTML"
            )
            PENDING_PAYMENT_MESSAGES[call.from_user.id] = sent_msg.message_id
            
    except Exception as e:
        await status_msg.edit_text(f"❌ Failed to generate crypto payment: {html.escape(str(e))}", reply_markup=kb_back("addfunds"))
