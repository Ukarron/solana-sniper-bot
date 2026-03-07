"""
КРОК 3: Legitimacy Filter — social presence and metadata checks.

Scoring system (0-5 points):
  +1: Has website (not empty, returns HTTP 200, content > 500 chars)
  +1: Has Twitter/X account
  +1: Has Telegram group
  +1: Name doesn't copy an existing popular token
  +1: DexScreener boosted (bonus)

Threshold: >= min_legitimacy_score (default 2)
"""

from __future__ import annotations

import logging

import aiohttp

from config import Config
from models import LegitimacyResult
from api_clients.helius import HeliusClient
from api_clients.dexscreener import DexScreenerClient

logger = logging.getLogger(__name__)

COPYCAT_SYMBOLS = {
    "BTC", "ETH", "SOL", "USDC", "USDT", "BNB", "XRP", "ADA", "DOGE",
    "DOT", "AVAX", "MATIC", "LINK", "UNI", "ATOM", "LTC", "NEAR", "ARB",
    "OP", "APT", "SUI", "SEI", "TIA", "JUP", "JTO", "PYTH", "BONK", "WIF",
}


async def calculate_legitimacy_score(
    token_mint: str, cfg: Config
) -> LegitimacyResult:
    """Calculate legitimacy score from metadata and social presence."""
    result = LegitimacyResult()

    helius = HeliusClient(cfg.helius_api_key, cfg.rpc_http)
    dexscreener = DexScreenerClient()

    try:
        # Get metadata from Helius DAS API
        asset = await helius.get_asset(token_mint)
        metadata = _extract_metadata(asset) if asset else {}

        # Get socials from DexScreener
        socials = await dexscreener.get_socials(token_mint)

        token_name = metadata.get("name", "")
        token_symbol = metadata.get("symbol", "")
        website_url = metadata.get("website") or socials.get("website", "")
        twitter_url = metadata.get("twitter") or socials.get("twitter", "")
        telegram_url = metadata.get("telegram") or socials.get("telegram", "")

        # Check website (+1)
        if website_url:
            result.has_website = await _check_url_alive(
                website_url, cfg.website_min_content_length, cfg.website_check_timeout_sec
            )
            if result.has_website:
                result.score += 1

        # Check Twitter (+1)
        if twitter_url:
            result.has_twitter = await _check_url_alive(twitter_url, min_content=0)
            if result.has_twitter:
                result.score += 1

        # Check Telegram (+1)
        if telegram_url:
            result.has_telegram = await _check_url_alive(telegram_url, min_content=0)
            if result.has_telegram:
                result.score += 1

        # Check copycat (+1 if NOT copycat)
        if token_symbol.upper() in COPYCAT_SYMBOLS:
            result.is_copycat = True
        else:
            result.score += 1

        # DexScreener boost check (+1 bonus)
        try:
            result.is_dexscreener_boosted = await dexscreener.is_boosted(token_mint)
            if result.is_dexscreener_boosted:
                result.score += 1
        except Exception:
            pass

        result.reason = (
            f"score={result.score} web={result.has_website} tw={result.has_twitter} "
            f"tg={result.has_telegram} copy={result.is_copycat} boost={result.is_dexscreener_boosted}"
        )
    except Exception as e:
        logger.warning("Legitimacy check error for %s: %s", token_mint[:12], e)
        result.reason = f"Error: {e}"
    finally:
        await helius.close()
        await dexscreener.close()

    return result


def _extract_metadata(asset: dict) -> dict:
    """Extract metadata fields from Helius DAS getAsset response."""
    content = asset.get("content", {})
    meta = content.get("metadata", {})
    links = content.get("links", {})

    result = {
        "name": meta.get("name", ""),
        "symbol": meta.get("symbol", ""),
        "description": meta.get("description", ""),
        "website": links.get("external_url", ""),
    }

    # Check JSON metadata URI for social links
    json_uri = content.get("json_uri", "")
    if json_uri:
        result["json_uri"] = json_uri

    return result


async def _check_url_alive(
    url: str, min_content: int = 0, timeout: int = 5
) -> bool:
    """Check if a URL returns HTTP 200 and has sufficient content."""
    if not url or not url.startswith("http"):
        return False
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    return False
                if min_content > 0:
                    text = await resp.text()
                    return len(text) >= min_content
                return True
    except Exception:
        return False
