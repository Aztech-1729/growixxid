from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from core.states import SearchState
from core.db import get_user_orders, get_currency_pref
from ui.keyboards import kb_back
from utils.rates import usd_to_inr
from handlers.common import _edit
from aiogram.types import BufferedInputFile
from core.config import config

async def _answer_with_image(msg: Message, text: str, reply_markup=None, parse_mode="HTML"):
    try:
        with open(config.START_IMAGE, "rb") as f:
            photo_data = f.read()
        photo_input = BufferedInputFile(photo_data, filename="start.jpg")
    except Exception:
        photo_input = config.START_IMAGE
    
    await msg.answer_photo(photo=photo_input, caption=text, reply_markup=reply_markup, parse_mode=parse_mode)

router = Router()

@router.callback_query(F.data.startswith("search:"))
async def cb_search(call: CallbackQuery, state: FSMContext):
    await call.answer()
    parts = call.data.split(":")
    search_type = parts[1]
    
    if search_type == "orders":
        await state.set_state(SearchState.waiting_for_order_query)
        await _edit(call.message, "🔍 <b>Search Orders</b>\n\nPlease type the number, service, or country you are looking for (e.g. 1940 or TG):", reply_markup=kb_back("myorders"), parse_mode="HTML")
        
    elif search_type == "alt":
        sid = parts[2]
        service = parts[3]
        await state.update_data(search_sid=sid, search_service=service)
        await state.set_state(SearchState.waiting_for_service_query)
        await _edit(call.message, "🔍 <b>Search Countries</b>\n\nPlease type the country name you are looking for:", reply_markup=kb_back(f"altcat:{sid}:{service}"), parse_mode="HTML")
        
    elif search_type == "ctry":
        service = parts[2]
        await state.update_data(search_service=service)
        await state.set_state(SearchState.waiting_for_ctry_query)
        await _edit(call.message, "🔍 <b>Search Countries</b>\n\nPlease type the country name you are looking for:", reply_markup=kb_back(f"svc:{service}" if service != "tg" else "catalog"), parse_mode="HTML")
        
    elif search_type == "grz_svc":
        await state.set_state(SearchState.waiting_for_grz_svc_query)
        await _edit(call.message, "🔍 <b>Search Services</b>\n\nPlease type the service name you are looking for (e.g. Google):", reply_markup=kb_back("grizzly:menu:0"), parse_mode="HTML")
        
    elif search_type == "grz_ctry":
        service = parts[2]
        await state.update_data(search_service=service)
        await state.set_state(SearchState.waiting_for_grz_ctry_query)
        await _edit(call.message, "🔍 <b>Search Countries</b>\n\nPlease type the country name you are looking for:", reply_markup=kb_back(f"grzsvc:{service}:0"), parse_mode="HTML")


@router.message(SearchState.waiting_for_order_query)
async def process_order_search(msg: Message, state: FSMContext):
    query = msg.text.lower()
    await state.clear()
    
    all_orders = await get_user_orders(msg.from_user.id, limit=100)
    filtered = []
    for o in all_orders:
        if query in str(o.get('number', '')).lower() or query in o.get('service', '').lower() or query in o.get('country_name', '').lower() or query in o.get('country_code', '').lower():
            filtered.append(o)
            
    if not filtered:
        await _answer_with_image(msg, "📭 No orders matched your search.", reply_markup=kb_back("myorders"))
        return
        
    text = f"🔍 <b>Search results for '{msg.text}'</b>\n\n"
    for o in filtered[:10]:
        svc_name = o['service'].upper()
        if ":" not in svc_name:
            svc_name = f"{svc_name} {o['country_code']}"
            
        text += f"• {svc_name} — <code>+{o['number']}</code>\n  Status: {o['status']}"
        if o.get("otp"):
            text += f" | OTP: <b>{o['otp']}</b>"
        text += "\n"
        
    if len(filtered) > 10:
        text += f"\n<i>...and {len(filtered)-10} more.</i>"
        
    await _answer_with_image(msg, text, reply_markup=kb_back("myorders"), parse_mode="HTML")


