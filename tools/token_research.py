"""
Token Research Analysis Tool

Compare top-performing Solana tokens from March 2026 vs our trading results.
Identifies patterns that separate winners from losers to improve filter accuracy.

Usage:
  python tools/token_research.py                             # Top performers only
  python tools/token_research.py --db data/sniping_bot.db    # With our DB comparison

Environment (loaded from ../.env):
  HELIUS_API_KEY  - For on-chain analysis (deployer, holders)
  RPC_HTTP        - Solana RPC endpoint
"""

from __future__ import annotations

import asyncio
import argparse
import json
import os
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
RPC_HTTP = os.getenv("RPC_HTTP", "")

DEXSCREENER = "https://api.dexscreener.com"
RUGCHECK = "https://api.rugcheck.xyz/v1"

MARCH_START_MS = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
MARCH_END_MS = int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)

SEARCH_TERMS = [
    "pump", "moon", "pepe", "doge", "dog", "cat", "ai",
    "meme", "inu", "bonk", "trump", "elon", "sol", "baby",
    "king", "god", "alpha", "dragon", "ninja", "pixel",
    "chad", "based", "giga", "turbo", "rocket", "gem",
    "pumpswap", "raydium",
]


@dataclass
class TokenData:
    address: str
    symbol: str = ""
    name: str = ""
    pair_address: str = ""
    created_at_ms: int = 0
    created_date: str = ""
    price_usd: float = 0
    price_change_5m: float = 0
    price_change_1h: float = 0
    price_change_6h: float = 0
    price_change_24h: float = 0
    volume_24h_usd: float = 0
    volume_6h_usd: float = 0
    liquidity_usd: float = 0
    fdv: float = 0
    market_cap: float = 0
    buys_24h: int = 0
    sells_24h: int = 0
    buy_sell_ratio: float = 0
    has_website: bool = False
    has_twitter: bool = False
    has_telegram: bool = False
    is_boosted: bool = False
    boost_count: int = 0
    social_count: int = 0
    # on-chain enrichment
    rugcheck_score: int = -1
    deployer_age_days: int = -1
    deployer_token_count: int = -1
    top_holder_pct: float = -1
    lp_locked: bool = False
    # classification
    dataset: str = ""
    pnl_sol: float = 0


# ━━━━━━━━━━━━━━━━━━ DexScreener API ━━━━━━━━━━━━━━━━━━

async def _dex_get(session: aiohttp.ClientSession, path: str) -> dict | list | None:
    url = f"{DEXSCREENER}{path}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
            if r.status == 429:
                await asyncio.sleep(2)
                return None
            if r.status != 200:
                return None
            return await r.json()
    except Exception:
        return None


async def fetch_profiles(session: aiohttp.ClientSession) -> list[str]:
    """Get token addresses from latest DexScreener profiles."""
    data = await _dex_get(session, "/token-profiles/latest/v1")
    if not data or not isinstance(data, list):
        return []
    return [
        t["tokenAddress"] for t in data
        if t.get("chainId") == "solana" and t.get("tokenAddress")
    ]


async def fetch_boosts(session: aiohttp.ClientSession) -> list[str]:
    """Get token addresses from top boosted tokens."""
    data = await _dex_get(session, "/token-boosts/top/v1")
    if not data or not isinstance(data, list):
        return []
    return [
        t["tokenAddress"] for t in data
        if t.get("chainId") == "solana" and t.get("tokenAddress")
    ]


async def search_pairs(session: aiohttp.ClientSession, query: str) -> list[dict]:
    """Search DexScreener for Solana pairs."""
    data = await _dex_get(session, f"/latest/dex/search?q={query}")
    if not data or not isinstance(data, dict):
        return []
    pairs = data.get("pairs") or []
    return [p for p in pairs if p.get("chainId") == "solana"]


async def get_token_pairs(
    session: aiohttp.ClientSession, addresses: list[str],
) -> list[dict]:
    """Batch-fetch pair data for up to 30 tokens at once."""
    if not addresses:
        return []
    chunk = ",".join(addresses[:30])
    data = await _dex_get(session, f"/tokens/v1/solana/{chunk}")
    if not data or not isinstance(data, list):
        return []
    return data


