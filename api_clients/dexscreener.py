from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

from utils import RateLimiter

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dexscreener.com"


@dataclass
class PairMetrics:
    """Structured market data from DexScreener for pre-buy validation."""
    available: bool = False
    price_change_m5: float = 0.0
    price_change_h1: float = 0.0
    buys_m5: int = 0
    sells_m5: int = 0
    buys_h1: int = 0
    sells_h1: int = 0
    volume_m5_usd: float = 0.0
    volume_h1_usd: float = 0.0
    volume_h24_usd: float = 0.0
    liquidity_usd: float = 0.0
    fdv: float = 0.0
    buy_sell_ratio_m5: float = 0.0

    @property
    def is_rising(self) -> bool:
        return self.price_change_m5 > 0

    @property
    def has_buy_pressure(self) -> bool:
        return self.buys_m5 > self.sells_m5

    @property
    def has_volume(self) -> bool:
        return self.volume_h1_usd > 0


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

    async def get_pair_metrics(self, mint: str) -> PairMetrics:
        """Fetch structured market metrics for pre-buy validation."""
        pair = await self.get_token_info(mint)
        if not pair:
            return PairMetrics(available=False)

        pc = pair.get("priceChange") or {}
        vol = pair.get("volume") or {}
        liq = pair.get("liquidity") or {}
        txns = pair.get("txns") or {}
        t_m5 = txns.get("m5") or {}
        t_h1 = txns.get("h1") or {}

        buys_m5 = int(t_m5.get("buys", 0))
        sells_m5 = int(t_m5.get("sells", 0))

        return PairMetrics(
            available=True,
            price_change_m5=float(pc.get("m5") or 0),
            price_change_h1=float(pc.get("h1") or 0),
            buys_m5=buys_m5,
            sells_m5=sells_m5,
            buys_h1=int(t_h1.get("buys", 0)),
            sells_h1=int(t_h1.get("sells", 0)),
            volume_m5_usd=float(vol.get("m5") or 0),
            volume_h1_usd=float(vol.get("h1") or 0),
            volume_h24_usd=float(vol.get("h24") or 0),
            liquidity_usd=float(liq.get("usd") or 0),
            fdv=float(pair.get("fdv") or 0),
            buy_sell_ratio_m5=round(buys_m5 / sells_m5, 2) if sells_m5 > 0 else 0.0,
        )

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
