"""Shop flow for alternate suppliers (TigerSMS).

Generic catalog -> offering -> confirm -> place order -> OTP delivery, driven by
``suppliers.py`` so the same handlers work for very different provider APIs.
"""
import asyncio
import html

from aiogram import Router, F
from aiogram.enums import ButtonStyle
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from db import (add_order, get_order, get_wallet, deduct_wallet,
                credit_wallet, update_order)
from keyboards import kb_back
from suppliers import SUPPLIERS, get_offerings, buy, get_code, cancel

router = Router()

# Per-user cache of the current supplier/service offering list (single process).
CACHE: dict = {}
PAGE = 8


def _kb_cancel(sid: str, ref: str):
    b = InlineKeyboardBuilder()
    b.button(text="❌ Cancel & Refund", callback_data=f"altcancel:{sid}:{ref}",
             style=ButtonStyle.DANGER)
    b.adjust(1)
    return b.as_markup()


# ---- supplier menu ----
@router.callback_query(F.data.startswith("alt:"))
async def cb_alt(call: CallbackQuery):
    await call.answer()
    sid = call.data.split(":", 1)[1]
    sup = SUPPLIERS[sid]
    b = InlineKeyboardBuilder()
    for s in sup["services"]:
        b.button(text=s["label"], callback_data=f"altcat:{sid}:{s['key']}",
                 style=ButtonStyle.PRIMARY)
    b.adjust(1)
    b.button(text="🔙 Back", callback_data="catalog", style=ButtonStyle.DANGER)
    await call.message.edit_text(
        f"🛰 <b>{sup['name']}</b> — {sup['subtitle']}\nChoose a service:",
        reply_markup=b.as_markup(), parse_mode="HTML")


# ---- service -> offering list ----
@router.callback_query(F.data.startswith("altcat:"))
async def cb_altcat(call: CallbackQuery):
    await call.answer()
    _, sid, service = call.data.split(":")
    try:
        items = await get_offerings(sid, service)
    except Exception as e:
        await call.message.edit_text(f"❌ {e}", reply_markup=kb_back(f"alt:{sid}"),
                                     parse_mode="HTML")
        return
    if not items:
        await call.message.edit_text("😕 No numbers available right now for this service.",
                                     reply_markup=kb_back(f"alt:{sid}"))
        return
    CACHE.setdefault(call.from_user.id, {})[f"{sid}:{service}"] = items
    await _show_offerings(call, sid, service, items, 0)


@router.callback_query(F.data.startswith("altpg:"))
async def cb_altpg(call: CallbackQuery):
    await call.answer()
    _, sid, service, page = call.data.split(":")
    items = CACHE.get(call.from_user.id, {}).get(f"{sid}:{service}", [])
    await _show_offerings(call, sid, service, items, int(page))


async def _show_offerings(call, sid, service, items, page):
    b = InlineKeyboardBuilder()
    start = page * PAGE
    for o in items[start:start + PAGE]:
        inr = o.price_usd * config.USD_INR_RATE
        label = f"{o.label} — ₹{inr:.2f}"
        if o.stock is not None:
            label += f" ({o.stock} left)"
        # buyable stock option -> SUCCESS
        b.button(text=label, callback_data=f"altbuy:{sid}:{service}:{o.id}",
                 style=ButtonStyle.SUCCESS)
    b.adjust(1)
    if page > 0:
        b.button(text="◀️ Prev", callback_data=f"altpg:{sid}:{service}:{page - 1}",
                 style=ButtonStyle.DANGER)
    if start + PAGE < len(items):
        b.button(text="Next ▶️", callback_data=f"altpg:{sid}:{service}:{page + 1}",
                 style=ButtonStyle.DANGER)
    b.button(text="🔙 Back", callback_data=f"alt:{sid}", style=ButtonStyle.DANGER)
    b.adjust(1)
    await call.message.edit_text(
        f"🌍 <b>{SUPPLIERS[sid]['name']}</b> — {service.upper()}\nChoose an option:",
        reply_markup=b.as_markup(), parse_mode="HTML")


# ---- confirm ----
@router.callback_query(F.data.startswith("altbuy:"))
async def cb_altbuy(call: CallbackQuery):
    await call.answer()
    _, sid, service, item_id = call.data.split(":", 3)
    o = await _resolve_offering(call.from_user.id, sid, service, item_id)
    if not o:
        await call.message.edit_text("❌ Session expired. Please start again.",
                                     reply_markup=kb_back("catalog"))
        return
    inr = o.price_usd * config.USD_INR_RATE
    b = InlineKeyboardBuilder()
    b.button(text=f"✅ Buy (₹{inr:.2f})",
             callback_data=f"altconfirm:{sid}:{service}:{item_id}",
             style=ButtonStyle.SUCCESS)
    b.button(text="🔙 Cancel", callback_data=f"alt:{sid}", style=ButtonStyle.DANGER)
    b.adjust(1)
    await call.message.edit_text(
        f"🧾 <b>Confirm Order</b>\n\n"
        f"Supplier: <b>{SUPPLIERS[sid]['name']}</b>\n"
        f"Service: {service.upper()}\nOption: {o.label}\nPrice: ₹{inr:.2f}",
        reply_markup=b.as_markup(), parse_mode="HTML")


