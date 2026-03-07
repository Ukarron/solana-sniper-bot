from __future__ import annotations

import logging

import aiohttp

from utils import RateLimiter

logger = logging.getLogger(__name__)


class HeliusClient:
    def __init__(self, api_key: str, rpc_url: str = "") -> None:
        self._api_key = api_key
        self._rpc_url = rpc_url or f"https://mainnet.helius-rpc.com/?api-key={api_key}"
        self._api_url = f"https://api.helius.xyz"
        self._limiter = RateLimiter(rate=25.0, burst=5)
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_asset(self, mint: str) -> dict | None:
        """DAS API — get asset metadata (name, symbol, links, image)."""
        await self._limiter.acquire()
        session = await self._ensure_session()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAsset",
            "params": {"id": mint},
        }
        try:
            async with session.post(
                self._rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                return data.get("result")
        except Exception as e:
            logger.warning("Helius getAsset error for %s: %s", mint[:12], e)
            return None

    async def get_assets_by_creator(self, creator: str, limit: int = 50) -> list[dict]:
        """DAS API — get all assets created by a specific wallet."""
        await self._limiter.acquire()
        session = await self._ensure_session()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAssetsByCreator",
            "params": {
                "creatorAddress": creator,
                "onlyVerified": False,
                "limit": limit,
            },
        }
        try:
            async with session.post(
                self._rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                result = data.get("result", {})
                return result.get("items", [])
        except Exception as e:
            logger.warning("Helius getAssetsByCreator error: %s", e)
            return []

    async def get_transactions(
        self, address: str, tx_type: str = "", limit: int = 20
    ) -> list[dict]:
        """Enhanced transactions API."""
        await self._limiter.acquire()
        session = await self._ensure_session()
        url = f"{self._api_url}/v0/addresses/{address}/transactions"
        params = {"api-key": self._api_key, "limit": str(limit)}
        if tx_type:
            params["type"] = tx_type

        try:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return []
                return await resp.json()
        except Exception as e:
            logger.warning("Helius transactions error: %s", e)
            return []
