"""
Telegram Notifier — singleton pattern from arbitrage-bot.

Non-blocking: messages are queued and sent with rate-limiting.
"""

from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

from config import Config

log = logging.getLogger(__name__)


class TelegramNotifier:
    _MIN_INTERVAL = 2.0

    def __init__(self, cfg: Config | None = None) -> None:
        token = cfg.telegram_bot_token if cfg else ""
        chat_id = cfg.telegram_chat_id if cfg else ""
        self.enabled = bool(token and chat_id)
        self._token = token
        self._chat_id = chat_id
        self._url = f"https://api.telegram.org/bot{token}/sendMessage" if token else ""
        self._session: aiohttp.ClientSession | None = None
        self._last_send: float = 0.0
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self._sender_task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.enabled:
            log.info("Telegram notifications disabled")
            return
        self._session = aiohttp.ClientSession()
        self._sender_task = asyncio.create_task(self._sender_loop(), name="tg-sender")
        log.info("Telegram notifier started")

    async def stop(self) -> None:
        if self._sender_task:
            self._sender_task.cancel()
        if self._session:
            await self._session.close()

    _PREFIX = "<b>[SNIPER BOT]</b> "

    async def send_direct(self, text: str) -> None:
        """Send immediately bypassing queue (for shutdown messages)."""
        if not self.enabled:
            return
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        await self._send(self._PREFIX + text)
        await asyncio.sleep(0.5)

    def alert(self, message: str) -> None:
        """Non-blocking: queue a message for sending."""
        if not self.enabled:
            return
        try:
            self._queue.put_nowait(self._PREFIX + message)
        except asyncio.QueueFull:
            pass

    async def _sender_loop(self) -> None:
        while True:
            try:
                msg = await self._queue.get()
                elapsed = time.time() - self._last_send
                if elapsed < self._MIN_INTERVAL:
                    await asyncio.sleep(self._MIN_INTERVAL - elapsed)
                await self._send(msg)
                self._last_send = time.time()
            except asyncio.CancelledError:
                return
            except Exception:
                log.warning("Telegram send error", exc_info=True)

    async def _send(self, text: str) -> None:
        if not self._session or not self._url:
            return
        try:
            async with self._session.post(
                self._url,
                json={
                    "chat_id": self._chat_id,
                    "text": text[:4096],
                    "parse_mode": "HTML",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.warning("Telegram HTTP %d: %s", resp.status, body[:200])
        except Exception:
            log.warning("Telegram send failed", exc_info=True)


_instance: TelegramNotifier | None = None


def get_notifier() -> TelegramNotifier:
    global _instance
    if _instance is None:
        from config import Config
        cfg = Config.from_env()
        _instance = TelegramNotifier(cfg)
    return _instance