def _parse_pair(pair: dict) -> TokenData | None:
    """Parse a DexScreener pair into TokenData."""
    base = pair.get("baseToken", {})
    addr = base.get("address", "")
    if not addr:
        return None

    created = pair.get("pairCreatedAt", 0)
    pc = pair.get("priceChange") or {}
    vol = pair.get("volume") or {}
    liq = pair.get("liquidity") or {}
    txns = pair.get("txns") or {}
    t24 = txns.get("h24") or {}
    info = pair.get("info") or {}
    websites = info.get("websites") or []
    socials = info.get("socials") or []
    boosts = pair.get("boosts") or {}

    buys = int(t24.get("buys", 0))
    sells = int(t24.get("sells", 0))

    social_types = {s.get("type", "").lower() for s in socials}
    has_tw = "twitter" in social_types or "x" in social_types
    has_tg = "telegram" in social_types

    social_count = int(bool(websites)) + int(has_tw) + int(has_tg)

    return TokenData(
        address=addr,
        symbol=base.get("symbol", ""),
        name=base.get("name", ""),
        pair_address=pair.get("pairAddress", ""),
        created_at_ms=created,
        created_date=datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if created else "",
        price_usd=float(pair.get("priceUsd") or 0),
        price_change_5m=float(pc.get("m5") or 0),
        price_change_1h=float(pc.get("h1") or 0),
        price_change_6h=float(pc.get("h6") or 0),
        price_change_24h=float(pc.get("h24") or 0),
        volume_24h_usd=float(vol.get("h24") or 0),
        volume_6h_usd=float(vol.get("h6") or 0),
        liquidity_usd=float(liq.get("usd") or 0),
        fdv=float(pair.get("fdv") or 0),
        market_cap=float(pair.get("marketCap") or 0),
        buys_24h=buys,
        sells_24h=sells,
        buy_sell_ratio=round(buys / sells, 2) if sells > 0 else 0,
        has_website=bool(websites),
        has_twitter=has_tw,
        has_telegram=has_tg,
        is_boosted=boosts.get("active", 0) > 0,
        boost_count=boosts.get("active", 0),
        social_count=social_count,
    )


# ━━━━━━━━━━━━━━━━━━ On-chain enrichment ━━━━━━━━━━━━━━

async def enrich_rugcheck(
    session: aiohttp.ClientSession, token: TokenData,
) -> None:
    """Fetch Rugcheck score for a token."""
    url = f"{RUGCHECK}/tokens/{token.address}/report/summary"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
            if r.status != 200:
                return
            data = await r.json()
            token.rugcheck_score = data.get("score", -1)
    except Exception:
        pass


