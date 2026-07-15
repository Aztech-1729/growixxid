"""Inline keyboards. Every action button uses a Bot API 9.4 style:
   PRIMARY (blue) = navigation / selection, SUCCESS (green) = buyable stock
   option, DANGER (red) = destructive / back / pagination nav.
"""
from aiogram.enums import ButtonStyle
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config

PRIMARY = ButtonStyle.PRIMARY
SUCCESS = ButtonStyle.SUCCESS
DANGER = ButtonStyle.DANGER


def kb_main(is_admin: bool = False):
    b = InlineKeyboardBuilder()
    b.button(text="🛒 Browse Numbers", callback_data="catalog", style=PRIMARY)
    b.button(text="💰 My Wallet", callback_data="wallet", style=PRIMARY)
    b.button(text="📜 My Orders", callback_data="myorders", style=PRIMARY)
    b.button(text="ℹ️ How to Use", callback_data="help", style=PRIMARY)
    if is_admin:
        b.button(text="👑 Admin", callback_data="admin", style=PRIMARY)
    b.adjust(1)
    return b.as_markup()


def kb_wallet(currency: str):
    b = InlineKeyboardBuilder()
    b.button(text=f"🔄 Switch to {'USD' if currency == 'INR' else 'INR'}",
             callback_data="toggle_currency", style=PRIMARY)
    b.button(text="➕ Add Funds", callback_data="addfunds", style=SUCCESS)
    b.button(text="🔙 Back", callback_data="menu", style=DANGER)
    b.adjust(1)
    return b.as_markup()


def kb_service():
    b = InlineKeyboardBuilder()
    b.button(text="📱 Telegram (VNHOTP)", callback_data="svc:tg", style=PRIMARY)
    b.button(text="💬 WhatsApp (VNHOTP)", callback_data="svc:wp", style=PRIMARY)
    b.button(text="💬 WhatsApp 2 (VNHOTP)", callback_data="svc:wp2", style=PRIMARY)
    b.button(text="🐯 TigerSMS (India ₹10)", callback_data="alt:tiger", style=PRIMARY)
    b.button(text="🔙 Back", callback_data="menu", style=DANGER)
    b.adjust(1)
    return b.as_markup()


def kb_countries(service, countries, page, page_size: int = 8):
    b = InlineKeyboardBuilder()
    start = page * page_size
    chunk = countries[start:start + page_size]
    for c in chunk:
        label = c["name"]
        if c.get("price") is not None:
            inr_price = float(c["price"]) * config.USD_INR_RATE
            label += f" — {config.CURRENCY}{inr_price:.2f}"
        if service == "tg" and c.get("qty") is not None:
            label += f" ({c['qty']} left)"
        # stock / buyable option -> SUCCESS
        b.button(text=label, callback_data=f"buy:{service}:{c['code']}", style=SUCCESS)
    if page > 0:
        b.button(text="◀️ Prev", callback_data=f"ctry:{service}:{page - 1}", style=DANGER)
    if start + page_size < len(countries):
        b.button(text="Next ▶️", callback_data=f"ctry:{service}:{page + 1}", style=DANGER)
    b.button(text="🔙 Back", callback_data="catalog", style=DANGER)
    b.adjust(1)
    return b.as_markup()


def kb_confirm(service, code, name, price):
    b = InlineKeyboardBuilder()
    b.button(text=f"✅ Buy (₹{price})",
             callback_data=f"confirm:{service}:{code}", style=SUCCESS)
    b.button(text="🔙 Cancel", callback_data="catalog", style=DANGER)
    b.adjust(1)
    return b.as_markup()


def kb_order_wp(service, ref):
    b = InlineKeyboardBuilder()
    b.button(text="❌ Cancel & Refund",
             callback_data=f"cancel:{service}:{ref}", style=DANGER)
    b.adjust(1)
    return b.as_markup()


def kb_join():
    b = InlineKeyboardBuilder()
    b.button(text="🔗 Join Channel", url=config.channel_link, style=PRIMARY)
    b.button(text="✅ I've Joined", callback_data="join_check", style=SUCCESS)
    b.adjust(1)
    return b.as_markup()


def kb_back(callback: str = "menu"):
    b = InlineKeyboardBuilder()
    b.button(text="🔙 Back", callback_data=callback, style=DANGER)
    b.adjust(1)
    return b.as_markup()


def kb_admin():
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Refresh", callback_data="admin", style=PRIMARY)
    b.button(text="🔙 Back", callback_data="menu", style=DANGER)
    b.adjust(1)
    return b.as_markup()
