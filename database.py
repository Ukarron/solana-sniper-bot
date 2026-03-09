from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = "data/sniping_bot.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS detected_pools (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    signature           TEXT UNIQUE,
    pool_address        TEXT,
    token_mint          TEXT,
    token_symbol        TEXT,
    token_name          TEXT,
    quote_mint          TEXT,
    dex                 TEXT,
    source              TEXT,
    initial_liquidity   REAL,
    detected_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    rugcheck_score      INTEGER,
    rugcheck_risks      TEXT,
    mint_revoked        BOOLEAN,
    freeze_revoked      BOOLEAN,
    lp_locked           BOOLEAN,
    top_holder_pct      REAL,
    liquidity_mc_ratio  REAL,
    is_token_2022       BOOLEAN,
    honeypot_safe       BOOLEAN,
    honeypot_sell_ratio REAL,
    deployer_address    TEXT,
    deployer_age_days   INTEGER,
    deployer_token_count INTEGER,
    deployer_score      INTEGER,
    legitimacy_score    INTEGER,
    unique_buyers       INTEGER,
    has_whitelist_buyer BOOLEAN,
    has_blacklist_buyer BOOLEAN,
    passed_filters      BOOLEAN,
    skip_reason         TEXT,
    filter_duration_ms  INTEGER,
    bought              BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS trades (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_id             INTEGER REFERENCES detected_pools(id),
    token_mint          TEXT,
    token_symbol        TEXT,
    side                TEXT,
    amount_sol          REAL,
    token_amount        REAL,
    price_per_token     REAL,
    tx_signature        TEXT,
    executed_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    slippage_actual     REAL,
    wallet_address      TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_id             INTEGER REFERENCES detected_pools(id),
    token_mint          TEXT,
    token_symbol        TEXT,
    entry_price         REAL,
    entry_amount_sol    REAL,
    token_amount        REAL,
    remaining_pct       REAL DEFAULT 100,
    status              TEXT,
    opened_at           DATETIME,
    closed_at           DATETIME,
    exit_reason         TEXT,
    pnl_sol             REAL,
    max_price_seen      REAL
);

