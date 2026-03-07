from __future__ import annotations

import asyncio
import logging
import random
import time
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)

LAMPORTS_PER_SOL = 1_000_000_000


def sol_to_lamports(sol: float) -> int:
    return int(sol * LAMPORTS_PER_SOL)


def lamports_to_sol(lamports: int) -> float:
    return lamports / LAMPORTS_PER_SOL


async def retry_async(
    func: Callable,
    *args: Any,
    retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    **kwargs: Any,
) -> Any:
    """Retry an async function with exponential backoff + jitter."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                logger.warning(
                    "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                    func.__name__, attempt + 1, retries, e, delay,
                )
                await asyncio.sleep(delay)
    raise last_error


class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, rate: float, burst: int = 1) -> None:
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1


class Timer:
    """Context manager to measure elapsed time in milliseconds."""

    def __init__(self) -> None:
        self.elapsed_ms: int = 0
        self._start: float = 0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)
