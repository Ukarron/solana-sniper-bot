from __future__ import annotations

import logging
from typing import Any

import aiohttp

from utils import RateLimiter, retry_async

logger = logging.getLogger(__name__)


class SolanaRPC:
    """Async wrapper around Solana JSON-RPC."""

    def __init__(self, http_url: str, rate: float = 25.0) -> None:
        self._url = http_url
        self._limiter = RateLimiter(rate, burst=5)
        self._session: aiohttp.ClientSession | None = None
        self._req_id = 0

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _call(self, method: str, params: list | None = None) -> Any:
        await self._limiter.acquire()
        session = await self._ensure_session()
        self._req_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params or [],
        }
        async with session.post(
            self._url, json=payload, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            data = await resp.json()
            if "error" in data:
                raise RuntimeError(f"RPC error: {data['error']}")
            return data.get("result")

    async def get_account_info_json_parsed(self, address: str) -> dict | None:
        result = await self._call(
            "getAccountInfo",
            [address, {"encoding": "jsonParsed"}],
        )
        return result.get("value") if result else None

    async def get_token_largest_accounts(self, mint: str) -> list[dict]:
        result = await self._call("getTokenLargestAccounts", [mint])
        return result.get("value", []) if result else []

    async def get_transaction(self, signature: str, commitment: str = "confirmed") -> dict | None:
        return await self._call(
            "getTransaction",
            [signature, {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
                "commitment": commitment,
            }],
        )

    async def get_signatures_for_address(
        self, address: str, limit: int = 20
    ) -> list[dict]:
        result = await self._call(
            "getSignaturesForAddress",
            [address, {"limit": limit}],
        )
        return result or []

    async def get_balance(self, address: str) -> float:
        """Get SOL balance in SOL (not lamports)."""
        result = await self._call("getBalance", [address])
        if result and "value" in result:
            return result["value"] / 1_000_000_000
        return 0.0

    async def get_slot(self) -> int:
        return await self._call("getSlot") or 0

    async def is_responsive(self) -> bool:
        try:
            await self.get_slot()
            return True
        except Exception:
            return False
