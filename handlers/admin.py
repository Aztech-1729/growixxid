"""Admin handlers: live provider balances, stats, broadcast."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from core.config import config
from core.db import count_orders, count_users
from ui.keyboards import kb_admin, kb_back
from services.suppliers import SUPPLIERS, balance as supplier_balance
from services.vnhotp import VNHOTPError, vnhotp
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


def _fmt(amount) -> str:
    try:
        return f"{config.CURRENCY}{float(amount) * config.USD_INR_RATE:.2f}"
    except (TypeError, ValueError):
        return f"error: {amount}"


async def _panel() -> str:
    lines = ["👑 <b>Admin Panel</b>\n"]

    # VNHOTP (primary)
    try:
        bal = await vnhotp.check()
        vbal = bal.get("user", {}).get("balance")
        lines.append(f"VNHOTP balance: {_fmt(vbal)}")
        discount = bal.get('api', {}).get('discount')
        lines.append(f"  discount: {discount or 'none'}")
    except VNHOTPError as e:
        lines.append(f"VNHOTP balance: error ({e})")

    # Alternate suppliers
    for sid, sup in SUPPLIERS.items():
        try:
            lines.append(f"{sup['name']} balance: {_fmt(await supplier_balance(sid))}")
        except Exception as e:
            lines.append(f"{sup['name']} balance: error ({e})")
            
    # Grizzly SMS
    try:
        from grizzly_api import grizzly
        g_bal = await grizzly.balance()
        lines.append(f"Grizzly balance: ₽ {g_bal:.2f}")
    except Exception as e:
        lines.append(f"Grizzly balance: error ({e})")

    users = await count_users()
    orders = await count_orders()
    lines.append("")
    lines.append(f"Users: {users}")
    lines.append(f"Orders: {orders}")
    lines.append("")
    lines.append("Use /broadcast &lt;text&gt; to message all users.")
    return "\n".join(lines)


@router.message(Command("admin"))
async def cmd_admin(msg: Message):
    if msg.from_user.id not in config.ADMIN_IDS:
        return
    await msg.answer(await _panel(), reply_markup=kb_admin(), parse_mode="HTML")


@router.callback_query(F.data == "admin")
async def cb_admin(call: CallbackQuery):
    if call.from_user.id not in config.ADMIN_IDS:
        await call.answer("⛔ Not authorized", show_alert=True)
        return
    await call.answer()
    await _edit(call.message, await _panel(), reply_markup=kb_admin(), parse_mode="HTML")


@router.message(Command("broadcast"))
async def cmd_broadcast(msg: Message):
    if msg.from_user.id not in config.ADMIN_IDS:
        return
    parts = msg.text.split(" ", 1)
    if len(parts) < 2:
        await msg.answer("Usage: /broadcast <message>")
        return
    text = parts[1]
    from db import get_all_users
    users = await get_all_users()
    sent = 0
    for u in users:
        try:
            await msg.bot.send_message(u["user_id"], f"📢 {text}")
            sent += 1
        except Exception:
            pass
    await msg.answer(f"✅ Broadcast sent to {sent} users.")
