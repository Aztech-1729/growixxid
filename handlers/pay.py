"""Razorpay "Add Funds" flow: choose amount -> UPI QR code -> auto-credit via webhook."""
import httpx
from aiogram import Router, F
from aiogram.enums import ButtonStyle
from aiogram.types import BufferedInputFile, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from db import get_wallet
from keyboards import kb_back
from payments import create_qr_code

router = Router()

_PRESETS = (1, 10, 50, 100, 500)


@router.callback_query(F.data == "addfunds")
async def cb_addfunds(call: CallbackQuery):
    await call.answer()
    bal = await get_wallet(call.from_user.id)
    b = InlineKeyboardBuilder()
    for amt in _PRESETS:
        b.button(text=f"₹{amt}", callback_data=f"pay:{amt}")
    b.adjust(2)
    b.button(text="🔙 Back", callback_data="menu", style=ButtonStyle.DANGER)
    b.adjust(1)
    await call.message.edit_text(
        f"💰 <b>Add Funds</b>\nWallet balance: ₹{bal:.2f}\n\nChoose an amount:",
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
    except Exception as e:
        await call.message.edit_text(
            f"❌ Payment init failed:\n<code>{e}</code>",
            reply_markup=kb_back("menu"), parse_mode="HTML")
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
            f"❌ Failed to load QR:\n<code>{e}</code>",
            reply_markup=kb_back("menu"), parse_mode="HTML")
