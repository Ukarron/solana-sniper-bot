"""
Pool Detector — real-time detection of new liquidity pools via logsSubscribe.

Uses logsSubscribe with auto-reconnect (exponential backoff + jitter).
Matches are put into a queue; a separate worker fetches tx details and dispatches.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Callable

import aiohttp
from websockets import connect
from websockets.exceptions import ConnectionClosed

from config import Config
from models import PoolInfo, PoolSource

logger = logging.getLogger(__name__)

_seen_sigs: set[str] = set()
_MAX_SEEN = 5000


async def start_pool_detection(
    cfg: Config, on_new_pool: Callable[[PoolInfo], Any],
) -> None:
    """Main entry point — runs WS listener + worker concurrently."""
    queue: asyncio.Queue[tuple[str, PoolSource]] = asyncio.Queue(maxsize=100)

    worker = asyncio.create_task(_match_worker(queue, cfg, on_new_pool))
    try:
        await _ws_listener(cfg, queue)
    finally:
        worker.cancel()


async def _ws_listener(
    cfg: Config,
    queue: asyncio.Queue[tuple[str, PoolSource]],
) -> None:
    """WebSocket listener — detects matching log events, puts them in queue."""
    base_delay = cfg.ws_base_delay
    max_delay = cfg.ws_max_delay
    attempt = 0

    while True:
        try:
            async with connect(
                cfg.rpc_wss,
                ping_interval=cfg.ws_ping_interval,
                ping_timeout=cfg.ws_ping_timeout,
            ) as ws:
                attempt = 0
                logger.info("WebSocket connected to %s", cfg.rpc_wss[:40])

                await ws.send(json.dumps({
                    "jsonrpc": "2.0", "id": 1,
                    "method": "logsSubscribe",
                    "params": [
                        {"mentions": [cfg.PUMPFUN_MIGRATION]},
                        {"commitment": "confirmed"},
                    ],
                }))
                await ws.send(json.dumps({
                    "jsonrpc": "2.0", "id": 2,
                    "method": "logsSubscribe",
                    "params": [
                        {"mentions": [cfg.RAYDIUM_AMM_V4]},
                        {"commitment": "confirmed"},
                    ],
                }))

                for _ in range(2):
                    confirm = await asyncio.wait_for(ws.recv(), timeout=10)
                    logger.debug("Subscription confirmed: %s", confirm[:120])

                logger.info("Listening for new pools (PumpSwap + Raydium) via logsSubscribe...")

                event_count = 0
                match_count = 0
                async for message in ws:
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        continue

                    if "method" not in data:
                        continue

                    value = (
                        data.get("params", {})
                        .get("result", {})
                        .get("value", {})
                    )
                    if not value:
                        continue

                    sig = value.get("signature", "")
                    logs = value.get("logs", [])
                    err = value.get("err")

                    event_count += 1
                    if event_count % 500 == 1:
                        logger.info(
                            "Events received: %d (matched: %d, queue: %d)",
                            event_count, match_count, queue.qsize(),
                        )

                    if err or not sig or not logs:
                        continue
                    if sig in _seen_sigs:
                        continue

                    logs_text = "\n".join(logs)

                    is_pumpswap = (
                        cfg.PUMPSWAP_AMM in logs_text
                        and "Instruction: Migrate" in logs_text
                        and "CreatePool" in logs_text
                    )
                    is_raydium = (
                        not is_pumpswap
                        and cfg.RAYDIUM_AMM_V4 in logs_text
                        and ("initialize2" in logs_text.lower() or "InitializeInstruction2" in logs_text)
                    )

                    if not is_pumpswap and not is_raydium:
                        continue

                    _seen_sigs.add(sig)
                    if len(_seen_sigs) > _MAX_SEEN:
                        _seen_sigs.clear()

                    match_count += 1
                    source = PoolSource.PUMPSWAP if is_pumpswap else PoolSource.RAYDIUM
                    logger.info("MATCH [%s] sig=%s", source.value, sig[:20])

                    try:
                        queue.put_nowait((sig, source))
                    except asyncio.QueueFull:
                        logger.warning("Match queue full, dropping sig=%s", sig[:20])

        except (ConnectionClosed, ConnectionError, asyncio.TimeoutError) as e:
            attempt += 1
            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
            logger.warning("WS disconnected: %s. Reconnect in %.1fs (#%d)", e, delay, attempt)
            await asyncio.sleep(delay)
        except Exception as e:
            attempt += 1
            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
            logger.exception("Unexpected WS error: %s. Reconnect in %.1fs (#%d)", e, delay, attempt)
            await asyncio.sleep(delay)


async def _match_worker(
    queue: asyncio.Queue[tuple[str, PoolSource]],
    cfg: Config,
    on_new_pool: Callable[[PoolInfo], Any],
) -> None:
    """Worker that processes matched sigs from the queue."""
    rpc_url = cfg.rpc_http
    logger.info("Match worker started (rpc=%s)", rpc_url[:40])

    async with aiohttp.ClientSession() as session:
        while True:
            sig, source = await queue.get()
            try:
                await _resolve_and_dispatch(session, rpc_url, cfg, sig, source, on_new_pool)
            except Exception:
                logger.exception("Error processing match sig=%s", sig[:20])
            finally:
                queue.task_done()


async def _rpc_call(session: aiohttp.ClientSession, url: str, method: str, params: list) -> Any:
    """Direct RPC call without rate limiter (for the worker only)."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        data = await resp.json()
        if "error" in data:
            raise RuntimeError(f"RPC error: {data['error']}")
        return data.get("result")


