"""
Solana Smart Sniping Bot — entry point.

Pipeline ("Confirm Then Snipe"):
  КРОК 0:    Macro filter (background, hourly)
  КРОК 1:    Pool detection (WebSocket)
  КРОК 1.5:  Minimum liquidity check
  КРОК 2-3:  Safety / Creator / Legitimacy (parallel)
  КРОК 4:    Early activity analysis (15s wait)
  КРОК 4.3:  DexScreener real-time validation (price, volume, buy pressure)
  КРОК 4.4:  Quality scoring (0-100, threshold >= 60)
  КРОК 4.45: Trade rate limiting (max 3/h, 10/d)
  КРОК 4.5:  EV filter
  КРОК 4.7:  Multi-sample momentum (4 samples, 20s, require 3%+ rise)
  КРОК 5:    Trade execution (Jupiter + Jito)
  КРОК 6:    Position management (trailing TP/SL)
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import signal
import time

from collections import deque
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from config import Config
from database import get_db
from models import FilterLog, PoolInfo
from notifier import get_notifier
from observability.logger import setup_logging
from observability.reporter import generate_daily_report
from pool_detector import start_pool_detection
from safety_filter import run_safety_checks
from creator_analysis import analyze_creator
from legitimacy_filter import calculate_legitimacy_score
from early_activity import analyze_early_activity
from ev_calculator import EVCalculator
from macro_filter import MacroFilter
from trade_executor import TradeExecutor
from position_manager import PositionManager
from api_clients.dexscreener import DexScreenerClient
from quality_scorer import compute_quality_score
from utils import Timer

logger = logging.getLogger("sniper")

# Trade rate limiter — tracks timestamps of executed trades
_trade_timestamps: deque[float] = deque()


def _check_rate_limit(cfg: Config) -> str | None:
    """Return a skip reason if rate limit exceeded, else None."""
    now = time.time()
    hour_ago = now - 3600
    day_start = now - 86400

    while _trade_timestamps and _trade_timestamps[0] < day_start:
        _trade_timestamps.popleft()

    trades_last_hour = sum(1 for t in _trade_timestamps if t >= hour_ago)
    trades_last_day = len(_trade_timestamps)

    if trades_last_hour >= cfg.max_trades_per_hour:
        return f"rate_limit: {trades_last_hour}/{cfg.max_trades_per_hour} trades this hour"
    if trades_last_day >= cfg.max_trades_per_day:
        return f"rate_limit: {trades_last_day}/{cfg.max_trades_per_day} trades today"
    return None


async def process_new_pool(
    pool: PoolInfo,
    cfg: Config,
    macro: MacroFilter,
    ev_calc: EVCalculator,
    executor: TradeExecutor,
    pos_mgr: PositionManager,
    dex_client: DexScreenerClient,
) -> None:
    """Run the full filter pipeline on a newly detected pool."""
    db = get_db()
    notifier = get_notifier()
    flog = FilterLog(pool=pool)

    # Check max concurrent positions
    open_count = pos_mgr.open_position_count
    if open_count >= cfg.max_concurrent_positions:
        logger.info(
            "SKIP [capacity] %s: %d/%d positions open",
            pool.token_mint[:12], open_count, cfg.max_concurrent_positions,
        )
        return

    # Prevent buying same token twice
    if pos_mgr.has_token(pool.token_mint):
        logger.info("SKIP [duplicate] %s: already holding this token", pool.token_mint[:12])
        return

    with Timer() as timer:
        # Save detection
        pool_id = await db.save_detected_pool(
            signature=pool.signature,
            pool_address=pool.pool_address,
            token_mint=pool.token_mint,
            token_symbol=pool.token_symbol,
            token_name=pool.token_name,
            quote_mint=pool.quote_mint,
            dex=pool.source.value,
            source=pool.source.value,
            initial_liquidity=pool.initial_liquidity_sol,
        )
        await db.increment_daily_stat("pools_detected")

        # КРОК 1.5: Minimum liquidity check
        if pool.initial_liquidity_sol > 0 and pool.initial_liquidity_sol < cfg.min_liquidity_sol:
            flog.skip_reason = f"liquidity: {pool.initial_liquidity_sol:.1f} < {cfg.min_liquidity_sol} SOL"
            logger.info(
                "SKIP [liquidity] %s: %.1f SOL < %.1f SOL min",
                pool.token_mint[:12], pool.initial_liquidity_sol, cfg.min_liquidity_sol,
            )
            await _save_filter_result(db, pool_id, flog, timer)
            return

        # КРОК 2 + 2.5 + 3: Safety / Creator / Legitimacy in parallel
        safety_coro = run_safety_checks(pool.token_mint, pool.pool_address, cfg)
        creator_coro = analyze_creator(pool.token_mint, cfg)
        legitimacy_coro = calculate_legitimacy_score(pool.token_mint, cfg)

        try:
            results = await asyncio.gather(
                safety_coro, creator_coro, legitimacy_coro,
                return_exceptions=True,
            )
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    names = ["safety", "creator", "legitimacy"]
                    logger.warning("Filter %s failed for %s: %s", names[i], pool.token_mint[:12], r)
                    flog.skip_reason = f"{names[i]} exception: {r}"
                    await _save_filter_result(db, pool_id, flog, timer)
                    return
            safety, creator, legitimacy = results
        except Exception:
            raise

        flog.safety = safety
        if not safety.safe:
            flog.skip_reason = f"safety: {safety.reason}"
            logger.info("SKIP [safety] %s: %s", pool.token_mint[:12], safety.reason)
            await _save_filter_result(db, pool_id, flog, timer)
            return

        flog.creator = creator
        if creator.is_blacklisted or creator.score < 0:
            flog.skip_reason = f"creator: {creator.reason}"
            logger.info("SKIP [creator] %s: %s", pool.token_mint[:12], creator.reason)
            await _save_filter_result(db, pool_id, flog, timer)
            return

        flog.legitimacy = legitimacy
        if legitimacy.score < cfg.min_legitimacy_score:
            flog.skip_reason = f"legitimacy: score {legitimacy.score} < {cfg.min_legitimacy_score}"
            logger.info("SKIP [legitimacy] %s: score %d too low", pool.token_mint[:12], legitimacy.score)
            await _save_filter_result(db, pool_id, flog, timer)
            return
        if legitimacy.score > cfg.max_legitimacy_score:
            flog.skip_reason = f"legitimacy: score {legitimacy.score} > {cfg.max_legitimacy_score}"
            logger.info("SKIP [legitimacy] %s: score %d too high (suspicious)", pool.token_mint[:12], legitimacy.score)
            await _save_filter_result(db, pool_id, flog, timer)
            return

        # КРОК 4: Early activity (wait before analysis)
        if cfg.wait_before_analysis_sec > 0:
            await asyncio.sleep(cfg.wait_before_analysis_sec)

        activity = await analyze_early_activity(pool.token_mint, pool.pool_address, cfg)
        flog.early_activity = activity
        if not activity.passed:
            flog.skip_reason = f"activity: {activity.reason}"
            logger.info("SKIP [activity] %s: %s", pool.token_mint[:12], activity.reason)
            await _save_filter_result(db, pool_id, flog, timer)
            return

        # КРОК 4.3: DexScreener real-time validation
        dex_metrics = await dex_client.get_pair_metrics(pool.token_mint)
        if not dex_metrics.available:
            flog.skip_reason = "dexscreener: no data available (token not gaining traction)"
            logger.info("SKIP [dexscreener] %s: no pair data found", pool.token_mint[:12])
            await _save_filter_result(db, pool_id, flog, timer)
            return

        if cfg.dex_require_rising and not dex_metrics.is_rising:
            flog.skip_reason = f"dexscreener: price falling (5m change {dex_metrics.price_change_m5:+.1f}%)"
            logger.info("SKIP [dexscreener] %s: price not rising (%.1f%%)", pool.token_mint[:12], dex_metrics.price_change_m5)
            await _save_filter_result(db, pool_id, flog, timer)
            return

        if cfg.dex_require_buy_pressure and not dex_metrics.has_buy_pressure:
            flog.skip_reason = f"dexscreener: sells >= buys ({dex_metrics.sells_m5}s vs {dex_metrics.buys_m5}b)"
            logger.info("SKIP [dexscreener] %s: no buy pressure (%db/%ds)", pool.token_mint[:12], dex_metrics.buys_m5, dex_metrics.sells_m5)
            await _save_filter_result(db, pool_id, flog, timer)
            return

        if cfg.dex_require_volume and not dex_metrics.has_volume:
            flog.skip_reason = "dexscreener: zero h1 volume"
            logger.info("SKIP [dexscreener] %s: no volume", pool.token_mint[:12])
            await _save_filter_result(db, pool_id, flog, timer)
            return

        if dex_metrics.liquidity_usd < cfg.dex_min_liquidity_usd:
            flog.skip_reason = f"dexscreener: low liquidity ${dex_metrics.liquidity_usd:.0f} < ${cfg.dex_min_liquidity_usd:.0f}"
            logger.info("SKIP [dexscreener] %s: liquidity $%.0f < $%.0f", pool.token_mint[:12], dex_metrics.liquidity_usd, cfg.dex_min_liquidity_usd)
            await _save_filter_result(db, pool_id, flog, timer)
            return

        logger.info(
            "DexScreener OK for %s: 5m=%+.1f%% buys/sells=%d/%d vol_h1=$%.0f liq=$%.0f",
            pool.token_mint[:12], dex_metrics.price_change_m5,
            dex_metrics.buys_m5, dex_metrics.sells_m5,
            dex_metrics.volume_h1_usd, dex_metrics.liquidity_usd,
        )

        # КРОК 4.4: Quality scoring
        quality = compute_quality_score(activity, dex_metrics, safety, creator, legitimacy)
        logger.info("Quality %s: %s", pool.token_mint[:12], quality.summary())

        if quality.total < cfg.min_quality_score:
            flog.skip_reason = f"quality: score {quality.total} < {cfg.min_quality_score}"
            logger.info("SKIP [quality] %s: score %d < %d", pool.token_mint[:12], quality.total, cfg.min_quality_score)
            await _save_filter_result(db, pool_id, flog, timer)
            return

        # КРОК 4.45: Trade rate limiting
        rate_reason = _check_rate_limit(cfg)
        if rate_reason:
            flog.skip_reason = rate_reason
            logger.info("SKIP [rate] %s: %s", pool.token_mint[:12], rate_reason)
            await _save_filter_result(db, pool_id, flog, timer)
            return

        # КРОК 4.5: EV filter
        if not ev_calc.is_profitable:
            flog.skip_reason = f"ev: EV={ev_calc.ev:.1f} <= 0"
            logger.info("SKIP [ev] %s: negative EV", pool.token_mint[:12])
            await _save_filter_result(db, pool_id, flog, timer)
            return
        flog.ev_positive = True

        # КРОК 0 result: macro multiplier
        flog.macro_multiplier = macro.get_risk_multiplier()

        # All filters passed
        flog.passed_all = True
        await db.increment_daily_stat("pools_passed")

    flog.filter_duration_ms = timer.elapsed_ms
    await _save_filter_result(db, pool_id, flog, timer)
    logger.info(
        "PASSED all filters: %s (%s) in %dms",
        pool.token_symbol or pool.token_mint[:12], pool.source.value, timer.elapsed_ms,
    )

    # КРОК 4.7: Multi-sample momentum check — verify price is rising
    try:
        jup = executor.jupiter
        test_amount = 100_000_000  # 0.1 SOL
        samples: list[int] = []
        for i in range(cfg.momentum_check_samples):
            q = await jup.get_quote(cfg.SOL_MINT, pool.token_mint, test_amount, cfg.max_slippage_bps)
            tokens = int(q["outAmount"]) if q and q.get("outAmount") else 0
            if tokens <= 0:
                break
            samples.append(tokens)
            if i < cfg.momentum_check_samples - 1:
                await asyncio.sleep(cfg.momentum_check_interval_sec)

        if len(samples) >= 2:
            # Fewer tokens for same SOL = price rising (positive = price up)
            total_change = (samples[0] - samples[-1]) / samples[0]

            if total_change < cfg.momentum_max_drop_pct / 100:
                logger.info(
                    "SKIP [momentum] %s: price dropping %.1f%% over %d samples",
                    pool.token_mint[:12], total_change * 100, len(samples),
                )
                return
            if total_change < cfg.momentum_min_rise_pct / 100:
                logger.info(
                    "SKIP [momentum] %s: price flat/weak %.1f%% (need >%.1f%%)",
                    pool.token_mint[:12], total_change * 100, cfg.momentum_min_rise_pct,
                )
                return
            logger.info(
                "Momentum OK for %s: %.1f%% total change (%d samples)",
                pool.token_mint[:12], total_change * 100, len(samples),
            )
    except Exception as e:
        logger.debug("Momentum check error: %s", e)

    # КРОК 5: Execute trade
    buy_amount = cfg.buy_amount_sol * flog.macro_multiplier
    trade = await executor.buy(pool, buy_amount)
    if trade and trade.tx_signature:
        _trade_timestamps.append(time.time())
        await db.mark_pool_bought(pool_id)
        await db.save_trade(
            pool_id=pool_id,
            token_mint=trade.token_mint,
            token_symbol=trade.token_symbol,
            side=trade.side,
            amount_sol=trade.amount_sol,
            token_amount=trade.token_amount,
            price_per_token=trade.price_per_token,
            tx_signature=trade.tx_signature,
            slippage_actual=trade.slippage_actual,
            wallet_address=trade.wallet_address,
        )
        await db.increment_daily_stat("trades_executed")
        token_name = html.escape(pool.token_name or trade.token_symbol or "???")
        token_sym = html.escape(trade.token_symbol or "???")
        dex_link = f"https://dexscreener.com/solana/{trade.token_mint}"
        notifier.alert(
            f"🟢 <b>BUY</b> {token_name} (${token_sym})\n"
            f"Amount: {trade.amount_sol:.3f} SOL\n"
            f"Mint: <code>{trade.token_mint[:16]}...</code>\n"
            f'<a href="{dex_link}">DexScreener</a> | '
            f"TX: <code>{trade.tx_signature[:16]}...</code>"
        )

        # КРОК 6: Start position monitoring
        pos_id = await db.save_position(
            pool_id=pool_id,
            token_mint=trade.token_mint,
            token_symbol=trade.token_symbol,
            entry_price=trade.price_per_token,
            entry_amount_sol=trade.amount_sol,
            token_amount=trade.token_amount,
            status="open",
            opened_at=trade.executed_at,
        )
        await pos_mgr.track_position(pos_id, trade, pool_id=pool_id)


async def _save_filter_result(db, pool_id: int, flog: FilterLog, timer: Timer) -> None:
    """Persist filter results to the database."""
    updates: dict = {
        "passed_filters": flog.passed_all,
        "skip_reason": flog.skip_reason,
        "filter_duration_ms": timer.elapsed_ms,
    }
    if flog.safety:
        updates.update(
            rugcheck_score=flog.safety.rugcheck_score,
            mint_revoked=flog.safety.mint_revoked,
            freeze_revoked=flog.safety.freeze_revoked,
            honeypot_safe=flog.safety.honeypot_safe,
            honeypot_sell_ratio=flog.safety.honeypot_sell_ratio,
            top_holder_pct=flog.safety.top_holder_pct,
            liquidity_mc_ratio=flog.safety.liquidity_mc_ratio,
            is_token_2022=flog.safety.is_token_2022,
        )
    if flog.creator:
        updates.update(
            deployer_address=flog.creator.deployer_address,
            deployer_age_days=flog.creator.deployer_age_days,
            deployer_token_count=flog.creator.token_count,
            deployer_score=flog.creator.score,
        )
    if flog.legitimacy:
        updates["legitimacy_score"] = flog.legitimacy.score
    if flog.early_activity:
        updates.update(
            unique_buyers=flog.early_activity.unique_buyers,
            has_whitelist_buyer=bool(flog.early_activity.whitelist_buyers),
            has_blacklist_buyer=flog.early_activity.has_blacklisted_buyer,
        )
    await db.update_pool_filters(pool_id, **updates)


async def _daily_summary_loop() -> None:
    """Send a Telegram summary at 10:00 Kyiv time each day."""
    kyiv = ZoneInfo("Europe/Kyiv")
    notifier = get_notifier()

    while True:
        try:
            now_kyiv = datetime.now(kyiv)
            target = now_kyiv.replace(hour=10, minute=0, second=0, microsecond=0)
            if now_kyiv >= target:
                target += timedelta(days=1)
            wait = (target - now_kyiv).total_seconds()
            logger.info("Daily summary scheduled in %.0f min (10:00 Kyiv)", wait / 60)
            await asyncio.sleep(wait)

            yesterday = (datetime.now(kyiv) - timedelta(days=1)).strftime("%Y-%m-%d")
            await generate_daily_report(notifier, date=yesterday)
            logger.info("Daily summary sent for %s", yesterday)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.debug("Daily summary error", exc_info=True)
            await asyncio.sleep(60)


async def run_bot() -> None:
    cfg = Config.from_env()
    cfg.validate()
    setup_logging(cfg.log_level)

    logger.info("Starting Solana Smart Sniping Bot (paper_trading=%s)", cfg.paper_trading)

    db = get_db()
    await db.init()

    notifier = get_notifier()
    await notifier.start()
    notifier.alert("🟢 <b>Sniper Bot started</b> (paper=%s)" % cfg.paper_trading)

    macro = MacroFilter(cfg)
    ev_calc = EVCalculator(
        win_rate=cfg.estimated_win_rate,
        avg_profit_pct=100.0,
        avg_loss_pct=cfg.stop_loss_pct,
    )
    executor = TradeExecutor(cfg)
    pos_mgr = PositionManager(cfg, executor, ev_calc)
    dex_client = DexScreenerClient()

    # Shutdown coordination
    shutdown_event = asyncio.Event()
    stop_file = os.path.join(os.path.dirname(__file__) or ".", ".stop")

    def _request_shutdown() -> None:
        if not shutdown_event.is_set():
            logger.info("Shutdown signal received...")
            shutdown_event.set()

    # Register signal handlers
    signal.signal(signal.SIGINT, lambda *_: _request_shutdown())
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda *_: _request_shutdown())

    async def _watch_stop_file() -> None:
        """Poll for .stop file — reliable graceful shutdown on Windows."""
        while not shutdown_event.is_set():
            if os.path.exists(stop_file):
                logger.info(".stop file detected — initiating shutdown")
                try:
                    os.remove(stop_file)
                except OSError:
                    pass
                _request_shutdown()
                return
            await asyncio.sleep(2)

    # Background tasks
    macro_task = asyncio.create_task(macro.run_loop(), name="macro-filter")
    pos_mgr_task = asyncio.create_task(pos_mgr.run_loop(), name="position-manager")
    summary_task = asyncio.create_task(_daily_summary_loop(), name="daily-summary")
    stopwatch_task = asyncio.create_task(_watch_stop_file(), name="stop-watcher")

    async def on_new_pool(pool: PoolInfo) -> None:
        try:
            await process_new_pool(pool, cfg, macro, ev_calc, executor, pos_mgr, dex_client)
        except Exception:
            logger.exception("Error processing pool %s", pool.token_mint[:12])

    detection_task = asyncio.create_task(start_pool_detection(cfg, on_new_pool))

    # Wait for shutdown signal
    await shutdown_event.wait()

    # Graceful shutdown
    logger.info("Bot shutting down...")
    try:
        await notifier.send_direct("🔴 Sniper Bot shutting down...")
    except Exception:
        pass

    for t in (detection_task, macro_task, pos_mgr_task, summary_task, stopwatch_task):
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass

    await dex_client.close()
    await executor.close()
    await notifier.stop()
    await db.close()
    logger.info("Bot stopped")


def main() -> None:
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
