"""Shop flow: catalog -> country -> confirm -> place order -> OTP delivery."""
import asyncio
import html

from aiogram import Router, F
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import config
from core.db import (add_order, get_user_orders, update_order, get_wallet, deduct_wallet, 
                get_currency_pref, count_user_orders, get_setting)
from ui.keyboards import kb_back, kb_confirm, kb_countries, kb_order_wp, kb_service, kb_myorders
from utils.otp_poller import poll_and_update
from utils.rates import usd_to_inr
from services.vnhotp import VNHOTPError, vnhotp

router = Router()

CACHE: dict = {}


async def _edit(msg, text, reply_markup=None, parse_mode=None):
    try:
        await msg.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest:
        try:
            await msg.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TelegramBadRequest:
            pass


async def _countries(service: str, user_id: int) -> list:
    margin = float(await get_setting("global_margin", 0.0))
    if service == "tg":
        countries = await vnhotp.tg_countries()
    else:
        raw = await vnhotp.wp_countries(service)
        countries = [{
            "code": c["code"].upper(),
            "name": c["name"],
            "price": float(c["price"]) * (1 + margin / 100) if c.get("price") is not None else None,
            "qty": c.get("count"),
        } for c in raw]
    CACHE.setdefault(user_id, {})[service] = countries
    return countries


@router.callback_query(F.data == "catalog")
async def cb_catalog(call: CallbackQuery):
    await call.answer()
    active = await get_setting("active_suppliers", ["vnhotp", "tigersms", "grizzly"])
    await _edit(call.message, "🛍 <b>Catalog</b>\n\nChoose a service:", reply_markup=kb_service(active), parse_mode="HTML")


@router.callback_query(F.data.startswith("svc:"))
async def cb_svc(call: CallbackQuery):
    await call.answer()
    service = call.data.split(":")[1]
    try:
        countries = await _countries(service, call.from_user.id)
    except VNHOTPError as e:
        await _edit(call.message, f"❌ {e}", reply_markup=kb_back("menu"))
        return
    if not countries:
        await _edit(call.message, "😕 No countries available right now for this service.",
                    reply_markup=kb_back("catalog"))
        return
    currency = await get_currency_pref(call.from_user.id)
    rate = await usd_to_inr()
    
    from ui.keyboards import CUSTOM_EMOJIS
    display_name = "Telegram" if service == "tg" else service.upper()
    emoji_tag = "🌍"
    if service in CUSTOM_EMOJIS:
        emoji_tag = f"<tg-emoji emoji-id='{CUSTOM_EMOJIS[service][1]}'>{CUSTOM_EMOJIS[service][0]}</tg-emoji>"
        
    await _edit(call.message,
        f"{emoji_tag} <b>Choose a country</b> — <b>{display_name}</b>:",
        reply_markup=kb_countries(service, countries, 0, currency, rate, "name"), parse_mode="HTML")


@router.callback_query(F.data.startswith("ctry:"))
async def cb_ctry(call: CallbackQuery):
    await call.answer()
    parts = call.data.split(":")
    service = parts[1]
    page = int(parts[2])
    sort_mode = parts[3] if len(parts) > 3 else "name"
    
    currency = await get_currency_pref(call.from_user.id)
    rate = await usd_to_inr()
    countries = CACHE.get(call.from_user.id, {}).get(service) or await _countries(service, call.from_user.id)
    
    sorted_countries = list(countries)
    if sort_mode == "cheap":
        # Handle cases where price might be None
        sorted_countries.sort(key=lambda c: float(c["price"]) if c.get("price") is not None else float('inf'))
    elif sort_mode == "qty":
        # Handle cases where qty might be None
        sorted_countries.sort(key=lambda c: int(c["qty"]) if c.get("qty") is not None else -1, reverse=True)
        
    from ui.keyboards import CUSTOM_EMOJIS
    display_name = "Telegram" if service == "tg" else service.upper()
    emoji_tag = "🌍"
    if service in CUSTOM_EMOJIS:
        emoji_tag = f"<tg-emoji emoji-id='{CUSTOM_EMOJIS[service][1]}'>{CUSTOM_EMOJIS[service][0]}</tg-emoji>"
        
    await _edit(call.message, f"{emoji_tag} <b>Choose a country</b> — <b>{display_name}</b>:",
                reply_markup=kb_countries(service, sorted_countries, page, currency, rate, sort_mode), parse_mode="HTML")


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery):
    await call.answer()
    _, service, code = call.data.split(":")
    countries = CACHE.get(call.from_user.id, {}).get(service, [])
    info = next((c for c in countries if c["code"].upper() == code.upper()), None)

    margin = float(await get_setting("global_margin", 0.0))
    if not info or info.get("price") is None:
        try:
            if service == "tg":
                d = await vnhotp.tg_country_info(code)
                price = float(d.get("price", 0)) * (1 + margin / 100)
            else:
                d = await vnhotp.wp_get_price(service, code)
                price = float(d.get("price", 0)) * (1 + margin / 100)
            name = info["name"] if info else code
        except VNHOTPError as e:
            await _edit(call.message, f"❌ {e}", reply_markup=kb_back("catalog"))
            return
        info = {"code": code, "name": name, "price": price}

    price = info["price"]
    currency = await get_currency_pref(call.from_user.id)
    rate = await usd_to_inr()
    inr = float(price) * rate
    
    stock = None
    if service != "tg":
        try:
            gp = await vnhotp.wp_get_price(service, code)
            inr = float(gp.get("price_inr", 0)) * (1 + margin / 100)
            stock = gp.get("stock")
        except VNHOTPError:
            pass
            
    stock_line = f"<b>Stock:</b> {stock}\n" if stock is not None else ""
    display_price = f"${float(price):.2f}" if currency == "USD" else f"₹{inr:.2f}"
    
    await _edit(call.message,
                f"🧾 <b>Confirm Order</b>\n\n<b>Service:</b> {service.upper()}\n"
                f"<b>Country:</b> {info['name']}\n{stock_line}<b>Price:</b> {display_price}",
                reply_markup=kb_confirm(service, code, info["name"], f"{float(price):.2f}" if currency == "USD" else f"{inr:.2f}", currency),
                parse_mode="HTML")


