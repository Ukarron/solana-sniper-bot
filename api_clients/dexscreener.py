from __future__ import annotations

import logging

import aiohttp

from utils import RateLimiter

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dexscreener.com"


class DexScreenerClient:
    def __init__(self) -> None:
        self._limiter = RateLimiter(rate=5.0, burst=3)
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_token_info(self, mint: str) -> dict | None:
        """Get token pair data from DexScreener."""
        await self._limiter.acquire()
        session = await self._ensure_session()
        url = f"{BASE_URL}/latest/dex/tokens/{mint}"

        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                pairs = data.get("pairs", [])
                return pairs[0] if pairs else None
        except Exception as e:
            logger.warning("DexScreener error for %s: %s", mint[:12], e)
            return None

    async def get_socials(self, mint: str) -> dict:
        """Extract social links from DexScreener data."""
        pair = await self.get_token_info(mint)
        if not pair:
            return {}

        info = pair.get("info", {})
        socials = {s.get("type", ""): s.get("url", "") for s in info.get("socials", [])}
        if info.get("websites"):
            socials["website"] = info["websites"][0].get("url", "")

        return socials

    async def is_boosted(self, mint: str) -> bool:
        """Check if token appears in DexScreener boosted list."""
        pair = await self.get_token_info(mint)
        if not pair:
            return False
        return pair.get("boosts", {}).get("active", 0) > 0

    async def get_price_usd(self, mint: str) -> float | None:
        """Get current token price in USD."""
        pair = await self.get_token_info(mint)
        if not pair:
            return None
        try:
            return float(pair.get("priceUsd", 0))
        except (ValueError, TypeError):
            return None

    async def get_price_native(self, mint: str) -> float | None:
        """Get current token price in native currency (SOL for Solana)."""
        pair = await self.get_token_info(mint)
        if not pair:
            return None
        try:
            return float(pair.get("priceNative", 0))
        except (ValueError, TypeError):
            return None
