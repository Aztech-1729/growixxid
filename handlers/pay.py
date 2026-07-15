"""Razorpay "Add Funds" flow: choose amount -> UPI QR code -> auto-credit via webhook."""
import html

import httpx
from aiogram import Router, F
from aiogram.enums import ButtonStyle
from aiogram.types import BufferedInputFile, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from db import get_wallet, get_currency_pref
from keyboards import kb_back
from payments import create_qr_code
from rates import RateFetchError, usd_to_inr

router = Router()

_PRESETS = (1, 10, 50, 100, 500)


@router.callback_query(F.data == "addfunds")
async def cb_addfunds(call: CallbackQuery):
    await call.answer()
    bal = await get_wallet(call.from_user.id)
    currency = await get_currency_pref(call.from_user.id)
    try:
        rate = await usd_to_inr()
    except RateFetchError:
        await call.message.edit_text(
            "❌ Could not fetch live rate. Please try again later.")
        return
    if currency == "USD":
        display = bal / rate
        symbol, code = "$", "USD"
    else:
        display = bal
        symbol, code = "₹", "INR"
    b = InlineKeyboardBuilder()
    for amt in _PRESETS:
        b.button(text=f"₹{amt}", callback_data=f"pay:{amt}")
    b.adjust(2)
    b.button(text="🔙 Back", callback_data="wallet", style=ButtonStyle.DANGER)
    b.adjust(1)
    await call.message.edit_text(
        f"💰 <b>Add Funds</b>\n"
        f"Wallet balance: {symbol}{display:.2f} {code}\n\n"
        f"Choose an amount:",
        reply_markup=b.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(call: CallbackQuery):
    await call.answer()
    amt = int(call.data.split(":")[1])
    if amt < 1:
        await call.message.edit_text(
            "❌ Minimum deposit is ₹1.", reply_markup=kb_back("menu"))
        return
    try:
        qr_url, qr_id = create_qr_code(call.from_user.id, amt)
        if not qr_url:
            raise RuntimeError("Razorpay did not return a QR image URL.")
    except Exception as e:
        await call.message.edit_text(
            f"❌ Payment init failed: {html.escape(str(e))}",
            reply_markup=kb_back("menu"))
        return
    await call.message.edit_text("⏳ Generating QR code...", reply_markup=None)
    try:
        async with httpx.AsyncClient() as hc:
            r = await hc.get(qr_url)
            photo = BufferedInputFile(r.content, filename="qr.png")
        await call.message.answer_photo(
            photo,
            caption=f"💰 <b>Add ₹{amt}</b>\n\n"
                    f"Scan this QR with any UPI app to pay.\n"
                    f"Your wallet will be credited automatically once confirmed.",
            parse_mode="HTML")
    except Exception as e:
        await call.message.edit_text(
            f"❌ Failed to load QR: {html.escape(str(e))}",
            reply_markup=kb_back("menu"))