async def _resolve_and_dispatch(
    session: aiohttp.ClientSession,
    rpc_url: str,
    cfg: Config,
    sig: str,
    source: PoolSource,
    on_new_pool: Callable[[PoolInfo], Any],
) -> None:
    """Fetch full transaction, extract token mint / pool address, dispatch."""
    tx_data = None
    for attempt in range(5):
        try:
            tx_data = await _rpc_call(session, rpc_url, "getTransaction", [
                sig,
                {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"},
            ])
        except Exception as e:
            logger.warning("getTransaction attempt %d failed for %s: %s", attempt + 1, sig[:20], e)
        if tx_data:
            break
        await asyncio.sleep(0.8 * (attempt + 1))

    if not tx_data:
        logger.warning("Could not fetch tx after retries: %s", sig[:20])
        return

    pool = _parse_full_transaction(tx_data, sig, source, cfg)
    if pool:
        # Fetch token metadata
        try:
            from api_clients.helius import HeliusClient
            helius = HeliusClient(cfg.helius_api_key, cfg.rpc_http)
            asset = await helius.get_asset(pool.token_mint)
            if asset:
                content = asset.get("content", {})
                metadata = content.get("metadata", {})
                pool.token_symbol = metadata.get("symbol", "")
                pool.token_name = metadata.get("name", "")
            await helius.close()
        except Exception:
            logger.debug("Failed to fetch token metadata for %s", pool.token_mint[:12])

        # Extract initial liquidity from postTokenBalances
        try:
            sol_balances = [
                b for b in tx_data.get("meta", {}).get("postTokenBalances", [])
                if b.get("mint") == cfg.SOL_MINT
            ]
            if sol_balances:
                liq_raw = sol_balances[0].get("uiTokenAmount", {}).get("uiAmount", 0)
                pool.initial_liquidity_sol = float(liq_raw) if liq_raw else 0
        except Exception:
            pass

        logger.info(
            "NEW POOL [%s]: %s (%s) mint=%s pool=%s liq=%.1f SOL",
            pool.source.value,
            pool.token_name or "?",
            pool.token_symbol or "?",
            pool.token_mint[:16],
            pool.pool_address[:16] if pool.pool_address else "?",
            pool.initial_liquidity_sol,
        )
        await on_new_pool(pool)
    else:
        meta = tx_data.get("meta", {})
        ptb = meta.get("postTokenBalances", [])
        err = meta.get("err")
        logger.warning(
            "Matched tx but no pool extracted: %s (err=%s, balances=%d, has_tx=%s)",
            sig[:20], err, len(ptb), bool(tx_data.get("transaction")),
        )


def _parse_full_transaction(
    tx_data: dict, sig: str, source: PoolSource, cfg: Config,
) -> PoolInfo | None:
    """Parse getTransaction response — uses postTokenBalances for reliable mint extraction."""
    meta = tx_data.get("meta", {})
    if meta.get("err"):
        return None

    sol_mint = cfg.SOL_MINT
    usdc_mint = cfg.USDC_MINT
    skip_mints = {sol_mint, usdc_mint}

    token_mint = ""
    for bal in meta.get("postTokenBalances", []):
        mint = bal.get("mint", "")
        if mint and mint not in skip_mints:
            token_mint = mint
            break

    if not token_mint:
        return None

    transaction = tx_data.get("transaction", {})
    message = transaction.get("message", {})
    account_keys = message.get("accountKeys", [])
    keys: list[str] = []
    for k in account_keys:
        if isinstance(k, str):
            keys.append(k)
        elif isinstance(k, dict):
            keys.append(k.get("pubkey", ""))
        else:
            keys.append("")

    known_programs = {
        cfg.PUMPSWAP_AMM, cfg.RAYDIUM_AMM_V4, cfg.PUMPFUN_PROGRAM,
        cfg.PUMPFUN_MIGRATION, cfg.SPL_TOKEN, cfg.TOKEN_2022_PROGRAM,
        cfg.JUPITER_V6, sol_mint, usdc_mint,
        "11111111111111111111111111111111",
        "SysvarRent111111111111111111111111111111111",
        "SysvarC1ock11111111111111111111111111111111",
        "SysvarRecentB1ockHashes11111111111111111111",
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
        "ComputeBudget111111111111111111111111111111",
        "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
    }

    signers = set()
    for k in account_keys:
        if isinstance(k, dict) and k.get("signer"):
            signers.add(k.get("pubkey", ""))

    skip_keys = known_programs | signers | {token_mint}

    pool_address = ""
    for k in account_keys:
        if isinstance(k, dict) and k.get("writable") and not k.get("signer"):
            pubkey = k.get("pubkey", "")
            if pubkey and pubkey not in skip_keys:
                pool_address = pubkey
                break
    if not pool_address:
        for key in keys:
            if key and key not in skip_keys:
                pool_address = key
                break

    quote_mint = sol_mint
    for key in keys:
        if key == usdc_mint:
            quote_mint = usdc_mint
            break

    return PoolInfo(
        signature=sig,
        pool_address=pool_address,
        token_mint=token_mint,
        quote_mint=quote_mint,
        source=source,
    )
