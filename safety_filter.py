"""
КРОК 2: Safety Filter — multi-layer security checks.

Strategy: Rugcheck API first, on-chain fallback, then honeypot v2 (multi-amount).
Rule: "worst result wins" — if ANY check fails, token is SKIP.
"""

from __future__ import annotations

import asyncio
import logging

from config import Config
from models import SafetyResult
from api_clients.rugcheck import RugcheckClient
from api_clients.jupiter import JupiterClient
from api_clients.solana_rpc import SolanaRPC

logger = logging.getLogger(__name__)

LEVER_KEYWORDS = ["lever", "leveraged", "x2l", "x3l", "x2s", "x3s"]

HONEYPOT_TEST_AMOUNTS = [
    10_000_000,      # 0.01 SOL
    100_000_000,     # 0.1 SOL
    1_000_000_000,   # 1.0 SOL
]


async def run_safety_checks(
    token_mint: str, pool_address: str, cfg: Config
) -> SafetyResult:
    """Combined safety filter: Rugcheck + on-chain fallback + honeypot v2."""
    result = SafetyResult(safe=False)

    # 1. Rugcheck API (primary)
    rugcheck = RugcheckClient(cfg.rugcheck_base_url)
    try:
        report = await rugcheck.get_report(token_mint)

        if report.get("fallback"):
            logger.info("Rugcheck unavailable, falling back to on-chain checks")
            onchain = await _onchain_safety_checks(token_mint, cfg)
            result = onchain
        elif not report.get("safe", False):
            result.reason = report.get("reason", "Rugcheck flagged")
            result.rugcheck_score = report.get("score", 9999)
            result.rugcheck_risks = report.get("risks", [])
            return result
        else:
            result.rugcheck_score = report.get("score", 0)
            result.rugcheck_risks = report.get("risks", [])
            result.mint_revoked = report.get("mint_authority") is None
            result.freeze_revoked = report.get("freeze_authority") is None
            result.lp_locked = bool(report.get("lp_locked"))

            # Check score threshold
            if result.rugcheck_score > cfg.max_rugcheck_score:
                result.reason = (
                    f"Risk score {result.rugcheck_score} > {cfg.max_rugcheck_score}"
                )
                return result
            result.safe = True
    finally:
        await rugcheck.close()

    # 2. Token-2022 transfer hooks check
    if cfg.skip_token_2022_hooks:
        is_t22 = await _check_token_2022(token_mint, cfg)
        result.is_token_2022 = is_t22
        if is_t22:
            result.safe = False
            result.reason = "Token-2022 with potential transfer hooks"
            return result

    # 3. Top holder check (if not already from Rugcheck)
    if result.top_holder_pct == 0:
        top_pct = await _check_top_holder(token_mint, pool_address, cfg)
        result.top_holder_pct = top_pct
        if top_pct > cfg.max_top_holder_pct:
            result.safe = False
            result.reason = f"Top holder {top_pct:.1f}% > {cfg.max_top_holder_pct}%"
            return result

    # 4. Honeypot detection v2 (multi-amount, always run)
    honeypot = await _check_honeypot_v2(token_mint, cfg)
    result.honeypot_safe = honeypot["safe"]
    result.honeypot_sell_ratio = honeypot.get("sell_ratio", 0)
    if not honeypot["safe"]:
        result.safe = False
        result.reason = f"Honeypot: {honeypot.get('reason', 'sell blocked')}"
        return result

    result.safe = True
    result.reason = "OK"
    return result


async def _onchain_safety_checks(token_mint: str, cfg: Config) -> SafetyResult:
    """Fallback on-chain checks when Rugcheck is unavailable."""
    result = SafetyResult(safe=False)
    rpc = SolanaRPC(cfg.rpc_http)
    try:
        account = await rpc.get_account_info_json_parsed(token_mint)
        if not account:
            result.reason = "Mint account not found"
            return result

        data = account.get("data", {})
        if isinstance(data, dict):
            parsed = data.get("parsed", {}).get("info", {})
        else:
            result.reason = "Cannot parse mint data"
            return result

        mint_auth = parsed.get("mintAuthority")
        freeze_auth = parsed.get("freezeAuthority")

        result.mint_revoked = mint_auth is None
        result.freeze_revoked = freeze_auth is None

        if cfg.require_mint_revoked and not result.mint_revoked:
            result.reason = "Mint authority NOT revoked"
            return result
        if cfg.require_freeze_revoked and not result.freeze_revoked:
            result.reason = "Freeze authority NOT revoked"
            return result

        result.safe = True
        result.reason = "OK (on-chain)"
    finally:
        await rpc.close()
    return result


