"""Async client for GrizzlySMS API (SMS-Activate style API).

Docs: https://grizzlysms.com/docs
Base: https://api.grizzlysms.com/stubs/handler_api.php
Auth: ``api_key`` query param. Responses are plain TEXT (SMS-Activate dialect).
"""
import asyncio
import json

import httpx

from core.config import config


class GrizzlySMSError(Exception):
    """Raised on ANY provider failure (business or network)."""


class GrizzlySMS:
    BASE = "https://api.grizzlysms.com/stubs/handler_api.php"

    def __init__(self, api_key: str, timeout: float = 20.0, retries: int = 3):
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def _req(self, action: str, **params) -> str:
        if not self.api_key:
            raise GrizzlySMSError("GrizzlySMS API key is not configured.")
        params = {"api_key": self.api_key, "action": action, **params}
        for attempt in range(self.retries):
            try:
                r = await self._client.get(self.BASE, params=params)
                return (await r.aread()).decode("utf-8", "replace").strip()
            except httpx.HTTPError:
                if attempt < self.retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                break
        raise GrizzlySMSError("GrizzlySMS is temporarily unreachable. Please try again.")

    async def balance(self) -> float:
        t = await self._req("getBalance")
        if t.startswith("ACCESS_BALANCE:"):
            return float(t.split(":", 1)[1])
        raise GrizzlySMSError(t)

    async def services_list(self) -> list:
        t = await self._req("getServicesList")
        try:
            data = json.loads(t)
            return data.get("services", [])
        except Exception:
            raise GrizzlySMSError(t)

    async def countries(self) -> list:
        t = await self._req("getCountries")
        try:
            data = json.loads(t)
            if isinstance(data, dict):
                return list(data.values())
            return data
        except Exception:
            raise GrizzlySMSError(t)

    async def prices(self, service: str, country: str = None) -> dict:
        p = {}
        if country:
            p["country"] = country
        t = await self._req("getPrices", service=service, **p)
        try:
            return json.loads(t)
        except Exception:
            raise GrizzlySMSError(t)

    async def get_number(self, service: str, country: str) -> tuple:
        t = await self._req("getNumber", service=service, country=country)
        if t.startswith("ACCESS_NUMBER:"):
            parts = t.split(":")
            if len(parts) >= 3:
                return parts[1], parts[2]
        raise GrizzlySMSError(t)

    async def get_status(self, activation_id: str) -> str:
        return await self._req("getStatus", id=activation_id)

    async def set_status(self, activation_id: str, status: int) -> str:
        return await self._req("setStatus", id=activation_id, status=status)


grizzly = GrizzlySMS(config.GRIZZLY_API_KEY)
