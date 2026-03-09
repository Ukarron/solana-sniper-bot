from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_float(key: str, default: float = 0.0) -> float:
    raw = os.getenv(key, str(default))
    try:
        return float(raw)
    except (ValueError, TypeError):
        log.warning("Invalid float for %s=%r, using default %s", key, raw, default)
        return default


def _env_int(key: str, default: int = 0) -> int:
    raw = os.getenv(key, str(default))
    try:
        return int(float(raw))
    except (ValueError, TypeError):
        log.warning("Invalid int for %s=%r, using default %s", key, raw, default)
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


@dataclass
class Config:
    # ── Program IDs (constants) ──────────────────────────
    RAYDIUM_AMM_V4: str = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
    PUMPFUN_PROGRAM: str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    PUMPSWAP_AMM: str = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
    PUMPFUN_MIGRATION: str = "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"
    JUPITER_V6: str = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
    SPL_TOKEN: str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    TOKEN_2022_PROGRAM: str = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
    SOL_MINT: str = "So11111111111111111111111111111111111111112"
    USDC_MINT: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    BURN_ADDRESS: str = "1nc1nerator11111111111111111111111111111111"

    # ── RPC ───────────────────────────────────────────────
    rpc_http: str = ""
    rpc_wss: str = ""
    helius_api_key: str = ""

    # ── Wallet ────────────────────────────────────────────
    private_key: str = ""

    # ── Safety filters ────────────────────────────────────
    min_liquidity_sol: float = 10.0
    max_top_holder_pct: float = 50.0
    min_liquidity_mc_ratio: float = 0.10
    max_rugcheck_score: int = 50000
    skip_token_2022_hooks: bool = True
    require_mint_revoked: bool = True
    require_freeze_revoked: bool = True
    require_lp_locked: bool = True

    # ── Honeypot check timing ──────────────────────────────
    honeypot_initial_delay: int = 30
    honeypot_retry_delay: int = 15
    honeypot_max_retries: int = 3

    # ── Creator analysis ──────────────────────────────────
    min_deployer_age_days: int = 0
    max_deployer_tokens: int = 50

    # ── Legitimacy filter ─────────────────────────────────
    min_legitimacy_score: int = 0
    website_min_content_length: int = 500
    website_check_timeout_sec: int = 5

    # ── Early activity filter ─────────────────────────────
    wait_before_analysis_sec: int = 15
    min_unique_buyers: int = 3
    max_single_buyer_pct: float = 50.0

    # ── Trading ───────────────────────────────────────────
    buy_amount_sol: float = 0.1
    max_slippage_bps: int = 300
    jito_tip_lamports: int = 100_000
    tx_timeout_sec: int = 30
    tx_retries: int = 3
    use_jito: bool = True

    # ── Take-profits (trailing) ───────────────────────────
    tp1_trigger: float = 2.0
    tp1_trailing_pct: float = 20.0
    tp1_sell_pct: float = 40.0
    tp2_trigger: float = 4.0
    tp2_trailing_pct: float = 25.0
    tp2_sell_pct: float = 30.0
    remaining_pct: float = 30.0

    # ── Stop-losses (trailing) ────────────────────────────
    stop_loss_pct: float = 35.0
    trailing_stop_activation: float = 1.8
    trailing_stop_pct: float = 30.0
    emergency_lp_drop_pct: float = 25.0
    max_hold_time_hours: int = 12

    # ── Risk management ───────────────────────────────────
    max_single_trade_pct: float = 2.0
    max_total_exposure_pct: float = 30.0
    min_ev_threshold: float = 0.0
    estimated_win_rate: float = 0.25

    # ── Macro filter ──────────────────────────────────────
    macro_check_interval_sec: int = 3600
    tvl_growth_threshold_pct: float = 60.0
    macro_risk_multiplier_bear: float = 0.5
    macro_risk_multiplier_bull: float = 1.5

    # ── Telegram ──────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── Misc ──────────────────────────────────────────────
    price_check_interval_sec: int = 5
    log_level: str = "INFO"
    paper_trading: bool = True

    # ── API URLs / keys ──────────────────────────────────
    jupiter_api_key: str = ""
    jupiter_quote_url: str = "https://api.jup.ag/swap/v1/quote"
    jupiter_swap_url: str = "https://api.jup.ag/swap/v1/swap"
    rugcheck_base_url: str = "https://api.rugcheck.xyz/v1"
    jito_endpoint: str = "https://mainnet.block-engine.jito.wtf"

    # ── WebSocket reconnect ───────────────────────────────
    ws_base_delay: float = 1.0
    ws_max_delay: float = 60.0
    ws_ping_interval: int = 30
    ws_ping_timeout: int = 10

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            rpc_http=_env("RPC_HTTP"),
            rpc_wss=_env("RPC_WSS"),
            helius_api_key=_env("HELIUS_API_KEY"),
            private_key=_env("PRIVATE_KEY"),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
            buy_amount_sol=_env_float("BUY_AMOUNT_SOL", 0.5),
            max_slippage_bps=_env_int("MAX_SLIPPAGE_BPS", 500),
            jito_tip_lamports=_env_int("JITO_TIP_LAMPORTS", 100_000),
            min_liquidity_sol=_env_float("MIN_LIQUIDITY_SOL", 10.0),
            stop_loss_pct=_env_float("STOP_LOSS_PCT", 20.0),
            log_level=_env("LOG_LEVEL", "INFO"),
            paper_trading=_env_bool("PAPER_TRADING", True),
            jupiter_api_key=_env("JUPITER_API_KEY"),
            max_rugcheck_score=_env_int("MAX_RUGCHECK_SCORE", 50000),
            max_top_holder_pct=_env_float("MAX_TOP_HOLDER_PCT", 50.0),
            honeypot_initial_delay=_env_int("HONEYPOT_INITIAL_DELAY", 30),
            honeypot_retry_delay=_env_int("HONEYPOT_RETRY_DELAY", 15),
            honeypot_max_retries=_env_int("HONEYPOT_MAX_RETRIES", 3),
        )

    def validate(self) -> None:
        """Fail fast if critical settings are missing."""
        assert self.rpc_http, "RPC_HTTP is required in .env"
        assert self.rpc_wss, "RPC_WSS is required in .env"
        if not self.paper_trading:
            assert self.private_key, "PRIVATE_KEY is required for live trading"
        if not self.paper_trading:
            assert self.telegram_bot_token, "TELEGRAM_BOT_TOKEN required for live trading"
            assert self.telegram_chat_id, "TELEGRAM_CHAT_ID required for live trading"
