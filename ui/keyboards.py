"""Inline keyboards. Every action button uses a Bot API 9.4 style:
   PRIMARY (blue) = navigation / selection, SUCCESS (green) = buyable stock
   option, DANGER (red) = destructive / back / pagination nav.
"""
from aiogram.enums import ButtonStyle
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import config
from utils.flags import flag_from_code, flag_from_name

PRIMARY = ButtonStyle.PRIMARY
SUCCESS = ButtonStyle.SUCCESS
DANGER = ButtonStyle.DANGER

CUSTOM_EMOJIS = {
    'tg': ('📱', '5330237710655306682'),
    'wa': ('💬', '5334998226636390258'),
    'ig': ('📸', '5319160079465857105'),
    'fb': ('📘', '5323261730283863478'),
    'lin': ('🛒', '5350383177447779958'),
    'dy': ('🍔', '5334671517064117716'),
    'fu': ('👻', '5330248916224983855'),
    'zpt': ('🛵', '5044544625088398868'),
    'jx': ('🍲', '6292090383849493316'),
    'go': ('📧', '5796209712009581332'),
    'aqj': ('🍎', '5381929914100369265'),
    'aay': ('🛒', '5345961362587670316')
}


def kb_main(is_admin: bool = False):
    b = InlineKeyboardBuilder()
    b.button(text="Services", callback_data="catalog", style=SUCCESS, icon_custom_emoji_id="5780560530515171033")
    b.button(text="My Wallet", callback_data="wallet", style=SUCCESS, icon_custom_emoji_id="6028517788606272241")
    b.button(text="My Orders", callback_data="myorders", style=SUCCESS, icon_custom_emoji_id="5217939515754174728")
    b.button(text="How to Use", callback_data="help", style=PRIMARY, icon_custom_emoji_id="5436113877181941026")
    b.button(text="Customer Support", callback_data="support", style=DANGER, icon_custom_emoji_id="5870692618244984670")
    if is_admin:
        b.button(text="Admin", callback_data="admin", style=DANGER, icon_custom_emoji_id="5870692618244984670")
    b.adjust(1)
    return b.as_markup()


def kb_support():
    b = InlineKeyboardBuilder()
    b.button(text="Contact Admin", url="https://t.me/ur_Growixx222")
    b.button(text="Back", callback_data="menu", style=DANGER, icon_custom_emoji_id="5352759161945867747")
    b.adjust(1)
    return b.as_markup()


def kb_wallet(currency: str):
    b = InlineKeyboardBuilder()
    b.button(text=f"🔄 Switch to {'USD' if currency == 'INR' else 'INR'}",
             callback_data="toggle_currency", style=PRIMARY)
    b.button(text="➕ Add Funds", callback_data="addfunds", style=SUCCESS)
    b.button(text="Back", callback_data="menu", style=DANGER, icon_custom_emoji_id="5352759161945867747")
    b.adjust(1)
    return b.as_markup()




def kb_service(active_suppliers: list = None):
    if active_suppliers is None:
        active_suppliers = ["vnhotp", "tigersms", "grizzly"]
        
    b = InlineKeyboardBuilder()
    sizes = []
    
    # Native Telegram (VNHOTP)
    if "vnhotp" in active_suppliers:
        b.button(text="Telegram", callback_data="svc:tg", style=SUCCESS, icon_custom_emoji_id="5330237710655306682")
        sizes.append(1)
    
    # Grizzly specific services
    if "grizzly" in active_suppliers:
        b.button(text="WhatsApp", callback_data="grzsvc:wa:0", style=SUCCESS, icon_custom_emoji_id="5334998226636390258")
        b.button(text="Instagram", callback_data="grzsvc:ig:0", style=SUCCESS, icon_custom_emoji_id="5319160079465857105")
        sizes.append(2)
        
        b.button(text="Facebook", callback_data="grzsvc:fb:0", style=SUCCESS, icon_custom_emoji_id="5323261730283863478")
        b.button(text="Blinkit", callback_data="grzsvc:lin:0", style=SUCCESS, icon_custom_emoji_id="5350383177447779958")
        b.button(text="Zomato", callback_data="grzsvc:dy:0", style=SUCCESS, icon_custom_emoji_id="5334671517064117716")
        sizes.append(3)
        
        b.button(text="Snapchat", callback_data="grzsvc:fu:0", style=SUCCESS, icon_custom_emoji_id="5330248916224983855")
        b.button(text="Zepto", callback_data="grzsvc:zpt:0", style=SUCCESS, icon_custom_emoji_id="5044544625088398868")
        b.button(text="Swiggy", callback_data="grzsvc:jx:0", style=SUCCESS, icon_custom_emoji_id="6292090383849493316")
        sizes.append(3)
        
        b.button(text="Gmail", callback_data="grzsvc:go:0", style=SUCCESS, icon_custom_emoji_id="5796209712009581332")
        b.button(text="BigBasket", callback_data="grzsvc:aqj:0", style=SUCCESS, icon_custom_emoji_id="5381929914100369265")
        b.button(text="Jio Mart", callback_data="grzsvc:aay:0", style=SUCCESS, icon_custom_emoji_id="5345961362587670316")
        sizes.append(3)
        
        b.button(text="3000+ Services", callback_data="grizzly:menu:0", style=SUCCESS, icon_custom_emoji_id="5282843764451195532")
        sizes.append(1)
        
    elif "tigersms" in active_suppliers:
        b.button(text="3000+ Services", callback_data="alt:tiger", style=SUCCESS, icon_custom_emoji_id="5282843764451195532")
        sizes.append(1)
        
    # Back
    b.button(text="Back", callback_data="menu", style=DANGER, icon_custom_emoji_id="5352759161945867747")
    sizes.append(1)
    
    b.adjust(*sizes)
    

    return b.as_markup()


