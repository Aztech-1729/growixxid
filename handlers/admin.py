"""Admin handlers: live provider balances, stats, broadcast."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from core.config import config
from core.db import (count_orders, count_users, get_all_users, get_setting, set_setting, 
                     get_user, toggle_ban_user, credit_wallet, deduct_wallet, 
                     get_sales_report, get_recent_failed_orders)
from ui.keyboards import kb_admin, kb_back, kb_admin_user, kb_admin_suppliers
from services.suppliers import SUPPLIERS, balance as supplier_balance
from services.vnhotp import VNHOTPError, vnhotp
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from core.states import AdminState

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
        from services.grizzly_api import grizzly
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
    lines.append("Reply to any message with /bd to broadcast it to all users.")
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


@router.message(Command("bd"))
async def cmd_bd(msg: Message):
    if msg.from_user.id not in config.ADMIN_IDS:
        return
    if not msg.reply_to_message:
        await msg.answer("❌ You must reply to a message with /bd to broadcast it.")
        return
    
    users = await get_all_users()
    sent = 0
    status_msg = await msg.answer("⏳ Broadcasting...")
    
    for u in users:
        try:
            await msg.reply_to_message.copy_to(chat_id=u["user_id"])
            sent += 1
        except Exception:
            pass
            
    await status_msg.edit_text(f"✅ Broadcast successfully sent to {sent} users.")


# ===================================================================
# ADMIN PANEL: USER MANAGEMENT
# ===================================================================

@router.callback_query(F.data == "admin_user_lookup")
async def cb_admin_user_lookup(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in config.ADMIN_IDS: return
    await call.answer()
    await _edit(call.message, "👤 <b>User Lookup</b>\n\nSend the Telegram User ID of the user:", reply_markup=kb_back("admin"), parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_user_id)


@router.message(AdminState.waiting_for_user_id)
async def process_user_lookup(msg: Message, state: FSMContext):
    if msg.from_user.id not in config.ADMIN_IDS: return
    try:
        uid = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ Invalid User ID. Please send a number.", reply_markup=kb_back("admin"))
        return
        
    u = await get_user(uid)
    if not u:
        await msg.answer(f"❌ User <code>{uid}</code> not found in database.", reply_markup=kb_back("admin"), parse_mode="HTML")
        return
        
    await state.clear()
    joined = u.get("joined_at")
    joined_str = joined.strftime("%Y-%m-%d") if joined else "Unknown"
    banned = u.get("banned", False)
    wallet = u.get("wallet", 0.0)
    
    text = (
        f"👤 <b>User Profile:</b> {uid}\n"
        f"<b>Name:</b> {u.get('first_name', '')} {u.get('last_name', '')}\n"
        f"<b>Username:</b> @{u.get('username', 'N/A')}\n"
        f"<b>Joined:</b> {joined_str}\n"
        f"<b>Wallet Balance:</b> ₹{wallet:.2f}\n"
        f"<b>Status:</b> {'🚫 BANNED' if banned else '✅ Active'}\n"
    )
    await msg.answer(text, reply_markup=kb_admin_user(uid, banned), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_ban_toggle:"))
async def cb_admin_ban_toggle(call: CallbackQuery):
    if call.from_user.id not in config.ADMIN_IDS: return
    uid = int(call.data.split(":")[1])
    new_status = await toggle_ban_user(uid)
    await call.answer(f"User is now {'BANNED' if new_status else 'UNBANNED'}", show_alert=True)
    
    # refresh profile
    u = await get_user(uid)
    banned = u.get("banned", False)
    wallet = u.get("wallet", 0.0)
    joined = u.get("joined_at")
    joined_str = joined.strftime("%Y-%m-%d") if joined else "Unknown"
    text = (
        f"👤 <b>User Profile:</b> {uid}\n"
        f"<b>Name:</b> {u.get('first_name', '')} {u.get('last_name', '')}\n"
        f"<b>Username:</b> @{u.get('username', 'N/A')}\n"
        f"<b>Joined:</b> {joined_str}\n"
        f"<b>Wallet Balance:</b> ₹{wallet:.2f}\n"
        f"<b>Status:</b> {'🚫 BANNED' if banned else '✅ Active'}\n"
    )
    await _edit(call.message, text, reply_markup=kb_admin_user(uid, banned), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_manage_bal:"))
async def cb_admin_manage_bal(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in config.ADMIN_IDS: return
    await call.answer()
    uid = int(call.data.split(":")[1])
    await state.update_data(target_user=uid)
    await _edit(call.message, "💰 <b>Manage Balance</b>\n\nEnter the amount to add or deduct (e.g., <code>50</code> or <code>-50</code>):", reply_markup=kb_back("admin"), parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_balance_change)


@router.message(AdminState.waiting_for_balance_change)
async def process_balance_change(msg: Message, state: FSMContext):
    if msg.from_user.id not in config.ADMIN_IDS: return
    data = await state.get_data()
    uid = data.get("target_user")
    
    try:
        amt = float(msg.text.strip())
    except ValueError:
        await msg.answer("❌ Invalid amount. Send a number.", reply_markup=kb_back("admin"))
        return
        
    if amt >= 0:
        await credit_wallet(uid, amt, "Admin manual credit")
    else:
        await deduct_wallet(uid, abs(amt), "Admin manual deduct")
        
    await state.clear()
    
    u = await get_user(uid)
    await msg.answer(f"✅ Balance updated! New balance for {uid}: ₹{u.get('wallet', 0.0):.2f}", reply_markup=kb_admin_user(uid, u.get("banned", False)))


# ===================================================================
# ADMIN PANEL: SETTINGS
# ===================================================================

@router.callback_query(F.data == "admin_margin")
async def cb_admin_margin(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in config.ADMIN_IDS: return
    await call.answer()
    current_margin = float(await get_setting("global_margin", 0.0))
    await _edit(call.message, f"⚙️ <b>Global Profit Margin</b>\n\nCurrent margin: <b>{current_margin}%</b>\n\nSend a new percentage (e.g. <code>20</code> for 20% markup, or <code>0</code> for cost price):", reply_markup=kb_back("admin"), parse_mode="HTML")
    await state.set_state(AdminState.waiting_for_margin)


@router.message(AdminState.waiting_for_margin)
async def process_margin(msg: Message, state: FSMContext):
    if msg.from_user.id not in config.ADMIN_IDS: return
    try:
        margin = float(msg.text.strip())
    except ValueError:
        await msg.answer("❌ Invalid percentage. Send a number.", reply_markup=kb_back("admin"))
        return
        
    await set_setting("global_margin", margin)
    await state.clear()
    await msg.answer(f"✅ Global margin updated to <b>{margin}%</b>.", reply_markup=kb_back("admin"), parse_mode="HTML")


@router.callback_query(F.data == "admin_suppliers")
async def cb_admin_suppliers(call: CallbackQuery):
    if call.from_user.id not in config.ADMIN_IDS: return
    await call.answer()
    active = await get_setting("active_suppliers", ["vnhotp", "tigersms", "grizzly"])
    await _edit(call.message, "🔌 <b>Manage Suppliers</b>\n\nToggling a supplier off will hide it from the catalog.", reply_markup=kb_admin_suppliers(active), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_sup_toggle:"))
async def cb_admin_sup_toggle(call: CallbackQuery):
    if call.from_user.id not in config.ADMIN_IDS: return
    sup = call.data.split(":")[1]
    active = await get_setting("active_suppliers", ["vnhotp", "tigersms", "grizzly"])
    
    if sup in active:
        active.remove(sup)
    else:
        active.append(sup)
        
    await set_setting("active_suppliers", active)
    await call.answer(f"Supplier {sup.upper()} toggled.", show_alert=False)
    await _edit(call.message, "🔌 <b>Manage Suppliers</b>\n\nToggling a supplier off will hide it from the catalog.", reply_markup=kb_admin_suppliers(active), parse_mode="HTML")


# ===================================================================
# ADMIN PANEL: ANALYTICS
# ===================================================================

@router.callback_query(F.data == "admin_sales")
async def cb_admin_sales(call: CallbackQuery):
    if call.from_user.id not in config.ADMIN_IDS: return
    await call.answer()
    
    report = await get_sales_report()
    rev = report["revenue"]
    pop = report["popular"]
    
    text = (
        "📊 <b>Sales Report</b>\n\n"
        f"<b>Today:</b> ₹{rev.get('today', 0):.2f}\n"
        f"<b>This Week:</b> ₹{rev.get('week', 0):.2f}\n"
        f"<b>This Month:</b> ₹{rev.get('month', 0):.2f}\n\n"
        "🔥 <b>Top Services:</b>\n"
    )
    for p in pop:
        text += f"- {p['_id'].upper()} ({p['count']} orders)\n"
        
    await _edit(call.message, text, reply_markup=kb_back("admin"), parse_mode="HTML")


@router.callback_query(F.data == "admin_failed")
async def cb_admin_failed(call: CallbackQuery):
    if call.from_user.id not in config.ADMIN_IDS: return
    await call.answer()
    
    recent = await get_recent_failed_orders(limit=10)
    if not recent:
        await _edit(call.message, "❌ No recent failed/refunded orders.", reply_markup=kb_back("admin"), parse_mode="HTML")
        return
        
    text = "❌ <b>Recent Failed Orders (Last 10)</b>\n\n"
    for o in recent:
        text += f"• <code>{o.get('order_ref')}</code> | {o.get('service').upper()} | {o.get('country_name')} | {o.get('status')}\n"
        
    await _edit(call.message, text, reply_markup=kb_back("admin"), parse_mode="HTML")
