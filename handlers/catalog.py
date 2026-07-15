"""Shop flow: catalog -> country -> confirm -> place order -> OTP delivery."""
import asyncio

from aiogram import Router, F
from aiogram.enums import ButtonStyle
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from db import add_order, get_user_orders, update_order, get_wallet, deduct_wallet
from keyboards import kb_back, kb_confirm, kb_countries, kb_order_wp, kb_service
from otp_poller import poll_and_update
from vnhotp import VNHOTPError, vnhotp

router = Router()

# In-memory catalog cache per user (single process). Refreshed each time the
# service is opened, so prices/stock stay current.
CACHE: dict = {}


async def _countries(service: str, user_id: int) -> list:
    if service == "tg":
        countries = await vnhotp.tg_countries()
    else:
        raw = await vnhotp.wp_countries(service)
        countries = [{
            "code": c["code"].upper(),
            "name": c["name"],
            "price": None,
            "qty": c.get("count"),
        } for c in raw]
    CACHE.setdefault(user_id, {})[service] = countries
    return countries


@router.callback_query(F.data == "catalog")
async def cb_catalog(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text("🛰 Select a service:", reply_markup=kb_service())


@router.callback_query(F.data.startswith("svc:"))
async def cb_svc(call: CallbackQuery):
    await call.answer()
    service = call.data.split(":")[1]
    try:
        countries = await _countries(service, call.from_user.id)
    except VNHOTPError as e:
        await call.message.edit_text(f"❌ {e}", reply_markup=kb_back("menu"))
        return
    if not countries:
        await call.message.edit_text(
            "😕 No countries available right now for this service.",
            reply_markup=kb_back("catalog"))
        return
    await call.message.edit_text(
        f"🌍 Choose a country — <b>{service.upper()}</b>:",
        reply_markup=kb_countries(service, countries, 0), parse_mode="HTML")


@router.callback_query(F.data.startswith("ctry:"))
async def cb_ctry(call: CallbackQuery):
    await call.answer()
    _, service, page = call.data.split(":")
    page = int(page)
    countries = CACHE.get(call.from_user.id, {}).get(service) or await _countries(service, call.from_user.id)
    await call.message.edit_text(
        f"🌍 Choose a country — <b>{service.upper()}</b>:",
        reply_markup=kb_countries(service, countries, page), parse_mode="HTML")


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery):
    await call.answer()
    _, service, code = call.data.split(":")
    countries = CACHE.get(call.from_user.id, {}).get(service, [])
    info = next((c for c in countries if c["code"].upper() == code.upper()), None)

    if not info or info.get("price") is None:
        try:
            if service == "tg":
                d = await vnhotp.tg_country_info(code)
                price = d.get("price")
            else:
                d = await vnhotp.wp_get_price(service, code)
                price = d.get("price")
            name = info["name"] if info else code
        except VNHOTPError as e:
            await call.message.edit_text(f"❌ {e}", reply_markup=kb_back("catalog"))
            return
        info = {"code": code, "name": name, "price": price}

    price = info["price"]
    inr = float(price) * config.USD_INR_RATE
    stock = None
    if service != "tg":
        try:
            gp = await vnhotp.wp_get_price(service, code)
            inr = float(gp.get("price_inr") or inr)
            stock = gp.get("stock")  # WP2 exposes live stock here
        except VNHOTPError:
            pass
    stock_line = f"Stock: {stock}\n" if stock is not None else ""
    await call.message.edit_text(
        f"🧾 <b>Confirm Order</b>\n\nService: <b>{service.upper()}</b>\n"
        f"Country: {info['name']}\n{stock_line}Price: ₹{inr:.2f}",
        reply_markup=kb_confirm(service, code, info["name"], f"{inr:.2f}"), parse_mode="HTML")


@router.callback_query(F.data.startswith("confirm:"))
async def cb_confirm(call: CallbackQuery):
    await call.answer()
    _, service, code = call.data.split(":")

    # 1) resolve INR price for the wallet check
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
        await call.message.edit_text(f"❌ {e}", reply_markup=kb_back("catalog"))
        return

    wallet = await get_wallet(call.from_user.id)
    if wallet < inr:
        b = InlineKeyboardBuilder()
        b.button(text="💰 Add Funds", callback_data="addfunds", style=ButtonStyle.SUCCESS)
        b.button(text="🔙 Back", callback_data="catalog", style=ButtonStyle.DANGER)
        b.adjust(1)
        await call.message.edit_text(
            f"💡 Price: ₹{inr:.2f}\nYour wallet: ₹{wallet:.2f}\n\nPlease add funds to continue.",
            reply_markup=b.as_markup(), parse_mode="HTML")
        return

    # 2) place the order with the provider
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
        await call.message.edit_text(
            f"❌ Order failed:\n<code>{e}</code>",
            reply_markup=kb_back("catalog"), parse_mode="HTML")
        return

    # 3) success -> deduct wallet, log order, start OTP polling
    await deduct_wallet(call.from_user.id, inr, f"order {service} {code}")
    await add_order(
        user_id=call.from_user.id, service=service, country_code=code,
        country_name=name, number=number, price=price, order_ref=ref, status="pending")

    kb = kb_order_wp(service, ref) if service != "tg" else kb_back("menu")
    await call.message.edit_text(
        f"⏳ Order placed! Waiting for OTP…\n\nService: <b>{service.upper()}</b>\n"
        f"Number: <code>{number}</code>\nCharged: ₹{inr:.2f}",
        reply_markup=kb, parse_mode="HTML")

    asyncio.create_task(
        _safe_poll(call.bot, call.from_user.id, call.message.chat.id,
                   call.message.message_id, service, ref, number))


@router.callback_query(F.data == "myorders")
async def cb_myorders(call: CallbackQuery):
    await call.answer()
    orders = await get_user_orders(call.from_user.id, limit=10)
    if not orders:
        await call.message.edit_text("📭 You have no orders yet.", reply_markup=kb_back("menu"))
        return
    text = "📜 <b>Your recent orders</b>\n\n"
    for o in orders:
        text += f"• {o['service'].upper()} {o['country_code']} — <code>{o['number']}</code>\n  Status: {o['status']}"
        if o.get("otp"):
            text += f" | OTP: <b>{o['otp']}</b>"
        text += "\n"
    await call.message.edit_text(text, reply_markup=kb_back("menu"), parse_mode="HTML")


@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel(call: CallbackQuery):
    await call.answer()
    _, service, ref = call.data.split(":")
    try:
        res = await vnhotp.wp_cancel_order(service, ref)
        await update_order(ref, status="cancelled", refund=str(res.get("message", "")))
        await call.message.edit_text(
            f"✅ Order cancelled & refunded.\n{res.get('message', '')}",
            reply_markup=kb_back("menu"))
    except VNHOTPError as e:
        await call.message.edit_text(f"❌ {e}", reply_markup=kb_back("menu"))


async def _safe_poll(bot, user_id, chat_id, message_id, service, ref, number):
    try:
        await poll_and_update(bot, user_id, chat_id, message_id, service, ref, number)
    except Exception:
        import logging
        logging.exception("OTP poller failed for %s", ref)
