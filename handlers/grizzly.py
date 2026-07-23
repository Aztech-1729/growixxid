"""Shop flow for GrizzlySMS (3000+ Services)."""
import asyncio
import html

from aiogram import Router, F
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import config
from core.db import (add_order, get_order, get_wallet, deduct_wallet,
                credit_wallet, update_order, get_currency_pref, get_setting)
from ui.keyboards import kb_back
from utils.rates import usd_to_inr
from services.grizzly_api import grizzly, GrizzlySMSError
from utils.flags import flag_from_name
from utils.session_maker import AutoSessionManager, SessionMakerError
from aiogram.types import FSInputFile
import time

router = Router()

SERVICES_CACHE = []
OFFERINGS_CACHE = {}
PAGE_SIZE = 10


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


def _kb_cancel(ref: str, locked: bool = False, lock_time: int = 0):
    b = InlineKeyboardBuilder()
    if locked:
        b.button(text=f"🔒 Cancel (Available in {lock_time}s)", callback_data="locked_cancel")
    else:
        b.button(text="❌ Cancel & Refund", callback_data=f"grzcancel:{ref}",
                 style=ButtonStyle.DANGER)
    b.adjust(1)
    return b.as_markup()

@router.callback_query(F.data == "locked_cancel")
async def cb_locked_cancel(call: CallbackQuery):
    await call.answer("Cancel is not available yet. Please wait.", show_alert=True)


async def get_all_services():
    global SERVICES_CACHE
    if not SERVICES_CACHE:
        try:
            SERVICES_CACHE = await grizzly.services_list()
        except GrizzlySMSError:
            return []
    return SERVICES_CACHE


