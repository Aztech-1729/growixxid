"""Live USD→INR exchange rate with 5-minute cache + config fallback."""
import time
import httpx

from core.config import config


class RateFetchError(Exception):
    """Raised when the live rate API is unreachable."""


_cache = {"rate": None, "updated": 0, "rub_rate": None, "rub_updated": 0}

async def usd_to_inr() -> float:
    now = time.time()
    if _cache["rate"] is not None and now - _cache["updated"] < 300:
        return _cache["rate"]
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://api.exchangerate-api.com/v4/latest/USD")
            if r.status_code != 200:
                raise RateFetchError(f"Rate API returned HTTP {r.status_code}")
            _cache["rate"] = float(r.json()["rates"]["INR"])
            _cache["updated"] = now
        return _cache["rate"]
    except Exception:
        # Never let a rate hiccup kill a purchase flow — fall back to config rate.
        _cache["rate"] = config.USD_INR_RATE
        _cache["updated"] = now
        return config.USD_INR_RATE

async def rub_to_inr() -> float:
    now = time.time()
    if _cache["rub_rate"] is not None and now - _cache["rub_updated"] < 300:
        return _cache["rub_rate"]
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://api.exchangerate-api.com/v4/latest/RUB")
            if r.status_code != 200:
                raise RateFetchError(f"Rate API returned HTTP {r.status_code}")
            _cache["rub_rate"] = float(r.json()["rates"]["INR"])
            _cache["rub_updated"] = now
        return _cache["rub_rate"]
    except Exception:
        _cache["rub_rate"] = config.USD_INR_RATE
        _cache["rub_updated"] = now
        return config.USD_INR_RATE