def kb_countries(service: str, countries: list, page: int = 0, currency: str = "INR", rate: float = 83.0, sort_mode: str = "name"):
    b = InlineKeyboardBuilder()
    page_size = 10
    start = page * page_size
    chunk = countries[start:start + page_size]
    for c in chunk:
        name = c['name']
        flag = flag_from_code(c.get("code", "")) or flag_from_name(name)
        if flag and flag in name:
            label = name
        else:
            label = f"{flag} {name}" if flag else name
        if c.get("price") is not None:
            if currency == "USD":
                label += f" — ${float(c['price']):.2f}"
            else:
                inr_price = float(c["price"]) * rate
                label += f" — {config.CURRENCY}{inr_price:.2f}"
        qty = c.get("qty")
        if qty is not None:
            label += f" ({qty} left)"
        b.button(text=label, callback_data=f"buy:{service}:{c['code']}", style=SUCCESS)
    
    sizes = [1] * len(chunk)
    
    # Sort buttons
    b.button(text="Cheapest", callback_data=f"ctry:{service}:0:cheap", style=PRIMARY, icon_custom_emoji_id="6240224423207507713")
    b.button(text="High Quantity", callback_data=f"ctry:{service}:0:qty", style=PRIMARY, icon_custom_emoji_id="5472392465203862636")
    sizes.append(2)
    
    nav_count = 0
    if page > 0:
        b.button(text="Prev", callback_data=f"ctry:{service}:{page - 1}:{sort_mode}", style=PRIMARY, icon_custom_emoji_id="5438531879345076160")
        nav_count += 1
    if start + page_size < len(countries):
        b.button(text="Next", callback_data=f"ctry:{service}:{page + 1}:{sort_mode}", style=PRIMARY, icon_custom_emoji_id="5435955998479102657")
        nav_count += 1
        
    if nav_count:
        sizes.append(nav_count)
        
    b.button(text="Search", callback_data=f"search:ctry:{service}", style=PRIMARY, icon_custom_emoji_id="5429571366384842791")
    sizes.append(1)
        
    b.button(text="Back", callback_data=f"svc:{service}" if service != "tg" else "catalog", style=DANGER, icon_custom_emoji_id="5352759161945867747")
    sizes.append(1)
    
    b.adjust(*sizes)
    return b.as_markup()


def kb_myorders(page: int, has_more: bool):
    b = InlineKeyboardBuilder()
    
    sizes = []
    
    nav_count = 0
    if page > 0:
        b.button(text="Prev", callback_data=f"myorders:{page - 1}", style=PRIMARY, icon_custom_emoji_id="5438531879345076160")
        nav_count += 1
    if has_more:
        b.button(text="Next", callback_data=f"myorders:{page + 1}", style=PRIMARY, icon_custom_emoji_id="5435955998479102657")
        nav_count += 1
        
    if nav_count:
        sizes.append(nav_count)
        
    b.button(text="Search", callback_data="search:orders", style=PRIMARY, icon_custom_emoji_id="5429571366384842791")
    sizes.append(1)
        
    b.button(text="Back", callback_data="menu", style=DANGER, icon_custom_emoji_id="5352759161945867747")
    sizes.append(1)
    
    b.adjust(*sizes)
    return b.as_markup()


def kb_confirm(service, code, name, price, currency="INR"):
    b = InlineKeyboardBuilder()
    symbol = "$" if currency == "USD" else "₹"
    b.button(text=f"✅ Buy ({symbol}{price})",
             callback_data=f"confirm:{service}:{code}", style=SUCCESS)
    b.button(text="Cancel", callback_data="catalog", style=DANGER, icon_custom_emoji_id="5352759161945867747")
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
    b.button(text="Back", callback_data=callback, style=DANGER, icon_custom_emoji_id="5352759161945867747")
    b.adjust(1)
    return b.as_markup()


def kb_admin():
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Refresh", callback_data="admin", style=PRIMARY)
    b.button(text="👥 User Lookup", callback_data="admin_user_lookup", style=PRIMARY)
    b.button(text="⚙️ Margin %", callback_data="admin_margin", style=PRIMARY)
    b.button(text="🔌 Suppliers", callback_data="admin_suppliers", style=PRIMARY)
    b.button(text="📊 Sales Report", callback_data="admin_sales", style=PRIMARY)
    b.button(text="❌ Failed Orders", callback_data="admin_failed", style=PRIMARY)
    b.button(text="Back", callback_data="menu", style=DANGER, icon_custom_emoji_id="5352759161945867747")
    b.adjust(1, 2, 2, 1, 1)
    return b.as_markup()

def kb_admin_user(user_id: int, is_banned: bool):
    b = InlineKeyboardBuilder()
    b.button(text="💰 Manage Balance", callback_data=f"admin_manage_bal:{user_id}", style=PRIMARY)
    if is_banned:
        b.button(text="✅ Unban User", callback_data=f"admin_ban_toggle:{user_id}", style=SUCCESS)
    else:
        b.button(text="🚫 Ban User", callback_data=f"admin_ban_toggle:{user_id}", style=DANGER)
    b.button(text="Back", callback_data="admin", style=DANGER, icon_custom_emoji_id="5352759161945867747")
    b.adjust(1, 1, 1)
    return b.as_markup()

def kb_admin_suppliers(active_list: list):
    b = InlineKeyboardBuilder()
    for s in ["vnhotp", "tigersms", "grizzly"]:
        status = "✅" if s in active_list else "❌"
        b.button(text=f"{status} {s.upper()}", callback_data=f"admin_sup_toggle:{s}")
    b.button(text="Back", callback_data="admin", style=DANGER, icon_custom_emoji_id="5352759161945867747")
    b.adjust(1)
    return b.as_markup()