async def _check_token_2022(token_mint: str, cfg: Config) -> bool:
    """Check if Token-2022 token has actual transfer hooks enabled."""
    rpc = SolanaRPC(cfg.rpc_http)
    try:
        account = await rpc.get_account_info_json_parsed(token_mint)
        if not account:
            return False
        owner = account.get("owner", "")
        if owner != cfg.TOKEN_2022_PROGRAM:
            return False

        data = account.get("data", {})
        if not isinstance(data, dict):
            return False
        extensions = (
            data.get("parsed", {}).get("info", {}).get("extensions", [])
        )
        for ext in extensions:
            ext_type = ext.get("extension", "")
            if ext_type == "transferHook":
                hook_addr = ext.get("state", {}).get("programId", "")
                if hook_addr and hook_addr != "1" * 32:
                    logger.info(
                        "Token %s has transfer hook: %s", token_mint[:12], hook_addr
                    )
                    return True
        return False
    except Exception as e:
        logger.warning("Token-2022 check error for %s: %s", token_mint[:12], e)
        return False
    finally:
        await rpc.close()


async def _check_top_holder(
    token_mint: str, pool_address: str, cfg: Config
) -> float:
    """Check largest token holder percentage (excluding pool and burn)."""
    rpc = SolanaRPC(cfg.rpc_http)
    try:
        holders = await rpc.get_token_largest_accounts(token_mint)
        if not holders:
            return 0.0

        # Get total supply
        account = await rpc.get_account_info_json_parsed(token_mint)
        if not account:
            return 0.0

        data = account.get("data", {})
        if isinstance(data, dict):
            supply_str = data.get("parsed", {}).get("info", {}).get("supply", "0")
        else:
            return 0.0

        total_supply = int(supply_str) if supply_str else 0
        if total_supply == 0:
            return 0.0

        excluded = {pool_address, cfg.BURN_ADDRESS}
        for holder in holders:
            addr = holder.get("address", "")
            if addr in excluded:
                continue
            amount = int(holder.get("amount", "0"))
            pct = (amount / total_supply) * 100
            return pct
        return 0.0
    except Exception as e:
        logger.warning("Top holder check failed: %s", e)
        return 0.0
    finally:
        await rpc.close()


async def _check_honeypot_v2(token_mint: str, cfg: Config) -> dict:
    """Multi-amount honeypot detection v2 with retry for Jupiter indexing lag."""
    jupiter = JupiterClient(
        api_key=cfg.jupiter_api_key,
        quote_url=cfg.jupiter_quote_url,
        swap_url=cfg.jupiter_swap_url,
    )
    try:
        delays = [
            cfg.honeypot_initial_delay,
            cfg.honeypot_retry_delay,
            cfg.honeypot_retry_delay * 2,
            cfg.honeypot_retry_delay * 3,
        ]
        max_attempts = cfg.honeypot_max_retries + 1

        for attempt in range(max_attempts):
            if attempt > 0:
                wait = delays[min(attempt, len(delays) - 1)]
                logger.info(
                    "Honeypot retry %d/%d for %s in %ds",
                    attempt, cfg.honeypot_max_retries, token_mint[:12], wait,
                )
                await asyncio.sleep(wait)
            elif delays[0] > 0:
                logger.debug(
                    "Honeypot initial wait %ds for %s", delays[0], token_mint[:12]
                )
                await asyncio.sleep(delays[0])

            results = await asyncio.gather(*[
                jupiter.simulate_buy_sell(token_mint, amt)
                for amt in HONEYPOT_TEST_AMOUNTS
            ])

            errors = [r for r in results if r.get("error")]
            if len(errors) < len(results):
                break
            logger.debug(
                "Honeypot attempt %d: all %d simulations failed for %s",
                attempt + 1, len(results), token_mint[:12],
            )
        else:
            return {"safe": False, "reason": "All simulations failed — honeypot"}

        ratios = [r["sell_ratio"] for r in results if not r.get("error")]
        if not ratios:
            return {"safe": False, "reason": "No valid sell ratios"}

        min_ratio = min(ratios)
        max_ratio = max(ratios)
        spread = max_ratio - min_ratio

        if spread > 0.15:
            return {
                "safe": False,
                "sell_ratio": min_ratio,
                "reason": f"Dynamic tax: spread {spread:.0%} between amounts",
            }

        if min_ratio < 0.50:
            return {
                "safe": False,
                "sell_ratio": min_ratio,
                "reason": f"Honeypot or extreme tax ({(1 - min_ratio) * 100:.0f}%)",
            }
        elif min_ratio < 0.85:
            return {
                "safe": False,
                "sell_ratio": min_ratio,
                "reason": f"High tax: {(1 - min_ratio) * 100:.0f}%",
            }

        avg_tax = (1 - sum(ratios) / len(ratios)) * 100
        return {"safe": True, "sell_ratio": min_ratio, "tax_pct": avg_tax}
    finally:
        await jupiter.close()


async def recheck_honeypot_after_buy(
    token_mint: str, cfg: Config, delay_seconds: int = 90
) -> dict:
    """Layer 4: Re-check honeypot after delay (timing-based honeypots)."""
    await asyncio.sleep(delay_seconds)
    result = await _check_honeypot_v2(token_mint, cfg)
    if not result["safe"]:
        result["timing_honeypot"] = True
        result["reason"] = (
            f"TIMING HONEYPOT: sell blocked after {delay_seconds}s — SELL IMMEDIATELY"
        )
    return result
