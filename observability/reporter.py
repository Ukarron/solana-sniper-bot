"""
Daily & Weekly reports — sent via Telegram at scheduled times.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from database import get_db

logger = logging.getLogger(__name__)


async def generate_daily_report(notifier, date: str | None = None) -> None:
    """Generate and send daily performance summary.

    Args:
        date: YYYY-MM-DD string. Defaults to today (UTC).
    """
    db = get_db()
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stats = await db.get_daily_stats(target_date)

    pools_detected = stats.get("pools_detected", 0) if stats else 0
    pools_passed = stats.get("pools_passed", 0) if stats else 0
    trades = stats.get("trades_executed", 0) if stats else 0
    wins = stats.get("wins", 0) if stats else 0
    losses = stats.get("losses", 0) if stats else 0
    net_pnl = stats.get("net_pnl_sol", 0) if stats else 0

    pass_rate = (pools_passed / pools_detected * 100) if pools_detected > 0 else 0
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

    msg = (
        f"📊 <b>DAILY SUMMARY</b> ({target_date})\n"
        f"Pools detected: {pools_detected}\n"
        f"Passed filters: {pools_passed} ({pass_rate:.0f}%)\n"
        f"Trades: {trades} (W:{wins} / L:{losses})\n"
        f"<b>Net PnL: {net_pnl:+.4f} SOL</b>"
    )

    if win_rate < 20 and (wins + losses) > 5:
        msg += "\n\n⚠️ Win rate below 20% — review filters."
    if net_pnl < -1:
        msg += "\n⚠️ Significant loss — consider reducing position sizes."

    ev_stats = await db.get_ev_stats(days=7)
    if ev_stats and ev_stats["total_trades"] > 0:
        wr = ev_stats["win_rate"] * 100
        ev = ev_stats["ev_per_trade"]
        ev_emoji = "✅" if ev > 0 else "⚠️"
        msg += (
            f"\n\n📈 <b>EV Analytics (7-day)</b>\n"
            f"Win rate: {wr:.1f}% ({ev_stats['wins']}W / {ev_stats['losses']}L)\n"
            f"Avg win: +{ev_stats['avg_win_sol']:.4f} | Avg loss: -{ev_stats['avg_loss_sol']:.4f}\n"
            f"{ev_emoji} <b>EV/trade: {ev:+.4f} SOL</b>\n"
            f"Total PnL (7d): {ev_stats['total_pnl_sol']:+.4f} SOL"
        )
        if ev < 0:
            msg += "\n⚠️ Negative EV — strategy needs review!"

    notifier.alert(msg)


async def generate_weekly_report(notifier) -> None:
    """Generate weekly performance summary."""
    db = get_db()
    ev_stats = await db.get_ev_stats(days=7)

    if not ev_stats or ev_stats["total_trades"] == 0:
        notifier.alert("📊 <b>WEEKLY REPORT</b>\nNo trades this week.")
        return

    wr = ev_stats["win_rate"] * 100
    ev = ev_stats["ev_per_trade"]
    ev_emoji = "✅" if ev > 0 else "⚠️"

    msg = (
        f"📊 <b>WEEKLY REPORT</b>\n"
        f"Trades: {ev_stats['total_trades']} (W:{ev_stats['wins']} / L:{ev_stats['losses']})\n"
        f"Win rate: {wr:.1f}%\n"
        f"Avg win: +{ev_stats['avg_win_sol']:.4f} SOL | Avg loss: -{ev_stats['avg_loss_sol']:.4f} SOL\n"
        f"{ev_emoji} <b>EV/trade: {ev:+.4f} SOL</b>\n"
        f"<b>Total PnL: {ev_stats['total_pnl_sol']:+.4f} SOL</b>"
    )

    notifier.alert(msg)
