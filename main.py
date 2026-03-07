"""
Solana Smart Sniping Bot — entry point.

Pipeline:
  КРОК 0: Macro filter (background, hourly)
  КРОК 1: Pool detection (WebSocket)
  КРОК 2: Safety filter (Rugcheck + on-chain + honeypot)
  КРОК 2.5: Creator analysis
  КРОК 3: Legitimacy filter
  КРОК 4: Early activity analysis
  КРОК 4.5: EV filter
  КРОК 5: Trade execution (Jupiter + Jito)
  КРОК 6: Position management (trailing TP/SL)
  КРОК 7: Logging & reporting
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

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
from utils import Timer

logger = logging.getLogger("sniper")


async def process_new_pool(
    pool: PoolInfo,
    cfg: Config,
    macro: MacroFilter,
    ev_calc: EVCalculator,
    executor: TradeExecutor,
    pos_mgr: PositionManager,
) -> None:
    """Run the full filter pipeline on a newly detected pool."""
    db = get_db()
    notifier = get_notifier()
    flog = FilterLog(pool=pool)

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

        # КРОК 2: Safety filter
        safety = await run_safety_checks(pool.token_mint, pool.pool_address, cfg)
        flog.safety = safety
        if not safety.safe:
            flog.skip_reason = f"safety: {safety.reason}"
            logger.info("SKIP [safety] %s: %s", pool.token_mint[:12], safety.reason)
            await _save_filter_result(db, pool_id, flog, timer)
            return

        # КРОК 2.5: Creator analysis
        creator = await analyze_creator(pool.token_mint, cfg)
        flog.creator = creator
        if creator.is_blacklisted or creator.score < 0:
            flog.skip_reason = f"creator: {creator.reason}"
            logger.info("SKIP [creator] %s: %s", pool.token_mint[:12], creator.reason)
            await _save_filter_result(db, pool_id, flog, timer)
            return

        # КРОК 3: Legitimacy filter
        legitimacy = await calculate_legitimacy_score(pool.token_mint, cfg)
        flog.legitimacy = legitimacy
        if legitimacy.score < cfg.min_legitimacy_score:
            flog.skip_reason = f"legitimacy: score {legitimacy.score} < {cfg.min_legitimacy_score}"
            logger.info("SKIP [legitimacy] %s: score %d", pool.token_mint[:12], legitimacy.score)
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

    # КРОК 5: Execute trade
    buy_amount = cfg.buy_amount_sol * flog.macro_multiplier
    trade = await executor.buy(pool, buy_amount)
    if trade and trade.tx_signature:
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
        token_name = pool.token_name or trade.token_symbol
        dex_link = f"https://dexscreener.com/solana/{trade.token_mint}"
        notifier.alert(
            f"🟢 <b>BUY</b> {token_name} (${trade.token_symbol})\n"
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
        await pos_mgr.track_position(pos_id, trade)


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
    pos_mgr = PositionManager(cfg, executor)

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
            await process_new_pool(pool, cfg, macro, ev_calc, executor, pos_mgr)
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