async def enrich_deployer(
    session: aiohttp.ClientSession, token: TokenData,
) -> None:
    """Fetch deployer info via Helius DAS API."""
    if not HELIUS_API_KEY:
        return
    rpc = RPC_HTTP or f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

    # Get mint authority (deployer)
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getAccountInfo",
        "params": [token.address, {"encoding": "jsonParsed"}],
    }
    try:
        async with session.post(rpc, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            value = data.get("result", {}).get("value")
            if not value:
                return
            parsed = value.get("data", {})
            if isinstance(parsed, dict):
                info = parsed.get("parsed", {}).get("info", {})
                deployer = info.get("mintAuthority", "")
            else:
                return

        if not deployer:
            return

        # Deployer age: get oldest tx
        payload2 = {
            "jsonrpc": "2.0", "id": 2,
            "method": "getSignaturesForAddress",
            "params": [deployer, {"limit": 1}],
        }
        async with session.post(rpc, json=payload2, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data2 = await r.json()
            sigs = data2.get("result", [])
            if sigs:
                bt = sigs[-1].get("blockTime", 0)
                if bt:
                    age_sec = time.time() - bt
                    token.deployer_age_days = max(0, int(age_sec / 86400))

        # Deployer token count via DAS
        payload3 = {
            "jsonrpc": "2.0", "id": 3,
            "method": "getAssetsByCreator",
            "params": {"creatorAddress": deployer, "onlyVerified": False, "limit": 50},
        }
        async with session.post(rpc, json=payload3, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data3 = await r.json()
            items = data3.get("result", {}).get("items", [])
            token.deployer_token_count = len(items)
    except Exception:
        pass


async def enrich_top_holder(
    session: aiohttp.ClientSession, token: TokenData,
) -> None:
    """Fetch top holder percentage."""
    rpc = RPC_HTTP
    if not rpc:
        return
    try:
        # Get total supply
        payload1 = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getAccountInfo",
            "params": [token.address, {"encoding": "jsonParsed"}],
        }
        async with session.post(rpc, json=payload1, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            value = data.get("result", {}).get("value")
            if not value:
                return
            parsed = value.get("data", {})
            if isinstance(parsed, dict):
                supply_str = parsed.get("parsed", {}).get("info", {}).get("supply", "0")
            else:
                return
        total_supply = int(supply_str) if supply_str else 0
        if total_supply == 0:
            return

        # Get largest accounts
        payload2 = {
            "jsonrpc": "2.0", "id": 2,
            "method": "getTokenLargestAccounts",
            "params": [token.address],
        }
        async with session.post(rpc, json=payload2, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data2 = await r.json()
            holders = data2.get("result", {}).get("value", [])
            if holders:
                top_amount = int(holders[0].get("amount", "0"))
                token.top_holder_pct = round((top_amount / total_supply) * 100, 1)
    except Exception:
        pass


# ━━━━━━━━━━━━━━━━━━ Our Database ━━━━━━━━━━━━━━━━━━━━━

def load_our_trades(db_path: str) -> tuple[list[TokenData], list[TokenData]]:
    """Load our traded tokens from SQLite, split into winners and losers."""
    winners, losers = [], []
    if not os.path.exists(db_path):
        print(f"  DB not found: {db_path}")
        return winners, losers

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT p.token_mint, p.token_symbol, p.entry_amount_sol, p.pnl_sol,
                   p.status, p.exit_reason, p.opened_at, p.closed_at,
                   d.initial_liquidity, d.rugcheck_score, d.deployer_age_days,
                   d.deployer_token_count, d.top_holder_pct, d.legitimacy_score,
                   d.unique_buyers, d.has_whitelist_buyer
            FROM positions p
            LEFT JOIN detected_pools d ON p.pool_id = d.id
            WHERE p.status = 'closed'
            ORDER BY p.closed_at DESC
        """).fetchall()

        for row in rows:
            pnl = row["pnl_sol"] or 0
            t = TokenData(
                address=row["token_mint"] or "",
                symbol=row["token_symbol"] or "",
                pnl_sol=pnl,
                rugcheck_score=row["rugcheck_score"] or -1,
                deployer_age_days=row["deployer_age_days"] or -1,
                deployer_token_count=row["deployer_token_count"] or -1,
                top_holder_pct=row["top_holder_pct"] or -1,
                liquidity_usd=float(row["initial_liquidity"] or 0) * 140,  # rough SOL->USD
            )
            if pnl > 0:
                t.dataset = "our_winner"
                winners.append(t)
            else:
                t.dataset = "our_loser"
                losers.append(t)
    finally:
        conn.close()

    return winners, losers


# ━━━━━━━━━━━━━━━━━━ Discovery Pipeline ━━━━━━━━━━━━━━━

async def discover_tokens(session: aiohttp.ClientSession) -> dict[str, TokenData]:
    """Discover top Solana tokens created in March 2026."""
    tokens: dict[str, TokenData] = {}
    addresses_to_fetch: set[str] = set()

    print("\n[1/5] Fetching DexScreener profiles...")
    profile_addrs = await fetch_profiles(session)
    addresses_to_fetch.update(profile_addrs)
    print(f"  Found {len(profile_addrs)} profiled Solana tokens")
    await asyncio.sleep(0.5)

    print("[2/5] Fetching DexScreener boosts...")
    boost_addrs = await fetch_boosts(session)
    addresses_to_fetch.update(boost_addrs)
    print(f"  Found {len(boost_addrs)} boosted Solana tokens")
    await asyncio.sleep(0.5)

    print(f"[3/5] Searching DexScreener ({len(SEARCH_TERMS)} terms)...")
    for i, term in enumerate(SEARCH_TERMS):
        pairs = await search_pairs(session, term)
        for pair in pairs:
            parsed = _parse_pair(pair)
            if parsed and parsed.address not in tokens:
                tokens[parsed.address] = parsed
        if (i + 1) % 5 == 0:
            print(f"  Searched {i + 1}/{len(SEARCH_TERMS)}, unique tokens: {len(tokens)}")
        await asyncio.sleep(1.1)  # respect rate limit

    # Fetch pair data for addresses found via profiles/boosts (not yet in tokens)
    missing = [a for a in addresses_to_fetch if a not in tokens]
    print(f"[4/5] Fetching pair data for {len(missing)} additional tokens...")
    for i in range(0, len(missing), 30):
        chunk = missing[i:i + 30]
        pairs = await get_token_pairs(session, chunk)
        for pair in pairs:
            parsed = _parse_pair(pair)
            if parsed and parsed.address not in tokens:
                tokens[parsed.address] = parsed
        await asyncio.sleep(1.1)

    # Filter for March 2026 creation
    total_before = len(tokens)
    march_tokens = {
        addr: t for addr, t in tokens.items()
        if MARCH_START_MS <= t.created_at_ms < MARCH_END_MS
    }
    print(f"[5/5] Filtered: {total_before} total -> {len(march_tokens)} created in March 2026")

    # Sort by volume (best proxy for success)
    sorted_tokens = sorted(march_tokens.values(), key=lambda t: t.volume_24h_usd, reverse=True)
    top = {}
    for t in sorted_tokens[:50]:
        t.dataset = "top_performer"
        top[t.address] = t
    print(f"  Selected top {len(top)} by 24h volume")

    return top


async def enrich_tokens(
    session: aiohttp.ClientSession, tokens: list[TokenData],
) -> None:
    """Enrich tokens with on-chain data (Rugcheck + deployer + holders)."""
    total = len(tokens)
    print(f"\nEnriching {total} tokens with on-chain data...")

    for i, token in enumerate(tokens):
        tasks = [enrich_rugcheck(session, token)]
        if HELIUS_API_KEY:
            tasks.append(enrich_deployer(session, token))
            tasks.append(enrich_top_holder(session, token))
        await asyncio.gather(*tasks)

        if (i + 1) % 10 == 0 or i == total - 1:
            print(f"  Enriched {i + 1}/{total}")
        await asyncio.sleep(0.3)


# ━━━━━━━━━━━━━━━━━━ Reporting ━━━━━━━━━━━━━━━━━━━━━━━━

def _safe_median(values: list[float]) -> float:
    clean = [v for v in values if v is not None and v >= 0]
    return round(statistics.median(clean), 2) if clean else 0


def _safe_mean(values: list[float]) -> float:
    clean = [v for v in values if v is not None and v >= 0]
    return round(statistics.mean(clean), 2) if clean else 0


def _pct_true(values: list[bool]) -> str:
    if not values:
        return "N/A"
    return f"{sum(values) / len(values) * 100:.0f}%"


def print_token_table(title: str, tokens: list[TokenData]) -> None:
    """Print a formatted table of tokens."""
    if not tokens:
        print(f"\n{'=' * 60}\n{title}: (no data)\n{'=' * 60}")
        return

    print(f"\n{'=' * 120}")
    print(f"  {title} ({len(tokens)} tokens)")
    print(f"{'=' * 120}")
    header = f"{'#':>3} {'Symbol':<12} {'Created':<12} {'PrChg24h':>10} {'Vol24h':>12} {'Liq':>10} {'FDV':>12} {'B/S':>7} {'Soc':>4} {'Rug':>6} {'TopH%':>6}"
    if tokens[0].dataset.startswith("our"):
        header += f" {'PnL':>10}"
    print(header)
    print("-" * 120)

    for i, t in enumerate(tokens[:30]):
        row = (
            f"{i + 1:>3} "
            f"{t.symbol[:11]:<12} "
            f"{t.created_date:<12} "
            f"{t.price_change_24h:>+9.1f}% "
            f"${t.volume_24h_usd:>10,.0f} "
            f"${t.liquidity_usd:>8,.0f} "
            f"${t.fdv:>10,.0f} "
            f"{t.buy_sell_ratio:>6.1f} "
            f"{'W' if t.has_website else '.'}"
            f"{'T' if t.has_twitter else '.'}"
            f"{'G' if t.has_telegram else '.'} "
            f"{t.rugcheck_score:>5} " if t.rugcheck_score >= 0 else f"{'N/A':>6} "
        )
        row += f"{t.top_holder_pct:>5.1f}" if t.top_holder_pct >= 0 else f"{'N/A':>6}"
        if t.dataset.startswith("our"):
            row += f" {t.pnl_sol:>+9.4f}"
        print(row)


def print_comparison(
    top: list[TokenData], winners: list[TokenData], losers: list[TokenData],
) -> None:
    """Print metric comparison across all three groups."""
    print(f"\n{'=' * 100}")
    print(f"  PATTERN ANALYSIS — What separates winners from losers?")
    print(f"{'=' * 100}")

    groups = [("Top Performers", top), ("Our Winners", winners), ("Our Losers", losers)]
    active_groups = [(name, grp) for name, grp in groups if grp]

    metrics = [
        ("Liquidity USD (median)", lambda t: t.liquidity_usd),
        ("Volume 24h USD (median)", lambda t: t.volume_24h_usd),
        ("FDV (median)", lambda t: t.fdv),
        ("Buy/Sell Ratio (median)", lambda t: t.buy_sell_ratio),
        ("Buys 24h (median)", lambda t: float(t.buys_24h)),
        ("Sells 24h (median)", lambda t: float(t.sells_24h)),
        ("Rugcheck Score (median)", lambda t: float(t.rugcheck_score)),
        ("Top Holder % (median)", lambda t: t.top_holder_pct),
        ("Deployer Age days (median)", lambda t: float(t.deployer_age_days)),
        ("Deployer Token Count (median)", lambda t: float(t.deployer_token_count)),
    ]
    bool_metrics = [
        ("Has Website", lambda t: t.has_website),
        ("Has Twitter/X", lambda t: t.has_twitter),
        ("Has Telegram", lambda t: t.has_telegram),
        ("Is Boosted", lambda t: t.is_boosted),
    ]

    # Header
    header = f"{'Metric':<35}"
    for name, _ in active_groups:
        header += f" {name:>16}"
    header += f" {'Signal':>10}"
    print(header)
    print("-" * 100)

    # Numeric metrics
    for metric_name, extractor in metrics:
        row = f"{metric_name:<35}"
        values_by_group = []
        for _, grp in active_groups:
            vals = [extractor(t) for t in grp]
            med = _safe_median(vals)
            values_by_group.append(med)
            if med >= 1_000_000:
                row += f" ${med / 1_000_000:>13.1f}M"
            elif med >= 1_000:
                row += f" ${med / 1_000:>13.1f}K"
            else:
                row += f" {med:>15.1f}"

        # Signal: compare top vs losers
        if len(values_by_group) >= 2:
            top_val = values_by_group[0]
            worst_val = values_by_group[-1]
            if worst_val > 0 and top_val / worst_val >= 2:
                row += f" {'*** HIGH':>10}"
            elif worst_val > 0 and top_val / worst_val >= 1.3:
                row += f" {'** MED':>10}"
            else:
                row += f" {'low':>10}"
        print(row)

    # Boolean metrics
    for metric_name, extractor in bool_metrics:
        row = f"{metric_name:<35}"
        pcts = []
        for _, grp in active_groups:
            vals = [extractor(t) for t in grp]
            pct = sum(vals) / len(vals) * 100 if vals else 0
            pcts.append(pct)
            row += f" {pct:>14.0f}%"
        if len(pcts) >= 2 and pcts[-1] < pcts[0] * 0.5:
            row += f" {'*** HIGH':>10}"
        elif len(pcts) >= 2 and pcts[-1] < pcts[0] * 0.7:
            row += f" {'** MED':>10}"
        else:
            row += f" {'low':>10}"
        print(row)


def print_recommendations(
    top: list[TokenData], winners: list[TokenData], losers: list[TokenData],
) -> None:
    """Print actionable filter recommendations."""
    print(f"\n{'=' * 80}")
    print(f"  RECOMMENDATIONS")
    print(f"{'=' * 80}")

    if not top:
        print("  Not enough data for recommendations.")
        return

    top_liq = _safe_median([t.liquidity_usd for t in top])
    top_vol = _safe_median([t.volume_24h_usd for t in top])
    top_bs = _safe_median([t.buy_sell_ratio for t in top])
    top_buys = _safe_median([float(t.buys_24h) for t in top])
    top_rug = _safe_median([float(t.rugcheck_score) for t in top if t.rugcheck_score >= 0])
    top_web_pct = sum(t.has_website for t in top) / len(top) * 100
    top_tw_pct = sum(t.has_twitter for t in top) / len(top) * 100

    loser_liq = _safe_median([t.liquidity_usd for t in losers]) if losers else 0
    loser_vol = _safe_median([t.volume_24h_usd for t in losers]) if losers else 0
    loser_bs = _safe_median([t.buy_sell_ratio for t in losers]) if losers else 0

    recs = []

    if top_liq > 0 and (loser_liq == 0 or top_liq > loser_liq * 1.5):
        threshold = int(top_liq * 0.3)
        recs.append(
            f"1. MIN LIQUIDITY: Increase min_liquidity_sol. "
            f"Top performers median: ${top_liq:,.0f}. "
            f"Suggested: raise to ~{threshold / 140:.0f} SOL (${threshold:,})."
        )

    if top_vol > 0:
        recs.append(
            f"2. NEW FILTER — MIN VOLUME: Top performers have ${top_vol:,.0f} 24h volume (median). "
            f"Add minimum volume check before buying."
        )

    if top_bs > 1.0:
        recs.append(
            f"3. NEW FILTER — BUY/SELL RATIO: Top performers have {top_bs:.1f}x more buys than sells. "
            f"Require buy/sell ratio > 1.2 before entry."
        )

    if top_buys > 50:
        recs.append(
            f"4. NEW FILTER — MIN TRANSACTIONS: Top performers have {top_buys:.0f} buys/24h (median). "
            f"Token needs organic trading activity before we enter."
        )

    if top_web_pct > 60:
        recs.append(
            f"5. TIGHTEN LEGITIMACY: {top_web_pct:.0f}% of top performers have a website. "
            f"Consider requiring website for entry."
        )

    if top_tw_pct > 60:
        recs.append(
            f"6. TIGHTEN LEGITIMACY: {top_tw_pct:.0f}% of top performers have Twitter/X. "
            f"Consider requiring Twitter for entry."
        )

    for r in recs:
        print(f"  {r}")

    if not recs:
        print("  Insufficient data contrast to generate recommendations.")


# ━━━━━━━━━━━━━━━━━━ Main ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def main() -> None:
    parser = argparse.ArgumentParser(description="Token Research Analysis")
    parser.add_argument("--db", type=str, default="", help="Path to bot SQLite database")
    parser.add_argument("--skip-enrich", action="store_true", help="Skip on-chain enrichment")
    parser.add_argument("--output", type=str, default="", help="Save raw data to JSON file")
    args = parser.parse_args()

    print("=" * 60)
    print("  Token Research Analysis Tool")
    print("  Comparing top March 2026 Solana tokens vs our trades")
    print("=" * 60)
    print(f"  HELIUS_API_KEY: {'set' if HELIUS_API_KEY else 'NOT SET (limited analysis)'}")
    print(f"  RPC_HTTP:       {'set' if RPC_HTTP else 'NOT SET'}")
    print(f"  DB path:        {args.db or '(none — top performers only)'}")

    async with aiohttp.ClientSession() as session:
        # Dataset A: Top performers
        top_tokens = await discover_tokens(session)

        if not args.skip_enrich:
            await enrich_tokens(session, list(top_tokens.values()))

        # Dataset B: Our trades
        our_winners, our_losers = [], []
        if args.db:
            print(f"\nLoading our trades from {args.db}...")
            our_winners, our_losers = load_our_trades(args.db)
            print(f"  Winners: {len(our_winners)}, Losers: {len(our_losers)}")

            if not args.skip_enrich:
                all_ours = [t for t in our_winners + our_losers if t.rugcheck_score < 0]
                if all_ours:
                    await enrich_tokens(session, all_ours)

    # Sort top performers by volume
    top_list = sorted(top_tokens.values(), key=lambda t: t.volume_24h_usd, reverse=True)
    winners_sorted = sorted(our_winners, key=lambda t: t.pnl_sol, reverse=True)
    losers_sorted = sorted(our_losers, key=lambda t: t.pnl_sol)

    # Display
    print_token_table("TOP PERFORMERS (March 2026 Solana tokens by 24h volume)", top_list)
    if our_winners:
        print_token_table("OUR WINNERS (closed with profit)", winners_sorted)
    if our_losers:
        print_token_table("OUR LOSERS (closed with loss)", losers_sorted)

    print_comparison(top_list, winners_sorted, losers_sorted)
    print_recommendations(top_list, winners_sorted, losers_sorted)

    # Save raw data
    if args.output:
        out = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "top_performers": [asdict(t) for t in top_list],
            "our_winners": [asdict(t) for t in winners_sorted],
            "our_losers": [asdict(t) for t in losers_sorted],
        }
        with open(args.output, "w") as f:
            json.dump(out, f, indent=2)
        print(f"\nRaw data saved to {args.output}")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
