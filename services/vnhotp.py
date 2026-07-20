"""Async client for the VNHOTP API (https://api.vnhotp.com).

All endpoints are GET with `api_key` as a query param. Response envelopes are
inconsistent across the API (some use `status`, others `success`), so we
normalize everything into either a dict (success) or a raised VNHOTPError.

Network is hardened with retries + backoff so transient provider slowness or
rate-limiting does not crash a handler with a raw httpx exception.
"""
import asyncio
import httpx

from core.config import config


class VNHOTPError(Exception):
    """Raised on ANY provider failure: business error OR network failure."""


class VNHOTP:
    def __init__(self, api_key: str, base: str, timeout: float = 20.0, retries: int = 3):
        self.api_key = api_key
        self.base = base
        self.timeout = timeout
        self.retries = retries
        self._client = httpx.AsyncClient(timeout=timeout, base_url=base)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, **params):
        params["api_key"] = self.api_key
        for attempt in range(self.retries):
            try:
                r = await self._client.get(path, params=params)
                try:
                    j = r.json()
                except Exception:
                    raise VNHOTPError(f"Bad response (HTTP {r.status_code})")
                return self._normalize(j)
            except httpx.HTTPError:
                # transient network/timeout error -> retry with backoff
                if attempt < self.retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                break
        raise VNHOTPError("Provider is temporarily unreachable. Please try again in a moment.")

    @staticmethod
    def _normalize(j):
        # TG available_countries returns a list: [true, {CODE: {...}}]
        if isinstance(j, list):
            return j[1] if len(j) > 1 else {}
        if isinstance(j, dict):
            ok = (j.get("status") == "success") or (j.get("success") is True)
            if ok:
                return j.get("data", j)
            raise VNHOTPError(j.get("message") or j.get("error") or "Request failed")
        raise VNHOTPError("Unexpected response")

    # ---- account ----
    async def check(self):
        return await self._get("/check")

    # ---- Telegram ----
    async def tg_countries(self):
        data = await self._get("/tg/available_countries")
        out = []
        for code, info in data.items():
            out.append({
                "code": info.get("code", code),
                "name": info.get("name", code),
                "qty": info.get("qty"),
                "price": info.get("price"),
            })
        out.sort(key=lambda x: x["name"].lower())
        return out

    async def tg_country_info(self, code: str):
        return await self._get("/tg/country_info", code=code)

    async def tg_place_order(self, code: str):
        return await self._get("/tg/place_order", code=code)

    async def tg_get_code(self, number: str):
        return await self._get("/tg/get_code", number=number)

    # ---- WhatsApp (server: wp | wp2) ----
    async def wp_countries(self, server: str = "wp"):
        data = await self._get(f"/{server}/available_countries")
        if isinstance(data, dict):
            # WP2 returns a dict keyed by country code (and sometimes a numeric
            # id too). Dedupe by name and prefer a 2-3 letter alpha code.
            out = {}
            for code, info in data.items():
                if not isinstance(info, dict):
                    continue
                name = info.get("name") or info.get("short_name") or str(code)
                c = str(info.get("code") or code)
                existing = out.get(name)
                if existing is None or (c.isalpha() and len(c) <= 3 and not existing["code"].isalpha()):
                    out[name] = {"code": c.upper(), "name": name,
                                 "price": None, "qty": info.get("count")}
            return list(out.values())
        return data

    async def wp_get_price(self, server: str, code: str):
        return await self._get(f"/{server}/get_price", country_code=code)

    async def wp_place_order(self, server: str, code: str):
        return await self._get(f"/{server}/place_order", country_code=code)

    async def wp_cancel_order(self, server: str, order_id: str):
        return await self._get(f"/{server}/cancel_order", order_id=order_id)

    async def wp_get_status(self, server: str, order_id: str):
        j = await self._get(f"/{server}/get_status", order_id=order_id)
        if isinstance(j, dict) and j.get("message"):
            return j["message"]
        return None


vnhotp = VNHOTP(config.API_KEY, config.API_BASE)
