"""
Token Quality Scoring System (0-100).

Ranks tokens by combining on-chain, social, and market metrics.
Only tokens scoring above the configured threshold get traded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from api_clients.dexscreener import PairMetrics
from models import SafetyResult, CreatorProfile, LegitimacyResult, EarlyActivityResult

logger = logging.getLogger(__name__)


@dataclass
class QualityScore:
    total: int = 0
    buyers_pts: int = 0
    price_trend_pts: int = 0
    buy_pressure_pts: int = 0
    volume_pts: int = 0
    deployer_pts: int = 0
    rugcheck_pts: int = 0
    holder_pts: int = 0
    legitimacy_pts: int = 0

    def summary(self) -> str:
        return (
            f"score={self.total} "
            f"[buy={self.buyers_pts} trend={self.price_trend_pts} "
            f"pres={self.buy_pressure_pts} vol={self.volume_pts} "
            f"dep={self.deployer_pts} rug={self.rugcheck_pts} "
            f"hold={self.holder_pts} legit={self.legitimacy_pts}]"
        )


def compute_quality_score(
    activity: EarlyActivityResult,
    dex: PairMetrics,
    safety: SafetyResult,
    creator: CreatorProfile,
    legitimacy: LegitimacyResult,
) -> QualityScore:
    """Score a token 0-100 based on all available metrics."""
    qs = QualityScore()

    # 1. Unique buyers (max 20)
    b = activity.unique_buyers
    if b >= 19:
        qs.buyers_pts = 20
    elif b >= 18:
        qs.buyers_pts = 15
    elif b >= 17:
        qs.buyers_pts = 10
    elif b >= 16:
        qs.buyers_pts = 5

    # 2. DexScreener 5m price change (max 15)
    if dex.available:
        pc = dex.price_change_m5
        if pc >= 15:
            qs.price_trend_pts = 15
        elif pc >= 5:
            qs.price_trend_pts = 10
        elif pc > 0:
            qs.price_trend_pts = 5

    # 3. Buy/sell pressure from DexScreener (max 15)
    if dex.available and dex.buy_sell_ratio_m5 > 0:
        r = dex.buy_sell_ratio_m5
        if r >= 2.0:
            qs.buy_pressure_pts = 15
        elif r >= 1.5:
            qs.buy_pressure_pts = 10
        elif r >= 1.0:
            qs.buy_pressure_pts = 5

    # 4. Volume (max 10)
    if dex.available:
        v = dex.volume_h1_usd
        if v >= 5000:
            qs.volume_pts = 10
        elif v >= 1000:
            qs.volume_pts = 5

    # 5. Deployer age (max 10)
    age = creator.deployer_age_days
    if 30 <= age <= 200:
        qs.deployer_pts = 10
    elif 1 <= age < 30 or age > 200:
        qs.deployer_pts = 5

    # 6. Rugcheck score (max 10) — lower is better
    rs = safety.rugcheck_score
    if rs <= 100:
        qs.rugcheck_pts = 10
    elif rs <= 1000:
        qs.rugcheck_pts = 5

    # 7. Top holder % (max 10) — based on pattern analysis
    th = safety.top_holder_pct
    if 0 < th < 22:
        qs.holder_pts = 10
    elif 25 <= th < 30:
        qs.holder_pts = 10
    elif 22 <= th < 25:
        qs.holder_pts = 5

    # 8. Legitimacy score (max 10)
    ls = legitimacy.score
    if ls == 1:
        qs.legitimacy_pts = 10
    elif ls == 2:
        qs.legitimacy_pts = 5

    qs.total = (
        qs.buyers_pts + qs.price_trend_pts + qs.buy_pressure_pts
        + qs.volume_pts + qs.deployer_pts + qs.rugcheck_pts
        + qs.holder_pts + qs.legitimacy_pts
    )

    return qs