@router.callback_query(F.data.startswith("confirm:"))
async def cb_confirm(call: CallbackQuery):
    await call.answer()
    _, service, code = call.data.split(":")

    try:
        if service == "tg":
            ci = await vnhotp.tg_country_info(code)
            inr = float(ci.get("price", 0)) * config.USD_INR_RATE
            name = code
        else:
            gp = await vnhotp.wp_get_price(service, code)
            inr = float(gp.get("price_inr") or (gp.get("price", 0) * config.USD_INR_RATE))
            name = code
    except VNHOTPError as e:
        await _edit(call.message, f"❌ {e}", reply_markup=kb_back("catalog"))
        return

    wallet = await get_wallet(call.from_user.id)
    if wallet < inr:
        b = InlineKeyboardBuilder()
        b.button(text="💰 Add Funds", callback_data="addfunds", style=ButtonStyle.SUCCESS)
        b.button(text="Back", callback_data="catalog", style=ButtonStyle.DANGER, icon_custom_emoji_id="5352759161945867747")
        b.adjust(1)
        await _edit(call.message,
                    f"💡 Price: ₹{inr:.2f}\nYour wallet: ₹{wallet:.2f}\n\nPlease add funds to continue.",
                    reply_markup=b.as_markup(), parse_mode="HTML")
        return

    try:
        if service == "tg":
            d = await vnhotp.tg_place_order(code)
            number = d["number"]
            ref = number
            price = d["price"]
            name = d.get("name", code)
        else:
            d = await vnhotp.wp_place_order(service, code)
            ref = d["order_id"]; number = d["phone_number"]; price = d["price"]; name = code
    except VNHOTPError as e:
        await _edit(call.message, f"❌ Order failed: {html.escape(str(e))}",
                    reply_markup=kb_back("catalog"))
        return

    await deduct_wallet(call.from_user.id, inr, f"order {service} {code}")
    await add_order(
        user_id=call.from_user.id, service=service, country_code=code,
        country_name=name, number=number, price=price, order_ref=ref, status="pending")

    currency = await get_currency_pref(call.from_user.id)
    display_price = f"${price:.2f}" if currency == "USD" else f"₹{inr:.2f}"
    
    kb = kb_order_wp(service, ref) if service != "tg" else kb_back("menu")
    await _edit(call.message,
                f"⏳ <b>Order placed! Waiting for OTP…</b>\n\n<b>Service:</b> {service.upper()}\n"
                f"<b>Number:</b> <code>{number}</code>\n<b>Charged:</b> {display_price}",
                reply_markup=kb, parse_mode="HTML")

    asyncio.create_task(
        _safe_poll(call.bot, call.from_user.id, call.message.chat.id,
                   call.message.message_id, service, ref, number))


@router.callback_query(F.data.startswith("myorders"))
async def cb_myorders(call: CallbackQuery):
    await call.answer()
    parts = call.data.split(":")
    page = int(parts[1]) if len(parts) > 1 else 0
    page_size = 5
    
    orders = await get_user_orders(call.from_user.id, skip=page * page_size, limit=page_size)
    total = await count_user_orders(call.from_user.id)
    
    if not orders and page == 0:
        await _edit(call.message, "📭 You have no orders yet.", reply_markup=kb_back("menu"))
        return
        
    text = "📜 <b>Your recent orders</b>\n\n"
    for o in orders:
        svc_name = o['service'].upper()
        if ":" in svc_name:
            # e.g., TIGER:TG
            svc_name = svc_name
        else:
            svc_name = f"{svc_name} {o['country_code']}"
            
        text += f"• <b>{svc_name}</b> — <code>+{o['number']}</code>\n  <b>Status:</b> {o['status']}"
        if o.get("otp"):
            text += f" | <b>OTP:</b> <b>{o['otp']}</b>"
        text += "\n"
        
    has_more = (page + 1) * page_size < total
    await _edit(call.message, text, reply_markup=kb_myorders(page, has_more), parse_mode="HTML")


@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel(call: CallbackQuery):
    await call.answer()
    _, service, ref = call.data.split(":")
    try:
        res = await vnhotp.wp_cancel_order(service, ref)
        await update_order(ref, status="cancelled", refund=str(res.get("message", "")))
        await _edit(call.message,
                    f"✅ Order cancelled & refunded.\n{res.get('message', '')}",
                    reply_markup=kb_back("menu"))
    except VNHOTPError as e:
        await _edit(call.message, f"❌ {e}", reply_markup=kb_back("menu"))


async def _safe_poll(bot, user_id, chat_id, message_id, service, ref, number):
    try:
        await poll_and_update(bot, user_id, chat_id, message_id, service, ref, number)
    except Exception:
        import logging
        logging.exception("OTP poller failed for %s", ref)
