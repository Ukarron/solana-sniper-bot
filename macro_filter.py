"""
КРОК 0: Macro Filter — market condition assessment.

Runs hourly in background. Checks:
  - BTC dominance trend (falling = alt season = bullish)
  - Solana TVL growth (>60%/month = bullish)
  - SOL/USD trend (uptrend = bullish)

Output: risk_multiplier (0.5x / 1.0x / 1.5x) applied to buy amount.
"""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

from config import Config
from models import MacroState

logger = logging.getLogger(__name__)


class MacroFilter:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.state: MacroState | None = None

    def get_risk_multiplier(self) -> float:
        if self.state is None:
            return 1.0
        return self.state.risk_multiplier

    async def run_loop(self) -> None:
        """Background loop: update macro state every interval."""
        while True:
            try:
                await self.update()
            except Exception as e:
                logger.warning("Macro filter update failed: %s", e)
            await asyncio.sleep(self.cfg.macro_check_interval_sec)

    async def update(self) -> None:
        async with aiohttp.ClientSession() as session:
            btc_dom_falling = await self._check_btc_dominance(session)
            tvl_growth = await self._check_solana_tvl(session)
            sol_uptrend = await self._check_sol_trend(session)

        if btc_dom_falling and tvl_growth > self.cfg.tvl_growth_threshold_pct and sol_uptrend:
            multiplier = self.cfg.macro_risk_multiplier_bull
        elif not btc_dom_falling and tvl_growth < 0 and not sol_uptrend:
            multiplier = self.cfg.macro_risk_multiplier_bear
        else:
            multiplier = 1.0

        self.state = MacroState(
            btc_dominance_falling=btc_dom_falling,
            solana_tvl_growth_pct=tvl_growth,
            sol_uptrend=sol_uptrend,
            risk_multiplier=multiplier,
        )
        logger.info(
            "Macro update: btc_dom_falling=%s tvl_growth=%.1f%% sol_up=%s → multiplier=%.1fx",
            btc_dom_falling, tvl_growth, sol_uptrend, multiplier,
        )

    async def _check_btc_dominance(self, session: aiohttp.ClientSession) -> bool:
        """CoinGecko: is BTC dominance falling? (alt season signal)"""
        try:
            async with session.get(
                "https://api.coingecko.com/api/v3/global",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                btc_dom = data.get("data", {}).get("market_cap_percentage", {}).get("btc", 50)
                # Simple heuristic: BTC dom < 50% suggests alt season
                return btc_dom < 50
        except Exception:
            return False

    async def _check_solana_tvl(self, session: aiohttp.ClientSession) -> float:
        """DefiLlama: Solana TVL growth % over 30 days."""
        try:
            async with session.get(
                "https://api.llama.fi/v2/historicalChainTvl/Solana",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return 0.0
                data = await resp.json()
                if len(data) < 30:
                    return 0.0
                current = data[-1].get("tvl", 0)
                month_ago = data[-30].get("tvl", 0)
                if month_ago <= 0:
                    return 0.0
                return ((current - month_ago) / month_ago) * 100
        except Exception:
            return 0.0

    async def _check_sol_trend(self, session: aiohttp.ClientSession) -> bool:
        """CoinGecko: is SOL in an uptrend?"""
        try:
            async with session.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "solana", "vs_currencies": "usd"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                sol_price = data.get("solana", {}).get("usd", 0)
                # Simple heuristic: SOL > $100 suggests healthy market
                return sol_price > 100
        except Exception:
            return False