CREATE TABLE IF NOT EXISTS blacklist (
    address             TEXT PRIMARY KEY,
    reason              TEXT,
    token_involved      TEXT,
    added_at            DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS whitelist (
    address             TEXT PRIMARY KEY,
    win_rate            REAL,
    avg_profit_pct      REAL,
    notes               TEXT,
    added_at            DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date                TEXT PRIMARY KEY,
    pools_detected      INTEGER DEFAULT 0,
    pools_passed        INTEGER DEFAULT 0,
    trades_executed     INTEGER DEFAULT 0,
    wins                INTEGER DEFAULT 0,
    losses              INTEGER DEFAULT 0,
    gross_pnl_sol       REAL DEFAULT 0,
    fees_sol            REAL DEFAULT 0,
    net_pnl_sol         REAL DEFAULT 0,
    best_trade_pnl      REAL DEFAULT 0,
    worst_trade_pnl     REAL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_pools_detected_at ON detected_pools(detected_at);
CREATE INDEX IF NOT EXISTS idx_pools_token_mint ON detected_pools(token_mint);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
"""


class Database:
    def __init__(self, path: str = DB_PATH) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        logger.info("Database initialized at %s", self._path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ── Detected pools ───────────────────────────────────

    async def save_detected_pool(self, **kwargs: Any) -> int:
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        try:
            cursor = await self._conn.execute(
                f"INSERT OR IGNORE INTO detected_pools ({cols}) VALUES ({placeholders})",
                tuple(kwargs.values()),
            )
            await self._conn.commit()
            return cursor.lastrowid or 0
        except Exception as e:
            logger.exception("Failed to save detected pool: %s", e)
            return 0

    async def update_pool_filters(self, pool_id: int, **kwargs: Any) -> None:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        try:
            await self._conn.execute(
                f"UPDATE detected_pools SET {sets} WHERE id = ?",
                (*kwargs.values(), pool_id),
            )
            await self._conn.commit()
        except Exception as e:
            logger.exception("Failed to update pool filters: %s", e)

    async def mark_pool_bought(self, pool_id: int) -> None:
        await self._conn.execute(
            "UPDATE detected_pools SET bought = TRUE WHERE id = ?", (pool_id,)
        )
        await self._conn.commit()

    # ── Trades ────────────────────────────────────────────

    async def save_trade(self, **kwargs: Any) -> int:
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        try:
            cursor = await self._conn.execute(
                f"INSERT INTO trades ({cols}) VALUES ({placeholders})",
                tuple(kwargs.values()),
            )
            await self._conn.commit()
            return cursor.lastrowid or 0
        except Exception as e:
            logger.exception("Failed to save trade: %s", e)
            return 0

    # ── Positions ─────────────────────────────────────────

    async def save_position(self, **kwargs: Any) -> int:
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        try:
            cursor = await self._conn.execute(
                f"INSERT INTO positions ({cols}) VALUES ({placeholders})",
                tuple(kwargs.values()),
            )
            await self._conn.commit()
            return cursor.lastrowid or 0
        except Exception as e:
            logger.exception("Failed to save position: %s", e)
            return 0

    async def update_position(self, position_id: int, **kwargs: Any) -> None:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        try:
            await self._conn.execute(
                f"UPDATE positions SET {sets} WHERE id = ?",
                (*kwargs.values(), position_id),
            )
            await self._conn.commit()
        except Exception as e:
            logger.exception("Failed to update position: %s", e)

    async def get_open_positions(self) -> list[dict]:
        try:
            cursor = await self._conn.execute(
                "SELECT * FROM positions WHERE status = 'open' ORDER BY opened_at"
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.exception("Failed to get open positions: %s", e)
            return []

    # ── Blacklist / Whitelist ─────────────────────────────

    async def add_to_blacklist(self, address: str, reason: str, token: str = "") -> None:
        try:
            await self._conn.execute(
                "INSERT OR IGNORE INTO blacklist (address, reason, token_involved) VALUES (?, ?, ?)",
                (address, reason, token),
            )
            await self._conn.commit()
        except Exception as e:
            logger.exception("Failed to add to blacklist: %s", e)

    async def is_blacklisted(self, address: str) -> bool:
        try:
            cursor = await self._conn.execute(
                "SELECT 1 FROM blacklist WHERE address = ?", (address,)
            )
            return await cursor.fetchone() is not None
        except Exception:
            return False

    async def get_whitelist(self) -> set[str]:
        try:
            cursor = await self._conn.execute("SELECT address FROM whitelist")
            rows = await cursor.fetchall()
            return {r["address"] for r in rows}
        except Exception:
            return set()

    # ── Daily stats ───────────────────────────────────────

    async def increment_daily_stat(self, field: str, value: float = 1) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            await self._conn.execute(
                f"""
                INSERT INTO daily_stats (date, {field}) VALUES (?, ?)
                ON CONFLICT(date) DO UPDATE SET {field} = {field} + excluded.{field}
                """,
                (today, value),
            )
            await self._conn.commit()
        except Exception as e:
            logger.exception("Failed to increment daily stat: %s", e)

    async def get_daily_stats(self, date: str) -> dict | None:
        try:
            cursor = await self._conn.execute(
                "SELECT * FROM daily_stats WHERE date = ?", (date,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.exception("Failed to get daily stats: %s", e)
            return None

    async def get_ev_stats(self, days: int = 7) -> dict | None:
        """Compute EV statistics from closed positions over the last N days."""
        try:
            cursor = await self._conn.execute(
                """
                SELECT pnl_sol FROM positions
                WHERE status = 'closed'
                  AND closed_at > datetime('now', ?)
                """,
                (f"-{days} days",),
            )
            rows = await cursor.fetchall()
            if not rows:
                return None

            pnls = [r["pnl_sol"] for r in rows]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            n = len(pnls)
            win_rate = len(wins) / n if n else 0.0
            avg_win = sum(wins) / len(wins) if wins else 0.0
            avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
            ev = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if n else 0.0

            return {
                "total_trades": n,
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": win_rate,
                "avg_win_sol": avg_win,
                "avg_loss_sol": avg_loss,
                "ev_per_trade": ev,
                "total_pnl_sol": sum(pnls),
            }
        except Exception as e:
            logger.exception("Failed to get EV stats: %s", e)
            return None


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db