@router.message(SearchState.waiting_for_service_query)
async def process_service_search(msg: Message, state: FSMContext):
    query = msg.text.lower()
    data = await state.get_data()
    sid = data.get("search_sid")
    service = data.get("search_service")
    await state.clear()
    
    if not sid or not service:
        await _answer_with_image(msg, "❌ Search session expired.", reply_markup=kb_back("catalog"))
        return
        
    from handlers.alt import CACHE, _offering_kb
    items = CACHE.get(msg.from_user.id, {}).get(f"{sid}:{service}", [])
    
    filtered = [o for o in items if query in o.label.lower()]
    
    if not filtered:
        await _answer_with_image(msg, f"😕 No countries matched '{msg.text}'.", reply_markup=kb_back(f"altcat:{sid}:{service}"))
        return
        
    currency = await get_currency_pref(msg.from_user.id)
    rate = await usd_to_inr()
    
    kb = _offering_kb(sid, service, filtered, 0, currency, rate)
    
    await _answer_with_image(msg, f"🔍 <b>Search results for '{msg.text}'</b>\nChoose an option:", reply_markup=kb, parse_mode="HTML")


@router.message(SearchState.waiting_for_ctry_query)
async def process_ctry_search(msg: Message, state: FSMContext):
    query = msg.text.lower()
    data = await state.get_data()
    service = data.get("search_service")
    await state.clear()
    
    if not service:
        await _answer_with_image(msg, "❌ Search session expired.", reply_markup=kb_back("catalog"))
        return
        
    from handlers.catalog import CACHE, _countries
    from keyboards import kb_countries
    
    countries = CACHE.get(msg.from_user.id, {}).get(service) or await _countries(service, msg.from_user.id)
    
    filtered = [c for c in countries if query in c['name'].lower()]
    
    if not filtered:
        await _answer_with_image(msg, f"😕 No countries matched '{msg.text}'.", reply_markup=kb_back(f"svc:{service}" if service != "tg" else "catalog"))
        return
        
    currency = await get_currency_pref(msg.from_user.id)
    rate = await usd_to_inr()
    
    kb = kb_countries(service, filtered, 0, currency, rate)
    
    await _answer_with_image(msg, f"🔍 <b>Search results for '{msg.text}'</b>\nChoose a country:", reply_markup=kb, parse_mode="HTML")


@router.message(SearchState.waiting_for_grz_svc_query)
async def process_grz_svc_search(msg: Message, state: FSMContext):
    query = msg.text.lower()
    await state.clear()
    
    from handlers.grizzly import get_all_services, _services_kb
    services = await get_all_services()
    
    filtered = [s for s in services if query in s['name'].lower()]
    
    if not filtered:
        await _answer_with_image(msg, f"😕 No services matched '{msg.text}'.", reply_markup=kb_back("grizzly:menu:0"))
        return
        
    kb = _services_kb(filtered, 0)
    
    await _answer_with_image(msg, f"🔍 <b>Search results for '{msg.text}'</b>\nChoose a service:", reply_markup=kb, parse_mode="HTML")


@router.message(SearchState.waiting_for_grz_ctry_query)
async def process_grz_ctry_search(msg: Message, state: FSMContext):
    query = msg.text.lower()
    data = await state.get_data()
    service_code = data.get("search_service")
    await state.clear()
    
    if not service_code:
        await _answer_with_image(msg, "❌ Search session expired.", reply_markup=kb_back("grizzly:menu:0"))
        return
        
    from handlers.grizzly import OFFERINGS_CACHE, _offering_kb, get_all_services
    items = OFFERINGS_CACHE.get(service_code, [])
    
    services = await get_all_services()
    service_name = next((s["name"] for s in services if s["code"] == service_code), service_code)
    
    filtered = [c for c in items if query in c['label'].lower()]
    
    if not filtered:
        await _answer_with_image(msg, f"😕 No countries matched '{msg.text}'.", reply_markup=kb_back(f"grzsvc:{service_code}:0"))
        return
        
    currency = await get_currency_pref(msg.from_user.id)
    rate = await usd_to_inr()
    
    kb = _offering_kb(service_code, service_name, filtered, 0, currency, rate)
    
    await _answer_with_image(msg, f"🔍 <b>Search results for '{msg.text}'</b>\nChoose a country:", reply_markup=kb, parse_mode="HTML")
