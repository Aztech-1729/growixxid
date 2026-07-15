"""Unified supplier layer for alternate (non-VNHOTP) number providers.

Providers wired here:
  * tiger -> TigerSMS (SMS-Activate style, cheapest India TG ~$0.12/₹10)
"""
from dataclasses import dataclass
from typing import Optional

from tigersms import tigersms, TigerSMSError
from flags import flag_from_name


@dataclass
class Offering:
    id: str                 # supplier-native selection id (country id)
    label: str              # human label
    price_usd: float        # provider price in USD
    stock: Optional[int]    # available count (None if unknown)
    meta: dict              # extra info carried to the buy step


SUPPLIERS = {
    "tiger": {
        "name": "TigerSMS",
        "subtitle": "Global • cheapest India TG ₹10",
        "client": tigersms,
        "error": TigerSMSError,
        "services": [
            {"key": "tg", "label": "📱 Telegram", "native": "tg", "cancellable": True},
            {"key": "wa", "label": "💬 WhatsApp", "native": "wa", "cancellable": True},
        ],
    },
}


def supplier_service(sid: str, service_key: str) -> dict:
    return next(s for s in SUPPLIERS[sid]["services"] if s["key"] == service_key)


# ---- offerings (what the user can buy) ------------------------------------
async def get_offerings(sid: str, service_key: str) -> list:
    if sid == "tiger":
        return await _tiger_offerings(service_key)
    return []


async def _tiger_offerings(service_key: str) -> list:
    svc = supplier_service("tiger", service_key)
    try:
        prices = await tigersms.prices(service_key)
        countries = await tigersms.countries(service_key)
    except TigerSMSError as e:
        raise TigerSMSError(f"Could not load TigerSMS catalog: {e}")
    names = {str(c["id"]): (c.get("eng") or c.get("rus") or str(c["id"])) for c in countries}
    out = []
    for cid, svcs in prices.items():
        d = svcs.get(service_key)
        if not d:
            continue
        count = int(d.get("count", 0))
        if count <= 0:
            continue
        eng_name = names.get(str(cid), cid)
        flag = flag_from_name(eng_name)
        out.append(Offering(
            id=str(cid),
            label=f"{flag} {eng_name}",
            price_usd=float(d["cost"]),
            stock=count,
            meta={"native": svc["native"], "cancellable": svc["cancellable"]},
        ))
    out.sort(key=lambda o: o.label.lower())
    return out


# ---- buy / code / cancel --------------------------------------------------
async def buy(sid: str, service_key: str, item_id: str) -> dict:
    if sid == "tiger":
        svc = supplier_service("tiger", service_key)
        aid, number = await tigersms.get_number(svc["native"], item_id)
        prices = await tigersms.prices(service_key, item_id)
        cost = float(prices[item_id][service_key]["cost"])
        return {
            "ref": aid,
            "number": number,
            "cost_usd": cost,
            "native": svc["native"],
        }
    raise ValueError("unknown supplier")


async def get_code(sid: str, ref: str, service_key: str):
    if sid == "tiger":
        st = await tigersms.get_status(ref)
        if st.startswith("STATUS_OK:"):
            return st.split(":", 1)[1]
        return None
    return None


async def cancel(sid: str, ref: str) -> bool:
    if sid == "tiger":
        res = await tigersms.set_status(ref, 8)  # 8 = cancel activation
        return res.startswith("ACCESS")
    return False


async def balance(sid: str) -> float:
    if sid == "tiger":
        return await tigersms.balance()
    raise ValueError("unknown supplier")
