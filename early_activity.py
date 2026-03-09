"""
КРОК 4: Early Activity Analysis — analyze first buyers and volume patterns.

Checks:
  - Unique buyer count >= threshold
  - No blacklisted buyers
  - Whitelist (smart money) buyers present (bonus)
  - Volume pattern looks organic (not just 2-3 big buys)
"""

from __future__ import annotations

import logging

from config import Config
from models import EarlyActivityResult
from api_clients.helius import HeliusClient
from api_clients.solana_rpc import SolanaRPC
from database import get_db

logger = logging.getLogger(__name__)


async def analyze_early_activity(
    token_mint: str, pool_address: str, cfg: Config
) -> EarlyActivityResult:
    """Analyze early trading activity on a new pool."""
    result = EarlyActivityResult()
    db = get_db()
    helius = HeliusClient(cfg.helius_api_key, cfg.rpc_http)

    try:
        # Get recent transactions for the pool
        txs = await helius.get_transactions(pool_address, limit=20)

        # Extract buyers and sellers
        buyers: set[str] = set()
        sellers: set[str] = set()
        buy_amounts: list[float] = []

        for tx in txs:
            fee_payer = tx.get("feePayer", "")
            if not fee_payer:
                continue

            token_transfers = tx.get("tokenTransfers", [])
            native_transfers = tx.get("nativeTransfers", [])

            sol_spent = 0.0
            sol_received = 0.0
            for nt in native_transfers:
                if nt.get("fromUserAccount") == fee_payer:
                    sol_spent += (nt.get("amount", 0) / 1_000_000_000)
                if nt.get("toUserAccount") == fee_payer:
                    sol_received += (nt.get("amount", 0) / 1_000_000_000)

            if sol_spent > sol_received and fee_payer:
                buyers.add(fee_payer)
                buy_amounts.append(sol_spent - sol_received)
            elif sol_received > sol_spent and fee_payer:
                sellers.add(fee_payer)

        result.unique_buyers = len(buyers)

        # Check minimum unique buyers
        if result.unique_buyers < cfg.min_unique_buyers:
            result.reason = (
                f"Only {result.unique_buyers} unique buyers < {cfg.min_unique_buyers}"
            )
            return result

        # Check for early sells (bearish signal)
        if sellers and len(sellers) >= len(buyers):
            result.reason = (
                f"Too many early sellers: {len(sellers)} sellers vs {len(buyers)} buyers"
            )
            return result

        # Check blacklisted buyers
        for buyer in buyers:
            if await db.is_blacklisted(buyer):
                result.has_blacklisted_buyer = True
                result.reason = f"Blacklisted buyer detected: {buyer[:12]}"
                return result

        # Check whitelist buyers (smart money)
        whitelist = await db.get_whitelist()
        result.whitelist_buyers = [b for b in buyers if b in whitelist]

        # Analyze volume pattern
        if buy_amounts:
            total = sum(buy_amounts)
            max_buy = max(buy_amounts)
            max_pct = (max_buy / total * 100) if total > 0 else 0

            if max_pct > cfg.max_single_buyer_pct:
                result.volume_pattern = "concentrated"
                result.reason = (
                    f"Single buyer dominance: {max_pct:.0f}% > {cfg.max_single_buyer_pct}%"
                )
                return result
            elif len(buy_amounts) >= 3 and max_pct < 30:
                result.volume_pattern = "organic"
            else:
                result.volume_pattern = "mixed"

        result.passed = True
        result.reason = (
            f"buyers={result.unique_buyers} pattern={result.volume_pattern} "
            f"smart_money={len(result.whitelist_buyers)}"
        )
    except Exception as e:
        logger.warning("Early activity analysis failed: %s", e)
        result.reason = f"Analysis error: {e}"
        result.passed = True  # Don't block on analysis errors
    finally:
        await helius.close()

    return result
