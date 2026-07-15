"""Live USD→INR exchange rate with 5-minute cache. No fallback."""
import time
import httpx


class RateFetchError(Exception):
    """Raised when the live rate API is unreachable."""


_cache = {"rate": None, "updated": 0}

async def usd_to_inr() -> float:
    now = time.time()
    if _cache["rate"] is not None and now - _cache["updated"] < 300:
        return _cache["rate"]
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("https://api.exchangerate-api.com/v4/latest/USD")
        if r.status_code != 200:
            raise RateFetchError(f"Rate API returned HTTP {r.status_code}")
        _cache["rate"] = float(r.json()["rates"]["INR"])
        _cache["updated"] = now
    return _cache["rate"]
