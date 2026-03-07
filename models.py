from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class PoolSource(Enum):
    PUMPSWAP = "PumpSwap"
    RAYDIUM = "Raydium"
    PUMPFUN_MIGRATION = "PumpFunMigration"


class PositionStatus(Enum):
    OPEN = "open"
    PARTIALLY_CLOSED = "partially_closed"
    CLOSED = "closed"


class ExitReason(Enum):
    TP1 = "tp1"
    TP2 = "tp2"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    LP_DRAIN = "lp_drain"
    TIMING_HONEYPOT = "timing_honeypot"
    EMERGENCY = "emergency"
    MAX_HOLD_TIME = "max_hold_time"
    MANUAL = "manual"


@dataclass
class PoolInfo:
    """Detected new liquidity pool."""
    signature: str
    pool_address: str
    token_mint: str
    token_symbol: str = ""
    token_name: str = ""
    quote_mint: str = ""
    source: PoolSource = PoolSource.PUMPSWAP
    initial_liquidity_sol: float = 0.0
    detected_at: float = field(default_factory=time.time)


@dataclass
class SafetyResult:
    safe: bool
    rugcheck_score: int = 0
    rugcheck_risks: list[str] = field(default_factory=list)
    mint_revoked: bool = False
    freeze_revoked: bool = False
    lp_locked: bool = False
    top_holder_pct: float = 0.0
    liquidity_mc_ratio: float = 0.0
    is_token_2022: bool = False
    honeypot_safe: bool = False
    honeypot_sell_ratio: float = 0.0
    reason: str = ""


@dataclass
class CreatorProfile:
    deployer_address: str = ""
    deployer_age_days: int = 0
    token_count: int = 0
    score: int = 0
    is_blacklisted: bool = False
    reason: str = ""


@dataclass
class LegitimacyResult:
    score: int = 0
    has_website: bool = False
    has_twitter: bool = False
    has_telegram: bool = False
    is_copycat: bool = False
    is_dexscreener_boosted: bool = False
    reason: str = ""


@dataclass
class EarlyActivityResult:
    unique_buyers: int = 0
    has_blacklisted_buyer: bool = False
    whitelist_buyers: list[str] = field(default_factory=list)
    volume_pattern: str = ""
    holder_signal: str = "neutral"
    passed: bool = False
    reason: str = ""


@dataclass
class FilterLog:
    """Complete record of all filter results for a detected pool."""
    pool: PoolInfo | None = None
    safety: SafetyResult | None = None
    creator: CreatorProfile | None = None
    legitimacy: LegitimacyResult | None = None
    early_activity: EarlyActivityResult | None = None
    ev_positive: bool = False
    macro_multiplier: float = 1.0
    passed_all: bool = False
    skip_reason: str = ""
    filter_duration_ms: int = 0


@dataclass
class TradeRecord:
    token_mint: str
    token_symbol: str = ""
    side: str = ""
    amount_sol: float = 0.0
    token_amount: float = 0.0
    price_per_token: float = 0.0
    tx_signature: str = ""
    executed_at: float = field(default_factory=time.time)
    slippage_actual: float = 0.0
    wallet_address: str = ""


@dataclass
class Position:
    pool_id: int = 0
    token_mint: str = ""
    token_symbol: str = ""
    entry_price: float = 0.0
    entry_amount_sol: float = 0.0
    token_amount: float = 0.0
    remaining_pct: float = 100.0
    status: PositionStatus = PositionStatus.OPEN
    opened_at: float = field(default_factory=time.time)
    closed_at: float = 0.0
    exit_reason: ExitReason | None = None
    pnl_sol: float = 0.0
    max_price_seen: float = 0.0

    # Trailing state
    tp1_triggered: bool = False
    tp1_max_price: float = 0.0
    tp2_triggered: bool = False
    tp2_max_price: float = 0.0
    trailing_stop_active: bool = False


@dataclass
class MacroState:
    btc_dominance_falling: bool = False
    solana_tvl_growth_pct: float = 0.0
    sol_uptrend: bool = False
    risk_multiplier: float = 1.0
    updated_at: float = field(default_factory=time.time)
