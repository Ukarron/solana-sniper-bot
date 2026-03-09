"""
КРОК 2.5: Creator Analysis — deployer wallet investigation.

Checks deployer age, token count, blacklist status.
Serial scammers create dozens of tokens — this filter catches ~30-40% of scams.
"""

from __future__ import annotations

import logging
import time

from config import Config
from models import CreatorProfile
from api_clients.helius import HeliusClient
from api_clients.solana_rpc import SolanaRPC
from database import get_db

logger = logging.getLogger(__name__)


async def analyze_creator(token_mint: str, cfg: Config) -> CreatorProfile:
    """Analyze the token deployer's wallet history."""
    profile = CreatorProfile()

    helius = HeliusClient(cfg.helius_api_key, cfg.rpc_http)
    rpc = SolanaRPC(cfg.rpc_http)
    db = get_db()

    try:
        # Find deployer: check mint authority or first transaction
        deployer = await _find_deployer(token_mint, rpc, helius)
        if not deployer:
            profile.reason = "Could not identify deployer"
            return profile
        profile.deployer_address = deployer

        # Check blacklist
        if await db.is_blacklisted(deployer):
            profile.is_blacklisted = True
            profile.reason = "Deployer is blacklisted"
            return profile

        # Check deployer age
        age_days = await _check_deployer_age(deployer, rpc)
        profile.deployer_age_days = age_days

        # Check number of tokens created
        token_count = await _count_deployer_tokens(deployer, helius)
        profile.token_count = token_count

        # Calculate score
        score = 0

        # Age scoring
        if age_days > 30:
            score += 1
        elif age_days < cfg.min_deployer_age_days:
            score -= 1

        # Token count scoring
        if token_count <= 3:
            score += 2
        elif token_count <= cfg.max_deployer_tokens:
            pass  # neutral
        else:
            score -= 2

        profile.score = score
        profile.reason = (
            f"age={age_days}d tokens={token_count} score={score}"
        )
    except Exception as e:
        logger.warning("Creator analysis failed for %s: %s", token_mint[:12], e)
        profile.reason = f"Analysis error: {e}"
    finally:
        await helius.close()
        await rpc.close()

    return profile


async def _find_deployer(
    token_mint: str, rpc: SolanaRPC, helius: HeliusClient
) -> str:
    """Find the wallet that created this token."""
    # Try mint authority first
    account = await rpc.get_account_info_json_parsed(token_mint)
    if account:
        data = account.get("data", {})
        if isinstance(data, dict):
            mint_auth = data.get("parsed", {}).get("info", {}).get("mintAuthority")
            if mint_auth:
                return mint_auth

    # Fallback: check first transaction's feePayer
    txs = await helius.get_transactions(token_mint, tx_type="TOKEN_MINT", limit=1)
    if txs:
        return txs[0].get("feePayer", "")

    # Last resort: getSignaturesForAddress
    sigs = await rpc.get_signatures_for_address(token_mint, limit=1)
    if sigs:
        last_sig = sigs[-1].get("signature", "")
        if last_sig:
            tx = await rpc.get_transaction(last_sig)
            if tx:
                message = tx.get("transaction", {}).get("message", {})
                keys = message.get("accountKeys", [])
                if keys:
                    first_key = keys[0]
                    if isinstance(first_key, dict):
                        return first_key.get("pubkey", "")
                    return first_key
    return ""


async def _check_deployer_age(deployer: str, rpc: SolanaRPC) -> int:
    """Estimate deployer wallet age in days by paginating to the oldest tx."""
    try:
        before = None
        oldest_time = 0
        for _ in range(10):
            params = [deployer, {"limit": 1000}]
            if before:
                params[1]["before"] = before
            sigs = await rpc._call("getSignaturesForAddress", params)
            if not sigs:
                break
            last = sigs[-1]
            bt = last.get("blockTime", 0)
            if bt:
                oldest_time = bt
            if len(sigs) < 1000:
                break
            before = last.get("signature")

        if oldest_time:
            age_sec = time.time() - oldest_time
            return max(0, int(age_sec / 86400))
    except Exception as e:
        logger.debug("Deployer age check failed: %s", e)
    return 0


async def _count_deployer_tokens(deployer: str, helius: HeliusClient) -> int:
    """Count how many tokens this deployer has created."""
    try:
        assets = await helius.get_assets_by_creator(deployer, limit=50)
        return len(assets)
    except Exception as e:
        logger.debug("Token count check failed: %s", e)
        return 0
