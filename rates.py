"""Live USD→INR exchange rate with 5-minute cache."""
import time
import httpx

_cache = {"rate": None, "updated": 0}

async def usd_to_inr() -> float:
    now = time.time()
    if _cache["rate"] is not None and now - _cache["updated"] < 300:
        return _cache["rate"]
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://api.exchangerate-api.com/v4/latest/USD")
            _cache["rate"] = float(r.json()["rates"]["INR"])
            _cache["updated"] = now
    except Exception:
        if _cache["rate"] is None:
            _cache["rate"] = 83.0
    return _cache["rate"]