# ---- place order ----
@router.callback_query(F.data.startswith("altconfirm:"))
async def cb_altconfirm(call: CallbackQuery):
    await call.answer()
    _, sid, service, item_id = call.data.split(":", 3)
    o = await _resolve_offering(call.from_user.id, sid, service, item_id)
    if not o:
        await call.message.edit_text("❌ Session expired. Please start again.",
                                     reply_markup=kb_back("catalog"))
        return
    inr = o.price_usd * config.USD_INR_RATE
    wallet = await get_wallet(call.from_user.id)
    if wallet < inr:
        b = InlineKeyboardBuilder()
        b.button(text="💰 Add Funds", callback_data="addfunds",
                 style=ButtonStyle.SUCCESS)
        b.button(text="🔙 Back", callback_data="catalog", style=ButtonStyle.DANGER)
        b.adjust(1)
        await call.message.edit_text(
            f"💡 Price: ₹{inr:.2f}\nYour wallet: ₹{wallet:.2f}\n\n"
            f"Please add funds to continue.",
            reply_markup=b.as_markup(), parse_mode="HTML")
        return

    try:
        res = await buy(sid, service, item_id)
    except Exception as e:
        await call.message.edit_text(
            f"❌ Order failed: {html.escape(str(e))}",
            reply_markup=kb_back("catalog"))
        return

    ref = res["ref"]
    number = res["number"]
    cost_usd = res["cost_usd"]
    await deduct_wallet(call.from_user.id, inr, f"alt {sid} {service} {item_id}")
    await add_order(
        user_id=call.from_user.id, service=f"{sid}:{service}",
        country_code=item_id, country_name=o.label, number=number,
        price=cost_usd, price_inr=inr, order_ref=ref,
        supplier=sid, status="pending")

    svc = next(s for s in SUPPLIERS[sid]["services"] if s["key"] == service)
    kb = _kb_cancel(sid, ref) if svc["cancellable"] else kb_back("menu")
    await call.message.edit_text(
        f"⏳ Order placed! Waiting for OTP…\n\n"
        f"Supplier: <b>{SUPPLIERS[sid]['name']}</b>\n"
        f"Service: {service.upper()}\nNumber: <code>{number}</code>\n"
        f"Charged: ₹{inr:.2f}",
        reply_markup=kb, parse_mode="HTML")

    asyncio.create_task(_safe_poll_alt(
        call.bot, call.from_user.id, call.message.chat.id,
        call.message.message_id, sid, service, ref, number))


# ---- cancel + refund ----
@router.callback_query(F.data.startswith("altcancel:"))
async def cb_altcancel(call: CallbackQuery):
    await call.answer()
    _, sid, ref = call.data.split(":", 2)
    try:
        ok = await cancel(sid, ref)
    except Exception as e:
        await call.message.edit_text(f"❌ {e}", reply_markup=kb_back("menu"))
        return
    if ok:
        o = await get_order(ref)
        if o and float(o.get("price_inr", 0)):
            await credit_wallet(o["user_id"], float(o["price_inr"]), "alt refund")
            await update_order(ref, status="cancelled", refunded=True)
        else:
            await update_order(ref, status="cancelled")
        await call.message.edit_text(
            "✅ Order cancelled & refunded.", reply_markup=kb_back("menu"))
    else:
        await call.message.edit_text(
            "❌ Could not cancel this order.", reply_markup=kb_back("menu"))


# ---- OTP poller ----
async def _safe_poll_alt(bot, user_id, chat_id, message_id, sid, service, ref, number):
    try:
        await poll_alt(bot, user_id, chat_id, message_id, sid, service, ref, number)
    except Exception as e:
        import logging
        logging.exception("Alt OTP poller failed for %s", ref)


async def poll_alt(bot, user_id, chat_id, message_id, sid, service, ref, number):
    interval = config.OTP_POLL_INTERVAL
    tries = max(1, int(config.OTP_TIMEOUT / interval))
    for _ in range(tries):
        try:
            code = await get_code(sid, ref, service)
        except Exception:
            code = None
        if code:
            await update_order(ref, status="completed", otp=code)
            await bot.edit_message_text(
                f"✅ <b>OTP Received!</b>\n\n"
                f"Supplier: {SUPPLIERS[sid]['name']}\n"
                f"Number: <code>{number}</code>\nOTP: <b>{code}</b>",
                chat_id=chat_id, message_id=message_id,
                parse_mode="HTML", reply_markup=kb_back("menu"))
            return
        await asyncio.sleep(interval)
    await update_order(ref, status="expired")
    # Try to cancel on the supplier and refund the wallet
    try:
        ok = await cancel(sid, ref)
        if ok:
            o = await get_order(ref)
            if o and float(o.get("price_inr", 0)):
                await credit_wallet(o["user_id"], float(o["price_inr"]),
                                    f"Refund for expired {sid} order")
                await update_order(ref, status="cancelled", refunded=True)
    except Exception:
        pass
    try:
        await bot.edit_message_text(
            "⌛ OTP not received within the time limit. Order expired.",
            chat_id=chat_id, message_id=message_id, reply_markup=kb_back("menu"))
    except Exception:
        pass


async def _resolve_offering(user_id, sid, service, item_id):
    items = CACHE.get(user_id, {}).get(f"{sid}:{service}", [])
    o = next((x for x in items if str(x.id) == item_id), None)
    if not o:
        try:
            items = await get_offerings(sid, service)
            CACHE.setdefault(user_id, {})[f"{sid}:{service}"] = items
            o = next((x for x in items if str(x.id) == item_id), None)
        except Exception:
            o = None
    return o
