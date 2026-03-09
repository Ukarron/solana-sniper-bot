"""
КРОК 6: Position Manager — trailing TP/SL, LP drain detection, emergency exit.

Combined scheme:
  1. Fixed stop-loss: -20% from entry (always active, emergency floor)
  2. Trailing stop: activates at +50%, 25% from maximum
  3. Trailing TP1: trigger at 2x, trail 15%, sell 50%
  4. Trailing TP2: trigger at 5x, trail 20%, sell 25%
  5. Moon bag: 25% held until trailing stop or fixed stop
"""

from __future__ import annotations

import asyncio
import html
import logging
import time

from config import Config
from models import TradeRecord, ExitReason
from trade_executor import TradeExecutor
from safety_filter import recheck_honeypot_after_buy
from database import get_db
from notifier import get_notifier
from api_clients.jupiter import JupiterClient

logger = logging.getLogger(__name__)


class PositionManager:
    def __init__(self, cfg: Config, executor: TradeExecutor) -> None:
        self.cfg = cfg
        self.executor = executor
        self._positions: dict[int, _TrackedPosition] = {}
        self._jupiter = JupiterClient(
            api_key=cfg.jupiter_api_key,
            quote_url=cfg.jupiter_quote_url,
            swap_url=cfg.jupiter_swap_url,
        )

    async def track_position(self, pos_id: int, trade: TradeRecord) -> None:
        """Start tracking a new position after buy."""
        self._positions[pos_id] = _TrackedPosition(
            pos_id=pos_id,
            token_mint=trade.token_mint,
            token_symbol=trade.token_symbol,
            entry_price=trade.price_per_token,
            entry_amount_sol=trade.amount_sol,
            token_amount=trade.token_amount,
            wallet_address=trade.wallet_address,
            remaining_pct=100.0,
            max_price=trade.price_per_token,
        )

        # Schedule honeypot recheck as background task
        asyncio.create_task(
            self._honeypot_recheck(pos_id, trade.token_mint),
            name=f"honeypot-recheck-{pos_id}",
        )

    async def run_loop(self) -> None:
        """Main loop: check all positions at regular intervals."""
        while True:
            try:
                for pos_id in list(self._positions.keys()):
                    pos = self._positions.get(pos_id)
                    if pos and pos.remaining_pct > 0:
                        await self._check_position(pos)
            except Exception as e:
                logger.exception("Position manager loop error: %s", e)
            await asyncio.sleep(self.cfg.price_check_interval_sec)

    async def _check_position(self, pos: _TrackedPosition) -> None:
        """Run all checks on a single position."""
        current_sol = await self._get_position_sol_value(pos)
        if current_sol is None or current_sol <= 0:
            logger.debug("No SOL value for %s (remaining=%.0f%%)", pos.token_mint[:12], pos.remaining_pct)
            return

        if current_sol > pos.max_sol_value:
            pos.max_sol_value = current_sol

        multiplier = current_sol / pos.entry_amount_sol if pos.entry_amount_sol > 0 else 0
        logger.debug(
            "POS %s: %.4f SOL (%.2fx) max=%.4f remaining=%.0f%%",
            pos.token_mint[:12], current_sol, multiplier, pos.max_sol_value, pos.remaining_pct,
        )
        db = get_db()
        notifier = get_notifier()

        # --- Fixed stop-loss (always active) ---
        loss_pct = (1 - multiplier) * 100
        if loss_pct >= self.cfg.stop_loss_pct:
            await self._execute_sell(pos, 100, ExitReason.STOP_LOSS)
            return

        # --- Trailing stop (activates after +50%) ---
        if multiplier >= self.cfg.trailing_stop_activation:
            trailing_floor = pos.max_sol_value * (1 - self.cfg.trailing_stop_pct / 100)
            if current_sol <= trailing_floor:
                await self._execute_sell(pos, pos.remaining_pct, ExitReason.TRAILING_STOP)
                return

        # --- Trailing TP1 (trigger at 2x) ---
        if not pos.tp1_sold and multiplier >= self.cfg.tp1_trigger:
            if not pos.tp1_triggered:
                pos.tp1_triggered = True
                pos.tp1_max_sol = current_sol
                logger.info("TP1 triggered for %s at %.2fx", pos.token_symbol, multiplier)

            if pos.tp1_triggered:
                if current_sol > pos.tp1_max_sol:
                    pos.tp1_max_sol = current_sol
                tp1_sell_level = pos.tp1_max_sol * (1 - self.cfg.tp1_trailing_pct / 100)
                if current_sol <= tp1_sell_level:
                    await self._execute_sell(pos, self.cfg.tp1_sell_pct, ExitReason.TP1)
                    pos.tp1_sold = True

        # --- Trailing TP2 (trigger at 5x) ---
        if not pos.tp2_sold and multiplier >= self.cfg.tp2_trigger:
            if not pos.tp2_triggered:
                pos.tp2_triggered = True
                pos.tp2_max_sol = current_sol
                logger.info("TP2 triggered for %s at %.2fx", pos.token_symbol, multiplier)

            if pos.tp2_triggered:
                if current_sol > pos.tp2_max_sol:
                    pos.tp2_max_sol = current_sol
                tp2_sell_level = pos.tp2_max_sol * (1 - self.cfg.tp2_trailing_pct / 100)
                if current_sol <= tp2_sell_level:
                    await self._execute_sell(pos, self.cfg.tp2_sell_pct, ExitReason.TP2)
                    pos.tp2_sold = True

        # --- Max hold time ---
        hold_hours = (time.time() - pos.opened_at) / 3600
        if hold_hours >= self.cfg.max_hold_time_hours:
            logger.info("Max hold time reached for %s", pos.token_symbol)
            await self._execute_sell(pos, pos.remaining_pct, ExitReason.MAX_HOLD_TIME)

        # Update DB
        await db.update_position(pos.pos_id, max_price_seen=pos.max_sol_value)

    async def _execute_sell(
        self, pos: _TrackedPosition, sell_pct: float, reason: ExitReason
    ) -> None:
        """Sell a percentage of the position."""
        sell_tokens = int(pos.token_amount * (sell_pct / 100) * (pos.remaining_pct / 100))
        if sell_tokens <= 0:
            return

        notifier = get_notifier()
        db = get_db()

        trade = await self.executor.sell(
            pos.token_mint, sell_tokens, pos.wallet_address
        )

        if trade and trade.tx_signature:
            pos.remaining_pct -= sell_pct
            if pos.remaining_pct <= 0:
                pos.remaining_pct = 0

            pnl = trade.amount_sol - (pos.entry_amount_sol * sell_pct / 100)
            pos.total_pnl += pnl
            is_win = pnl > 0

            await db.save_trade(
                pool_id=0,
                token_mint=trade.token_mint,
                token_symbol=pos.token_symbol,
                side=trade.side,
                amount_sol=trade.amount_sol,
                token_amount=trade.token_amount,
                tx_signature=trade.tx_signature,
                wallet_address=trade.wallet_address,
            )

            status = "closed" if pos.remaining_pct <= 0 else "open"
            await db.update_position(
                pos.pos_id,
                remaining_pct=pos.remaining_pct,
                status=status,
                exit_reason=reason.value,
                pnl_sol=pos.total_pnl,
                closed_at=time.time() if status == "closed" else None,
            )

            if is_win:
                await db.increment_daily_stat("wins")
            else:
                await db.increment_daily_stat("losses")

            emoji = "💰" if is_win else "🔴"
            sym = html.escape(pos.token_symbol or "???")
            dex_link = f"https://dexscreener.com/solana/{pos.token_mint}"
            notifier.alert(
                f"{emoji} <b>{reason.value.upper()}</b> {sym}\n"
                f"Sold {sell_pct:.0f}% | PnL: {pnl:+.4f} SOL\n"
                f"Remaining: {pos.remaining_pct:.0f}%\n"
                f'<a href="{dex_link}">DexScreener</a>'
            )

            if pos.remaining_pct <= 0:
                self._positions.pop(pos.pos_id, None)

            logger.info(
                "%s %s: sold %.0f%% pnl=%+.4f SOL remaining=%.0f%%",
                reason.value, pos.token_symbol, sell_pct, pnl, pos.remaining_pct,
            )

    async def _honeypot_recheck(self, pos_id: int, token_mint: str) -> None:
        """Background task: recheck honeypot after 90s delay."""
        try:
            result = await recheck_honeypot_after_buy(token_mint, self.cfg, delay_seconds=90)
            if not result.get("safe", True):
                pos = self._positions.get(pos_id)
                if pos and pos.remaining_pct > 0:
                    logger.warning("TIMING HONEYPOT detected for %s!", token_mint[:12])
                    await self._execute_sell(pos, pos.remaining_pct, ExitReason.TIMING_HONEYPOT)
        except Exception as e:
            logger.debug("Honeypot recheck error: %s", e)

    async def _get_position_sol_value(self, pos: _TrackedPosition) -> float | None:
        """Get current SOL value of the remaining position via Jupiter quote."""
        remaining_tokens = int(
            pos.token_amount * (pos.remaining_pct / 100)
        )
        if remaining_tokens <= 0:
            return None
        try:
            quote = await self._jupiter.get_quote(
                pos.token_mint,
                self.cfg.SOL_MINT,
                remaining_tokens,
                self.cfg.max_slippage_bps,
            )
            if not quote or not quote.get("outAmount"):
                return None
            sol_out = int(quote["outAmount"]) / 1_000_000_000
            return sol_out
        except Exception as e:
            logger.debug("Position value check failed for %s: %s", pos.token_mint[:12], e)
            return None


class _TrackedPosition:
    """Internal position tracking state."""

    def __init__(
        self,
        pos_id: int,
        token_mint: str,
        token_symbol: str,
        entry_price: float,
        entry_amount_sol: float,
        token_amount: float,
        wallet_address: str,
        remaining_pct: float = 100.0,
        max_price: float = 0.0,
    ) -> None:
        self.pos_id = pos_id
        self.token_mint = token_mint
        self.token_symbol = token_symbol
        self.entry_price = entry_price
        self.entry_amount_sol = entry_amount_sol
        self.token_amount = token_amount
        self.wallet_address = wallet_address
        self.remaining_pct = remaining_pct
        self.max_sol_value = entry_amount_sol
        self.opened_at = time.time()

        self.total_pnl = 0.0

        # Trailing TP state (tracked in SOL value)
        self.tp1_triggered = False
        self.tp1_max_sol = 0.0
        self.tp1_sold = False
        self.tp2_triggered = False
        self.tp2_max_sol = 0.0
        self.tp2_sold = False
