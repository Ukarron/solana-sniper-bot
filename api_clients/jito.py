from __future__ import annotations

import logging

import aiohttp
import base58

from utils import RateLimiter

logger = logging.getLogger(__name__)


class JitoClient:
    """Send transactions through Jito Block Engine for anti-sandwich protection."""

    def __init__(
        self,
        endpoint: str = "https://mainnet.block-engine.jito.wtf",
    ) -> None:
        self._endpoint = endpoint
        self._limiter = RateLimiter(rate=5.0, burst=2)
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def send_transaction(self, signed_tx_bytes: bytes) -> str:
        """Send a signed transaction via Jito (base58 encoded)."""
        await self._limiter.acquire()
        session = await self._ensure_session()
        tx_b58 = base58.b58encode(signed_tx_bytes).decode()

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [tx_b58, {"encoding": "base58"}],
        }
        url = f"{self._endpoint}/api/v1/transactions"

        try:
            async with session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                result = await resp.json()
                if "result" in result:
                    sig = result["result"]
                    logger.info("Jito TX sent: %s", sig[:20])
                    return sig
                error = result.get("error", "unknown")
                raise RuntimeError(f"Jito error: {error}")
        except aiohttp.ClientError as e:
            logger.error("Jito send failed: %s", e)
            raise

    async def get_tip_accounts(self) -> list[str]:
        """Get current Jito tip accounts."""
        session = await self._ensure_session()
        url = f"{self._endpoint}/api/v1/bundles"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTipAccounts",
            "params": [],
        }
        try:
            async with session.post(
                url, json=payload, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                data = await resp.json()
                return data.get("result", [])
        except Exception as e:
            logger.warning("Failed to get Jito tip accounts: %s", e)
            return []
