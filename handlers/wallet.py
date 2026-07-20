"""Wallet view and currency toggle (USD / INR)."""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from core.db import get_wallet, get_currency_pref, set_currency_pref
from ui.keyboards import kb_wallet
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


async def _wallet_text(user_id: int) -> tuple:
    balance = await get_wallet(user_id)
    currency = await get_currency_pref(user_id)
    rate = await usd_to_inr()
    if currency == "USD":
        display = balance / rate
        symbol, code = "$", "USD"
    else:
        display = balance
        symbol, code = "₹", "INR"
    text = (
        f"💰 <b>Your Wallet</b>\n\n"
        f"<b>Balance:</b> {symbol}{display:.2f} {code}\n"
        f"<b>Rate:</b> $1 = ₹{rate:.2f}\n\n"
        f"Tap <b>Add Funds</b> to deposit money."
    )
    return (text, currency)


from aiogram.fsm.context import FSMContext

@router.callback_query(F.data == "wallet")
async def cb_wallet(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    try:
        text, currency = await _wallet_text(call.from_user.id)
    except RateFetchError:
        await _edit(call.message, "❌ Could not fetch live rate. Please try again later.")
        return
    await _edit(call.message, text, reply_markup=kb_wallet(currency), parse_mode="HTML")


@router.callback_query(F.data == "toggle_currency")
async def cb_toggle_currency(call: CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    current = await get_currency_pref(user_id)
    new_currency = "USD" if current == "INR" else "INR"
    await set_currency_pref(user_id, new_currency)
    try:
        text, _ = await _wallet_text(user_id)
    except RateFetchError:
        await _edit(call.message, "❌ Could not fetch live rate. Please try again later.")
        return
    await _edit(call.message, text, reply_markup=kb_wallet(new_currency), parse_mode="HTML")