def _services_kb(services, page: int):
    b = InlineKeyboardBuilder()
    start = page * PAGE_SIZE
    chunk = services[start:start + PAGE_SIZE]
    for s in chunk:
        b.button(text=s["name"], callback_data=f"grzsvc:{s['code']}:0",
                 style=ButtonStyle.SUCCESS)
                 
    sizes = [2] * (len(chunk) // 2)
    if len(chunk) % 2 != 0:
        sizes.append(1)
        
    nav_count = 0
    if page > 0:
        b.button(text="Prev", callback_data=f"grizzly:menu:{page - 1}", style=ButtonStyle.PRIMARY, icon_custom_emoji_id="5438531879345076160")
        nav_count += 1
    if start + PAGE_SIZE < len(services):
        b.button(text="Next", callback_data=f"grizzly:menu:{page + 1}", style=ButtonStyle.PRIMARY, icon_custom_emoji_id="5435955998479102657")
        nav_count += 1
        
    if nav_count:
        sizes.append(nav_count)
        
    b.button(text="Search", callback_data="search:grz_svc", style=ButtonStyle.PRIMARY, icon_custom_emoji_id="5429571366384842791")
    sizes.append(1)
        
    b.button(text="Back", callback_data="catalog", style=ButtonStyle.DANGER, icon_custom_emoji_id="5352759161945867747")
    sizes.append(1)
    
    b.adjust(*sizes)
    return b.as_markup()


# ---- supplier menu (Services) ----
@router.callback_query(F.data.startswith("grizzly:menu:"))
async def cb_grizzly_menu(call: CallbackQuery):
    await call.answer()
    page = int(call.data.split(":")[2])
    services = await get_all_services()
    if not services:
        await _edit(call.message, "❌ Could not load GrizzlySMS services.", reply_markup=kb_back("catalog"))
        return
        
    await _edit(call.message,
                "🌍 <b>3000+ Services</b>\n<b>Choose a service:</b>",
                reply_markup=_services_kb(services, page), parse_mode="HTML")


# ---- service -> offering list ----
@router.callback_query(F.data.startswith("grzsvc:"))
async def cb_grzsvc(call: CallbackQuery):
    await call.answer()
    parts = call.data.split(":")
    service_code = parts[1]
    page = int(parts[2])
    sort_mode = parts[3] if len(parts) > 3 else "name"
    
    services = await get_all_services()
    service_name = next((s["name"] for s in services if s["code"] == service_code), service_code)
    
    items = OFFERINGS_CACHE.get(service_code)
    if items is None:
        try:
            margin = float(await get_setting("global_margin", 0.0))
            prices = await grizzly.prices(service_code)
            countries = await grizzly.countries()
            
            names = {str(c["id"]): (c.get("eng") or c.get("rus") or str(c["id"])) for c in countries}
            items = []
            for cid, svcs in prices.items():
                d = svcs.get(service_code)
                if not d:
                    continue
                count = int(d.get("count", 0))
                if count <= 0:
                    continue
                eng_name = names.get(str(cid), cid)
                flag = flag_from_name(eng_name)
                label = f"{flag} {eng_name}" if flag else eng_name
                items.append({
                    "id": str(cid),
                    "label": label,
                    "price_usd": float(d["cost"]) * (1 + margin / 100),
                    "stock": count
                })
            items.sort(key=lambda o: o["label"].lower())
            OFFERINGS_CACHE[service_code] = items
        except Exception as e:
            await _edit(call.message, f"❌ {e}", reply_markup=kb_back("grizzly:menu:0"))
            return
            
    if not items:
        await _edit(call.message, f"😕 No numbers available right now for <b>{service_name}</b>.",
                    reply_markup=kb_back("grizzly:menu:0"), parse_mode="HTML")
        return
        
    currency = await get_currency_pref(call.from_user.id)
    rate = await usd_to_inr()
    
    sorted_items = list(items)
    if sort_mode == "cheap":
        sorted_items.sort(key=lambda o: o["price_usd"])
    elif sort_mode == "qty":
        sorted_items.sort(key=lambda o: o["stock"], reverse=True)
        
    from ui.keyboards import CUSTOM_EMOJIS
    emoji_tag = "🌍"
    if service_code in CUSTOM_EMOJIS:
        emoji_tag = f"<tg-emoji emoji-id='{CUSTOM_EMOJIS[service_code][1]}'>{CUSTOM_EMOJIS[service_code][0]}</tg-emoji>"
        
    await _edit(call.message,
        f"{emoji_tag} <b>{service_name}</b>\n<b>Choose a country:</b>",
        reply_markup=_offering_kb(service_code, service_name, sorted_items, page, currency, rate, sort_mode), parse_mode="HTML")


def _offering_kb(service_code, service_name, items, page, currency="INR", rate=83.0, sort_mode="name"):
    b = InlineKeyboardBuilder()
    start = page * PAGE_SIZE
    chunk = items[start:start + PAGE_SIZE]
    for o in chunk:
        if currency == "USD":
            label = f"{o['label']} — ${o['price_usd']:.2f}"
        else:
            inr = o['price_usd'] * rate
            label = f"{o['label']} — ₹{inr:.2f}"
            
        if o.get("stock") is not None:
            label += f" ({o['stock']} left)"
        b.button(text=label, callback_data=f"grzbuy:{service_code}:{o['id']}",
                 style=ButtonStyle.SUCCESS)
                 
    sizes = [1] * len(chunk)
    
    # Sort buttons
    b.button(text="Cheapest", callback_data=f"grzsvc:{service_code}:0:cheap", style=ButtonStyle.PRIMARY, icon_custom_emoji_id="6240224423207507713")
    b.button(text="High Quantity", callback_data=f"grzsvc:{service_code}:0:qty", style=ButtonStyle.PRIMARY, icon_custom_emoji_id="5472392465203862636")
    sizes.append(2)
    
    nav_count = 0
    if page > 0:
        b.button(text="Prev", callback_data=f"grzsvc:{service_code}:{page - 1}:{sort_mode}", style=ButtonStyle.PRIMARY, icon_custom_emoji_id="5438531879345076160")
        nav_count += 1
    if start + PAGE_SIZE < len(items):
        b.button(text="Next", callback_data=f"grzsvc:{service_code}:{page + 1}:{sort_mode}", style=ButtonStyle.PRIMARY, icon_custom_emoji_id="5435955998479102657")
        nav_count += 1
        
    if nav_count:
        sizes.append(nav_count)
        
    b.button(text="Search", callback_data=f"search:grz_ctry:{service_code}", style=ButtonStyle.PRIMARY, icon_custom_emoji_id="5429571366384842791")
    sizes.append(1)
        
    FEATURED = {'wa', 'ig', 'fb', 'lin', 'dy', 'fu', 'zpt', 'jx', 'go', 'aqj', 'aay'}
    back_data = "catalog" if service_code in FEATURED else "grizzly:menu:0"
    b.button(text="Back", callback_data=back_data, style=ButtonStyle.DANGER, icon_custom_emoji_id="5352759161945867747")
    sizes.append(1)
    
    b.adjust(*sizes)
    return b.as_markup()


# ---- confirm ----
@router.callback_query(F.data.startswith("grzbuy:"))
async def cb_grzbuy(call: CallbackQuery):
    await call.answer()
    _, service_code, country_id = call.data.split(":", 2)
    
    items = OFFERINGS_CACHE.get(service_code, [])
    o = next((x for x in items if x["id"] == country_id), None)
    if not o:
        await _edit(call.message, "❌ Session expired. Please start again.",
                    reply_markup=kb_back("grizzly:menu:0"))
        return
        
    services = await get_all_services()
    service_name = next((s["name"] for s in services if s["code"] == service_code), service_code)
        
    currency = await get_currency_pref(call.from_user.id)
    rate = await usd_to_inr()
    inr = o['price_usd'] * rate
    display_price = f"${o['price_usd']:.2f}" if currency == "USD" else f"₹{inr:.2f}"
    
    b = InlineKeyboardBuilder()
    b.button(text=f"✅ Buy ({display_price})",
             callback_data=f"grzconfirm:{service_code}:{country_id}",
             style=ButtonStyle.SUCCESS)
    b.button(text="Cancel", callback_data=f"grzsvc:{service_code}:0", style=ButtonStyle.DANGER, icon_custom_emoji_id="5352759161945867747")
    b.adjust(1)
    await _edit(call.message,
                f"🧾 <b>Confirm Order</b>\n\n"
                f"<b>Service:</b> {service_name}\n<b>Option:</b> {o['label']}\n<b>Price:</b> {display_price}",
                reply_markup=b.as_markup(), parse_mode="HTML")


# ---- place order ----
@router.callback_query(F.data.startswith("grzconfirm:"))
async def cb_grzconfirm(call: CallbackQuery):
    await call.answer()
    _, service_code, country_id = call.data.split(":", 2)
    
    items = OFFERINGS_CACHE.get(service_code, [])
    o = next((x for x in items if x["id"] == country_id), None)
    if not o:
        await _edit(call.message, "❌ Session expired. Please start again.",
                    reply_markup=kb_back("grizzly:menu:0"))
        return
        
    services = await get_all_services()
    service_name = next((s["name"] for s in services if s["code"] == service_code), service_code)
        
    currency = await get_currency_pref(call.from_user.id)
    rate = await usd_to_inr()
    inr = o['price_usd'] * rate
    display_price = f"${o['price_usd']:.2f}" if currency == "USD" else f"₹{inr:.2f}"
    
    wallet = await get_wallet(call.from_user.id)
    if wallet < inr:
        b = InlineKeyboardBuilder()
        b.button(text="💰 Add Funds", callback_data="addfunds",
                 style=ButtonStyle.SUCCESS)
        b.button(text="Back", callback_data="grizzly:menu:0", style=ButtonStyle.DANGER, icon_custom_emoji_id="5352759161945867747")
        b.adjust(1)
        await _edit(call.message,
                    f"💡 Price: {display_price}\nYour wallet: {('$' if currency == 'USD' else '₹')}{(wallet/rate if currency == 'USD' else wallet):.2f}\n\n"
                    f"Please add funds to continue.",
                    reply_markup=b.as_markup(), parse_mode="HTML")
        return

    try:
        await _edit(call.message, "🛒 <b>Purchasing...</b>", parse_mode="HTML")
        aid, number = await grizzly.get_number(service_code, country_id)
        
        await asyncio.sleep(0.5)
        await _edit(call.message, "⏳ <b>Readying number, please wait just a moment...</b>", parse_mode="HTML")
        
        margin = float(await get_setting("global_margin", 0.0))
        prices = await grizzly.prices(service_code, country_id)
        cost_usd = float(prices[country_id][service_code]["cost"]) * (1 + margin / 100)
        actual_inr = cost_usd * rate
        
        await asyncio.sleep(0.5)
        await _edit(call.message, "✅ <b>Done!</b>", parse_mode="HTML")
        await asyncio.sleep(0.3)
    except Exception as e:
        err_str = str(e)
        if "NO_NUMBERS" in err_str:
            # Remove the empty country from cache dynamically so nobody else sees it
            if service_code in OFFERINGS_CACHE:
                OFFERINGS_CACHE[service_code] = [x for x in OFFERINGS_CACHE[service_code] if x["id"] != country_id]
            
            await _edit(call.message,
                        f"❌ <b>Out of Stock!</b>\n\nGrizzly SMS just ran out of numbers for {o['label']}.\nI have temporarily removed it from the catalog. Please choose a different country.",
                        reply_markup=kb_back(f"grzsvc:{service_code}:0"), parse_mode="HTML")
        else:
            await _edit(call.message,
                        f"❌ Order failed: {html.escape(err_str)}",
                        reply_markup=kb_back("grizzly:menu:0"))
        return

    ref = aid
    await deduct_wallet(call.from_user.id, actual_inr, f"grizzly {service_code} {country_id}")
    await add_order(
        user_id=call.from_user.id, service=f"grz:{service_code}",
        country_code=country_id, country_name=o['label'], number=number,
        price=cost_usd, price_inr=actual_inr, order_ref=ref,
        supplier="grizzly", status="pending")

    await call.message.delete()
    
    is_tg = service_code == "tg"
    kb = None if is_tg else _kb_cancel(ref, locked=True, lock_time=120)
    
    if is_tg:
        text = (
            f"⏳ <b>Number acquired! Generating Telegram Session...</b>\n\n"
            f"<b>Service:</b> {service_name}\n<b>Number:</b> <code>{number}</code>\n"
            f"<b>Charged:</b> {display_price}"
        )
    else:
        text = (
            f"⏳ <b>Order placed! Waiting for OTP…</b>\n\n"
            f"<b>Service:</b> {service_name}\n<b>Number:</b> <code>{number}</code>\n"
            f"<b>Charged:</b> {display_price}\n\n"
            f"ℹ️ <i>You can wait for the OTP or cancel manually at any time. If no OTP is received before the provider's time limit, the order will be automatically cancelled and your wallet will be fully refunded!</i>"
        )
    
    new_msg = await call.message.answer(text, reply_markup=kb, parse_mode="HTML")

    asyncio.create_task(_safe_poll_grz(
        call.bot, call.from_user.id, new_msg.chat.id,
        new_msg.message_id, service_code, service_name, ref, number))


# ---- cancel + refund ----
@router.callback_query(F.data.startswith("grzcancel:"))
async def cb_grzcancel(call: CallbackQuery):
    await call.answer()
    _, ref = call.data.split(":", 1)
    try:
        res = await grizzly.set_status(ref, 8)
        ok = res.startswith("ACCESS")
    except Exception as e:
        await call.answer(f"❌ Cancel failed: {html.escape(str(e))}", show_alert=True)
        return

    if ok:
        o = await get_order(ref)
        if o and float(o.get("price_inr", 0)):
            await credit_wallet(o["user_id"], float(o["price_inr"]), f"Refund for cancelled grizzly order {ref}")
            await update_order(ref, status="cancelled", refunded=True)
            await _edit(call.message, "✅ Order cancelled & refunded.", reply_markup=kb_back("menu"))
        else:
            await _edit(call.message, "✅ Order cancelled.", reply_markup=kb_back("menu"))
    else:
        await call.answer("❌ Order could not be cancelled. It may have already expired or completed.", show_alert=True)


# ---- OTP poller ----
async def _safe_poll_grz(bot, user_id, chat_id, message_id, service_code, service_name, ref, number):
    try:
        await poll_grz(bot, user_id, chat_id, message_id, service_code, service_name, ref, number)
    except Exception:
        import logging
        logging.exception("Grizzly OTP poller failed for %s", ref)


async def poll_grz(bot, user_id, chat_id, message_id, service_code, service_name, ref, number):
    interval = config.OTP_POLL_INTERVAL
    max_loops = int(1800 / interval)  # 30 mins max safety net
    
    start_time = time.time()
    locked = True
    
    session_maker = None
    if service_code == "tg":
        session_maker = AutoSessionManager(number)
        try:
            await session_maker.connect_and_send_code()
        except SessionMakerError as e:
            await _edit_msg(bot, chat_id, message_id, f"❌ Failed to request code from Telegram:\n{e}", reply_markup=None)
            return

    for _ in range(max_loops):
        try:
            st = await grizzly.get_status(ref)
        except Exception:
            st = ""
            
        if st.startswith("STATUS_OK:"):
            code = st.split(":", 1)[1]
            if service_code == "tg":
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
                    f"<b>Service:</b> {service_name}\n"
                    f"<b>Number:</b> <code>{number}</code>\n<b>OTP:</b> <b>{code}</b>",
                    parse_mode="HTML")
                return
        elif st == "STATUS_CANCEL":
            break
            
        elapsed = int(time.time() - start_time)
        if service_code != "tg":
            if locked:
                remaining_lock = 120 - elapsed
                if remaining_lock <= 0:
                    locked = False
                    try:
                        await _edit_msg(bot, chat_id, message_id,
                            f"⏳ <b>Waiting for OTP…</b>\n\n<b>Number:</b> <code>{number}</code>\n"
                            f"<i>Order will auto-expire in {int(20 - elapsed/60)} minutes.</i>",
                            reply_markup=_kb_cancel(ref), parse_mode="HTML")
                    except TelegramBadRequest:
                        pass
                else:
                    try:
                        await _edit_msg(bot, chat_id, message_id,
                            f"⏳ <b>Waiting for OTP…</b>\n\n<b>Number:</b> <code>{number}</code>\n"
                            f"<i>Order will auto-expire in {int(20 - elapsed/60)} minutes.</i>",
                            reply_markup=_kb_cancel(ref, locked=True, lock_time=remaining_lock), parse_mode="HTML")
                    except TelegramBadRequest:
                        pass
            else:
                # Just update the expiry timer every minute or so, but let's do it every 15s to avoid flood
                if elapsed % 15 < interval:
                    try:
                        await _edit_msg(bot, chat_id, message_id,
                            f"⏳ <b>Waiting for OTP…</b>\n\n<b>Number:</b> <code>{number}</code>\n"
                            f"<i>Order will auto-expire in {int(20 - elapsed/60)} minutes.</i>",
                            reply_markup=_kb_cancel(ref), parse_mode="HTML")
                    except TelegramBadRequest:
                        pass
            
        await asyncio.sleep(interval)
        
    await update_order(ref, status="expired")
    if session_maker:
        session_maker.cleanup()
        
    try:
        o = await get_order(ref)
        if o and float(o.get("price_inr", 0)):
            await credit_wallet(o["user_id"], float(o["price_inr"]),
                                "Refund for expired grizzly order")
            await update_order(ref, status="cancelled", refunded=True)
    except Exception:
        pass
        
    await _edit_msg(
        bot, chat_id, message_id,
        "⌛ <b>OTP not received!</b>\n\nThe provider's wait time has expired. The order has been automatically cancelled and your wallet has been fully refunded.",
        reply_markup=None, parse_mode="HTML")
