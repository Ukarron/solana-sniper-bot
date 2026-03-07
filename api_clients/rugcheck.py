from __future__ import annotations

import logging

import aiohttp

from utils import RateLimiter

logger = logging.getLogger(__name__)

RUGCHECK_BASE = "https://api.rugcheck.xyz/v1"

CRITICAL_RISKS = {
    "Copycat token",
    "Mint authority enabled",
    "Freeze authority enabled",
    "Low liquidity",
    "Single holder majority",
}


class RugcheckClient:
    def __init__(self, base_url: str = RUGCHECK_BASE) -> None:
        self._base = base_url
        self._limiter = RateLimiter(rate=5.0, burst=3)
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_report(self, token_mint: str) -> dict:
        """Full token report. Returns dict with safe, score, risks, etc."""
        await self._limiter.acquire()
        session = await self._ensure_session()
        url = f"{self._base}/tokens/{token_mint}/report"

        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    logger.warning("Rugcheck HTTP %d for %s", resp.status, token_mint[:12])
                    return {"safe": None, "reason": "Rugcheck unavailable", "fallback": True}
                data = await resp.json()
        except Exception as e:
            logger.warning("Rugcheck error for %s: %s", token_mint[:12], e)
            return {"safe": None, "reason": str(e), "fallback": True}

        score = data.get("score", 9999)
        risks = data.get("risks", [])
        critical = [
            r for r in risks
            if r.get("name") in CRITICAL_RISKS or r.get("level") == "critical"
        ]

        if critical:
            return {
                "safe": False,
                "score": score,
                "risks": [r.get("name", "") for r in critical],
                "reason": f"Critical risks: {', '.join(r.get('name', '') for r in critical)}",
            }

        return {
            "safe": True,
            "score": score,
            "risks": [r.get("name", "") for r in risks],
            "top_holders": data.get("topHolders", []),
            "mint_authority": data.get("mintAuthority"),
            "freeze_authority": data.get("freezeAuthority"),
            "lp_locked": data.get("lpLocked"),
            "reason": "OK",
        }

    async def get_summary(self, token_mint: str) -> dict:
        """Quick summary — risk_level and basic flags."""
        await self._limiter.acquire()
        session = await self._ensure_session()
        url = f"{self._base}/tokens/{token_mint}/report/summary"

        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                if resp.status != 200:
                    return {"available": False}
                return await resp.json()
        except Exception:
            return {"available": False}
