"""Wallet view and currency toggle (USD / INR)."""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from db import get_wallet, get_currency_pref, set_currency_pref
from keyboards import kb_wallet
from rates import RateFetchError, usd_to_inr

router = Router()


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
    return (
        f"💰 <b>Your Wallet</b>\n\n"
        f"Balance: {symbol}{display:.2f} {code}\n"
        f"Rate: $1 = ₹{rate:.2f}\n\n"
        f"Tap <b>Add Funds</b> to deposit money.",
        currency,
    )


@router.callback_query(F.data == "wallet")
async def cb_wallet(call: CallbackQuery):
    await call.answer()
    try:
        text, currency = await _wallet_text(call.from_user.id)
    except RateFetchError:
        await call.message.edit_text(
            "❌ Could not fetch live rate. Please try again later.")
        return
    await call.message.edit_text(text, reply_markup=kb_wallet(currency),
                                 parse_mode="HTML")


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
        await call.message.edit_text(
            "❌ Could not fetch live rate. Please try again later.")
        return
    await call.message.edit_text(text, reply_markup=kb_wallet(new_currency),
                                 parse_mode="HTML")
