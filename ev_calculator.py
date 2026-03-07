"""
КРОК 4.5: EV Filter — Expected Value calculation.

EV = (P_win * avg_profit) - (P_loss * avg_loss)
If EV <= 0 → skip all trades until parameters improve.

Starts with configured estimates, auto-updates from database after 30+ trades.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from database import get_db

logger = logging.getLogger(__name__)


@dataclass
class EVCalculator:
    win_rate: float
    avg_profit_pct: float
    avg_loss_pct: float

    @property
    def ev(self) -> float:
        return (self.win_rate * self.avg_profit_pct) - (
            (1 - self.win_rate) * self.avg_loss_pct
        )

    @property
    def is_profitable(self) -> bool:
        return self.ev > 0

    @property
    def min_win_rate(self) -> float:
        """Minimum win rate for breakeven at current TP/SL."""
        total = self.avg_profit_pct + self.avg_loss_pct
        return self.avg_loss_pct / total if total > 0 else 1.0

    async def update_from_db(self, days: int = 7) -> bool:
        """Update win rate and avg profit/loss from real trade data.

        Returns True if enough data was available (30+ trades).
        """
        db = get_db()
        stats = await db.get_ev_stats(days=days)
        if not stats or stats["total_trades"] < 30:
            return False

        self.win_rate = stats["win_rate"]
        if stats["avg_win_sol"] > 0 and stats["avg_loss_sol"] > 0:
            self.avg_profit_pct = stats["avg_win_sol"] * 100
            self.avg_loss_pct = stats["avg_loss_sol"] * 100

        logger.info(
            "EV updated from DB: win_rate=%.1f%% EV=%.1f profit=%.1f loss=%.1f",
            self.win_rate * 100, self.ev, self.avg_profit_pct, self.avg_loss_pct,
        )
        return True
