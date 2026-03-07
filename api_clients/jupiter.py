from __future__ import annotations

import logging

import aiohttp

from utils import RateLimiter

logger = logging.getLogger(__name__)

SOL_MINT = "So11111111111111111111111111111111111111112"


class JupiterClient:
    def __init__(
        self,
        api_key: str = "",
        quote_url: str = "https://api.jup.ag/swap/v1/quote",
        swap_url: str = "https://api.jup.ag/swap/v1/swap",
    ) -> None:
        self._api_key = api_key
        self._quote_url = quote_url
        self._swap_url = swap_url
        self._limiter = RateLimiter(rate=10.0, burst=3)
        self._session: aiohttp.ClientSession | None = None

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self._api_key:
            h["x-api-key"] = self._api_key
        return h

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 500,
    ) -> dict | None:
        """Get a swap quote from Jupiter."""
        await self._limiter.acquire()
        session = await self._ensure_session()
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": str(slippage_bps),
        }
        try:
            async with session.get(
                self._quote_url, params=params,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Jupiter quote HTTP %d", resp.status)
                    return None
                return await resp.json()
        except Exception as e:
            logger.warning("Jupiter quote error: %s", e)
            return None

    async def build_swap_tx(
        self,
        quote: dict,
        user_pubkey: str,
        wrap_unwrap_sol: bool = True,
    ) -> dict | None:
        """Build the swap transaction from a quote."""
        await self._limiter.acquire()
        session = await self._ensure_session()
        payload = {
            "quoteResponse": quote,
            "userPublicKey": user_pubkey,
            "wrapAndUnwrapSol": wrap_unwrap_sol,
        }
        try:
            async with session.post(
                self._swap_url, json=payload,
                headers={**self._headers(), "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Jupiter swap HTTP %d", resp.status)
                    return None
                return await resp.json()
        except Exception as e:
            logger.warning("Jupiter swap error: %s", e)
            return None

    async def simulate_buy_sell(
        self, token_mint: str, amount_lamports: int, slippage_bps: int = 500
    ) -> dict:
        """Simulate buy SOL->token then sell token->SOL. Returns sell_ratio."""
        buy_quote = await self.get_quote(
            SOL_MINT, token_mint, amount_lamports, slippage_bps
        )
        if not buy_quote or not buy_quote.get("outAmount"):
            return {"sell_ratio": 0.0, "error": "buy_quote_failed"}

        tokens_received = buy_quote["outAmount"]
        if int(tokens_received) == 0:
            return {"sell_ratio": 0.0, "error": "buy_returns_zero"}

        sell_quote = await self.get_quote(
            token_mint, SOL_MINT, int(tokens_received), slippage_bps
        )
        if not sell_quote or not sell_quote.get("outAmount"):
            return {"sell_ratio": 0.0, "error": "sell_blocked"}

        sol_returned = int(sell_quote["outAmount"])
        return {
            "sell_ratio": sol_returned / amount_lamports,
            "error": None,
        }
