"""Shop flow for alternate suppliers (TigerSMS).

Generic catalog -> offering -> confirm -> place order -> OTP delivery, driven by
``suppliers.py`` so the same handlers work for very different provider APIs.
"""
import asyncio
import html

from aiogram import Router, F
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import config
from core.db import (add_order, get_order, get_wallet, deduct_wallet,
                credit_wallet, update_order, get_currency_pref)
from ui.keyboards import kb_back
from utils.rates import usd_to_inr
from services.suppliers import SUPPLIERS, get_offerings, buy, get_code, cancel
from utils.session_maker import AutoSessionManager, SessionMakerError
from aiogram.types import FSInputFile

router = Router()

CACHE: dict = {}
PAGE = 8


async def _edit(msg, text, reply_markup=None, parse_mode=None):
    try:
        await msg.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest:
        try:
            await msg.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TelegramBadRequest:
            pass


async def _edit_msg(bot, chat_id, message_id, text, reply_markup=None, parse_mode=None):
    try:
        await bot.edit_message_text(
            text, chat_id=chat_id, message_id=message_id,
            reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest:
        try:
            await bot.edit_message_caption(
                chat_id=chat_id, message_id=message_id,
                caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TelegramBadRequest:
            pass


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
                 style=ButtonStyle.SUCCESS)
                 
    sizes = [2] * (len(sup["services"]) // 2)
    if len(sup["services"]) % 2 != 0:
        sizes.append(1)
        
    b.button(text="Back", callback_data="catalog", style=ButtonStyle.DANGER, icon_custom_emoji_id="5352759161945867747")
    sizes.append(1)
    
    b.adjust(*sizes)
    await _edit(call.message,
                "🌐 <b>Other Services</b>\n<b>Choose a service:</b>",
                reply_markup=b.as_markup(), parse_mode="HTML")


# ---- service -> offering list ----
@router.callback_query(F.data.startswith("altcat:"))
async def cb_altcat(call: CallbackQuery):
    await call.answer()
    _, sid, service = call.data.split(":")
    try:
        items = await get_offerings(sid, service)
    except Exception as e:
        await _edit(call.message, f"❌ {e}", reply_markup=kb_back(f"alt:{sid}"),
                    parse_mode="HTML")
        return
    if not items:
        await _edit(call.message, "😕 No numbers available right now for this service.",
                    reply_markup=kb_back(f"alt:{sid}"))
        return
    CACHE.setdefault(call.from_user.id, {})[f"{sid}:{service}"] = items
    currency = await get_currency_pref(call.from_user.id)
    rate = await usd_to_inr()
    await _edit(call.message,
        f"🌍 <b>Other Services</b> — <b>{service.upper()}</b>\n<b>Choose an option:</b>",
        reply_markup=_offering_kb(sid, service, items, 0, currency, rate), parse_mode="HTML")


def _offering_kb(sid, service, items, page, currency="INR", rate=83.0):
    b = InlineKeyboardBuilder()
    start = page * PAGE
    chunk = items[start:start + PAGE]
    for o in chunk:
        if currency == "USD":
            label = f"{o.label} — ${o.price_usd:.2f}"
        else:
            inr = o.price_usd * rate
            label = f"{o.label} — ₹{inr:.2f}"
            
        if o.stock is not None:
            label += f" ({o.stock} left)"
        b.button(text=label, callback_data=f"altbuy:{sid}:{service}:{o.id}",
                 style=ButtonStyle.SUCCESS)
                 
    sizes = [1] * len(chunk)
    
    nav_count = 0
    if page > 0:
        b.button(text="Prev", callback_data=f"altpg:{sid}:{service}:{page - 1}", style=ButtonStyle.PRIMARY, icon_custom_emoji_id="5438531879345076160")
        nav_count += 1
    if start + PAGE < len(items):
        b.button(text="Next", callback_data=f"altpg:{sid}:{service}:{page + 1}", style=ButtonStyle.PRIMARY, icon_custom_emoji_id="5435955998479102657")
        nav_count += 1
        
    if nav_count:
        sizes.append(nav_count)
        
    b.button(text="Search", callback_data=f"search:alt:{sid}:{service}", style=ButtonStyle.PRIMARY, icon_custom_emoji_id="5429571366384842791")
    sizes.append(1)
        
    b.button(text="Back", callback_data=f"alt:{sid}", style=ButtonStyle.DANGER, icon_custom_emoji_id="5352759161945867747")
    sizes.append(1)
    
    b.adjust(*sizes)
    return b.as_markup()


@router.callback_query(F.data.startswith("altpg:"))
async def cb_altpg(call: CallbackQuery):
    await call.answer()
    _, sid, service, page = call.data.split(":")
    currency = await get_currency_pref(call.from_user.id)
    rate = await usd_to_inr()
    items = CACHE.get(call.from_user.id, {}).get(f"{sid}:{service}", [])
    await _edit(call.message,
                f"🌍 <b>Other Services</b> — <b>{service.upper()}</b>\n<b>Choose an option:</b>",
                reply_markup=_offering_kb(sid, service, items, int(page), currency, rate),
                parse_mode="HTML")


# ---- confirm ----
@router.callback_query(F.data.startswith("altbuy:"))
async def cb_altbuy(call: CallbackQuery):
    await call.answer()
    _, sid, service, item_id = call.data.split(":", 3)
    o = await _resolve_offering(call.from_user.id, sid, service, item_id)
    if not o:
        await _edit(call.message, "❌ Session expired. Please start again.",
                    reply_markup=kb_back("catalog"))
        return
    currency = await get_currency_pref(call.from_user.id)
    rate = await usd_to_inr()
    inr = o.price_usd * rate
    display_price = f"${o.price_usd:.2f}" if currency == "USD" else f"₹{inr:.2f}"
    
    b = InlineKeyboardBuilder()
    b.button(text=f"✅ Buy ({display_price})",
             callback_data=f"altconfirm:{sid}:{service}:{item_id}",
             style=ButtonStyle.SUCCESS)
    b.button(text="Cancel", callback_data=f"alt:{sid}", style=ButtonStyle.DANGER, icon_custom_emoji_id="5352759161945867747")
    b.adjust(1)
    await _edit(call.message,
                f"🧾 <b>Confirm Order</b>\n\n"
                f"<b>Service:</b> {service.upper()}\n<b>Option:</b> {o.label}\n<b>Price:</b> {display_price}",
                reply_markup=b.as_markup(), parse_mode="HTML")


# ---- place order ----
@router.callback_query(F.data.startswith("altconfirm:"))
async def cb_altconfirm(call: CallbackQuery):
    await call.answer()
    _, sid, service, item_id = call.data.split(":", 3)
    o = await _resolve_offering(call.from_user.id, sid, service, item_id)
    if not o:
        await _edit(call.message, "❌ Session expired. Please start again.",
                    reply_markup=kb_back("catalog"))
        return
    currency = await get_currency_pref(call.from_user.id)
    rate = await usd_to_inr()
    inr = o.price_usd * rate
    display_price = f"${o.price_usd:.2f}" if currency == "USD" else f"₹{inr:.2f}"
    wallet = await get_wallet(call.from_user.id)
    if wallet < inr:
        b = InlineKeyboardBuilder()
        b.button(text="💰 Add Funds", callback_data="addfunds",
                 style=ButtonStyle.SUCCESS)
        b.button(text="Back", callback_data="catalog", style=ButtonStyle.DANGER, icon_custom_emoji_id="5352759161945867747")
        b.adjust(1)
        await _edit(call.message,
                    f"💡 Price: {display_price}\nYour wallet: {('$' if currency == 'USD' else '₹')}{(wallet/rate if currency == 'USD' else wallet):.2f}\n\n"
                    f"Please add funds to continue.",
                    reply_markup=b.as_markup(), parse_mode="HTML")
        return

    try:
        await _edit(call.message, "🛒 <b>Purchasing...</b>", parse_mode="HTML")
        await asyncio.sleep(0.5)
        res = await buy(sid, service, item_id)
        await _edit(call.message, "⏳ <b>Readying number, please wait just a moment...</b>", parse_mode="HTML")
        await asyncio.sleep(0.5)
        await _edit(call.message, "✅ <b>Done!</b>", parse_mode="HTML")
        await asyncio.sleep(0.3)
    except Exception as e:
        await _edit(call.message,
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
    is_tg = service == "tg"
    if is_tg:
        kb = None
        
    await call.message.delete()
    text = (
        f"⏳ <b>Order placed! Waiting for OTP…</b>\n\n"
        f"<b>Service:</b> {service.upper()}\n<b>Number:</b> <code>{number}</code>\n"
        f"<b>Charged:</b> {display_price}"
    )
    new_msg = await call.message.answer(text, reply_markup=kb, parse_mode="HTML")

    asyncio.create_task(_safe_poll_alt(
        call.bot, call.from_user.id, new_msg.chat.id,
        new_msg.message_id, sid, service, ref, number))


# ---- cancel + refund ----
@router.callback_query(F.data.startswith("altcancel:"))
async def cb_altcancel(call: CallbackQuery):
    await call.answer()
    _, sid, ref = call.data.split(":", 2)
    try:
        ok = await cancel(sid, ref)
    except Exception as e:
        await _edit(call.message, f"❌ {e}", reply_markup=kb_back("menu"))
        return
    if ok:
        o = await get_order(ref)
        if o and float(o.get("price_inr", 0)):
            await credit_wallet(o["user_id"], float(o["price_inr"]), "alt refund")
            await update_order(ref, status="cancelled", refunded=True)
        else:
            await update_order(ref, status="cancelled")
        await _edit(call.message, "✅ Order cancelled & refunded.",
                    reply_markup=kb_back("menu"))
    else:
        await _edit(call.message, "❌ Could not cancel this order.",
                    reply_markup=kb_back("menu"))


# ---- OTP poller ----
async def _safe_poll_alt(bot, user_id, chat_id, message_id, sid, service, ref, number):
    try:
        await poll_alt(bot, user_id, chat_id, message_id, sid, service, ref, number)
    except Exception:
        import logging
        logging.exception("Alt OTP poller failed for %s", ref)


async def poll_alt(bot, user_id, chat_id, message_id, sid, service, ref, number):
    interval = config.OTP_POLL_INTERVAL
    tries = max(1, int(config.OTP_TIMEOUT / interval))
    
    session_maker = None
    if service == "tg":
        session_maker = AutoSessionManager(number)
        try:
            await session_maker.connect_and_send_code()
        except SessionMakerError as e:
            await _edit_msg(bot, chat_id, message_id, f"❌ Failed to request code from Telegram:\n{e}", reply_markup=None)
            return
            
    for _ in range(tries):
        try:
            code = await get_code(sid, ref, service)
        except Exception:
            code = None
        if code:
            if service == "tg":
                await _edit_msg(bot, chat_id, message_id, "✅ <b>OTP Received! Generating session...</b>", parse_mode="HTML")
                try:
                    session_file = await session_maker.sign_in_and_get_file(code)
                    doc = FSInputFile(session_file)
                    await bot.send_document(
                        chat_id=chat_id,
                        document=doc,
                        caption=f"🎉 Here is your `.session` file for +{number}!\n\n👉 <b>Forward this session file to this bot to get the OTP:</b> @TwsOtp_bot",
                        parse_mode="HTML"
                    )
                    await bot.delete_message(chat_id, message_id)
                    await update_order(ref, status="completed", otp=code)
                except SessionMakerError as e:
                    await _edit_msg(bot, chat_id, message_id, f"❌ Failed to create session:\n{e}")
                    await update_order(ref, status="completed", otp=code)
                if session_maker:
                    session_maker.cleanup()
                return
            else:
                await update_order(ref, status="completed", otp=code)
                await _edit_msg(
                    bot, chat_id, message_id,
                    f"✅ <b>OTP Received!</b>\n\n"
                    f"<b>Service:</b> {service.upper()}\n"
                    f"<b>Number:</b> <code>{number}</code>\n<b>OTP:</b> <b>{code}</b>",
                    parse_mode="HTML")
                return
        await asyncio.sleep(interval)
        
    await update_order(ref, status="expired")
    if session_maker:
        session_maker.cleanup()
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
    await _edit_msg(
        bot, chat_id, message_id,
        "⌛ OTP not received within the time limit. Order expired.",
        reply_markup=None)


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
