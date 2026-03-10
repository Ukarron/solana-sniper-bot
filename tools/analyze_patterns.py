"""
Direct pattern analysis from our bot's trading data.
Identifies what separates winners from losers without external API calls.

Run: python tools/analyze_patterns.py
"""
import json
import statistics
from collections import Counter

# Our pool filter data for bought tokens (from VM database)
POOLS = [{"id": 525, "token_symbol": "", "token_name": "", "initial_liquidity": 0.0, "rugcheck_score": 1, "top_holder_pct": 23.9, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 18}, {"id": 527, "token_symbol": "", "token_name": "", "initial_liquidity": 0.0, "rugcheck_score": 501, "top_holder_pct": 21.9, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 2, "unique_buyers": 12}, {"id": 529, "token_symbol": "", "token_name": "", "initial_liquidity": 0.0, "rugcheck_score": 1, "top_holder_pct": 21.6, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 16}, {"id": 535, "token_symbol": "", "token_name": "", "initial_liquidity": 0.0, "rugcheck_score": 1, "top_holder_pct": 22.4, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 13}, {"id": 539, "token_symbol": "", "token_name": "", "initial_liquidity": 0.0, "rugcheck_score": 1, "top_holder_pct": 27.1, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 17}, {"id": 540, "token_symbol": "", "token_name": "", "initial_liquidity": 0.0, "rugcheck_score": 1, "top_holder_pct": 23.8, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 2, "unique_buyers": 11}, {"id": 541, "token_symbol": "", "token_name": "", "initial_liquidity": 0.0, "rugcheck_score": 1, "top_holder_pct": 34.6, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 18}, {"id": 545, "token_symbol": "", "token_name": "", "initial_liquidity": 0.0, "rugcheck_score": 1, "top_holder_pct": 8.4, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 14}, {"id": 546, "token_symbol": "", "token_name": "", "initial_liquidity": 0.0, "rugcheck_score": 1, "top_holder_pct": 25.9, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 16}, {"id": 548, "token_symbol": "", "token_name": "", "initial_liquidity": 0.0, "rugcheck_score": 501, "top_holder_pct": 20.7, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 17}, {"id": 549, "token_symbol": "", "token_name": "", "initial_liquidity": 0.0, "rugcheck_score": 0, "top_holder_pct": 24.0, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 14}, {"id": 550, "token_symbol": "", "token_name": "", "initial_liquidity": 0.0, "rugcheck_score": 0, "top_holder_pct": 22.6, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 13}, {"id": 556, "token_symbol": "", "token_name": "", "initial_liquidity": 0.0, "rugcheck_score": 1, "top_holder_pct": 22.4, "deployer_age_days": 0, "deployer_token_count": 1, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 19},
{"id": 570, "token_symbol": "keypo", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.3, "deployer_age_days": 15, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 2, "unique_buyers": 17},
{"id": 572, "token_symbol": "ANI", "initial_liquidity": 85.0, "rugcheck_score": 0, "top_holder_pct": 22.9, "deployer_age_days": 12, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 11},
{"id": 573, "token_symbol": "", "initial_liquidity": 100.0, "rugcheck_score": 10501, "top_holder_pct": 0.0, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 0, "legitimacy_score": 1, "unique_buyers": 19},
{"id": 575, "token_symbol": "PW", "initial_liquidity": 84.1, "rugcheck_score": 1, "top_holder_pct": 25.4, "deployer_age_days": 233, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 15},
{"id": 577, "token_symbol": "LIFESAVING", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.7, "deployer_age_days": 53, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 18},
{"id": 580, "token_symbol": "parasites", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 21.5, "deployer_age_days": 7, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 18},
{"id": 582, "token_symbol": "MYRACYL", "initial_liquidity": 4724.0, "rugcheck_score": 1, "top_holder_pct": 21.6, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 2, "unique_buyers": 11},
{"id": 584, "token_symbol": "MIRACIL", "initial_liquidity": 4730.0, "rugcheck_score": 1, "top_holder_pct": 24.4, "deployer_age_days": 8, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 16},
{"id": 601, "token_symbol": "creature", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 27.4, "deployer_age_days": 49, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 19},
{"id": 605, "token_symbol": "freedom", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 26.1, "deployer_age_days": 348, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 14},
{"id": 609, "token_symbol": "BENJAMIN", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 22.5, "deployer_age_days": 52, "deployer_token_count": 4, "deployer_score": 1, "legitimacy_score": 1, "unique_buyers": 19},
{"id": 617, "token_symbol": "EYEBROWS", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.8, "deployer_age_days": 45, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 12},
{"id": 618, "token_symbol": "Password", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.2, "deployer_age_days": 11, "deployer_token_count": 11, "deployer_score": 0, "legitimacy_score": 2, "unique_buyers": 12},
{"id": 622, "token_symbol": "Pleco", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.0, "deployer_age_days": 98, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 14},
{"id": 623, "token_symbol": "NowClaw", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 20.8, "deployer_age_days": 3, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 13},
{"id": 627, "token_symbol": "INTROVERT", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 23.2, "deployer_age_days": 30, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 14},
{"id": 629, "token_symbol": "Bichi", "initial_liquidity": 85.0, "rugcheck_score": 2019, "top_holder_pct": 22.2, "deployer_age_days": 8, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 19},
{"id": 632, "token_symbol": "SPACE", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.2, "deployer_age_days": 198, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 16},
{"id": 636, "token_symbol": "$MWH", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.4, "deployer_age_days": 37, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 13},
{"id": 638, "token_symbol": "BTP", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.8, "deployer_age_days": 3, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 17},
{"id": 639, "token_symbol": "UXR", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 23.4, "deployer_age_days": 819, "deployer_token_count": 1, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 16},
{"id": 640, "token_symbol": "TREN", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.8, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 10},
{"id": 642, "token_symbol": "NemoClaw", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 24.9, "deployer_age_days": 2, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 16},
{"id": 643, "token_symbol": "PO", "initial_liquidity": 20.9, "rugcheck_score": 12871, "top_holder_pct": 20.7, "deployer_age_days": 37, "deployer_token_count": 12, "deployer_score": 1, "legitimacy_score": 1, "unique_buyers": 6},
{"id": 644, "token_symbol": "MOG", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 22.4, "deployer_age_days": 19, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 12},
{"id": 646, "token_symbol": "believe", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 20.8, "deployer_age_days": 85, "deployer_token_count": 3, "deployer_score": 3, "legitimacy_score": 2, "unique_buyers": 11},
{"id": 648, "token_symbol": "NOVAH", "initial_liquidity": 85.0, "rugcheck_score": 0, "top_holder_pct": 22.3, "deployer_age_days": 1, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 2, "unique_buyers": 17},
{"id": 649, "token_symbol": "italianrot", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 22.4, "deployer_age_days": 19, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 14},
{"id": 650, "token_symbol": "Wei", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.6, "deployer_age_days": 2, "deployer_token_count": 2, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 19},
{"id": 652, "token_symbol": "REVM", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 22.1, "deployer_age_days": 90, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 2, "unique_buyers": 17},
{"id": 654, "token_symbol": "MIDNIGHT", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 22.1, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 16},
{"id": 656, "token_symbol": "Hamster", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 22.6, "deployer_age_days": 40, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 13},
{"id": 665, "token_symbol": "REDEMPTION", "initial_liquidity": 5091.4, "rugcheck_score": 1, "top_holder_pct": 21.4, "deployer_age_days": 31, "deployer_token_count": 1, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 15},
{"id": 670, "token_symbol": "saddog", "initial_liquidity": 85.0, "rugcheck_score": 2401, "top_holder_pct": 23.0, "deployer_age_days": 13, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 16},
{"id": 671, "token_symbol": "FLYWIRE", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 24.6, "deployer_age_days": 44, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 3, "unique_buyers": 16},
{"id": 677, "token_symbol": "ROBOT", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 28.0, "deployer_age_days": 16, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 15},
{"id": 679, "token_symbol": "TROK", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 28.1, "deployer_age_days": 5, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 16},
{"id": 682, "token_symbol": "OILFUL", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 22.9, "deployer_age_days": 115, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 2, "unique_buyers": 13},
{"id": 684, "token_symbol": "2024", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.4, "deployer_age_days": 27, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 16},
{"id": 686, "token_symbol": "KOKO", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 25.6, "deployer_age_days": 2, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 3, "unique_buyers": 14},
{"id": 689, "token_symbol": "PumpLiquid", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.9, "deployer_age_days": 11, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 2, "unique_buyers": 16},
{"id": 696, "token_symbol": "Dragon", "initial_liquidity": 85.0, "rugcheck_score": 7701, "top_holder_pct": 21.6, "deployer_age_days": 91, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 15},
{"id": 701, "token_symbol": "Felicette", "initial_liquidity": 85.0, "rugcheck_score": 0, "top_holder_pct": 24.1, "deployer_age_days": 71, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 12},
{"id": 703, "token_symbol": "NailPigeon", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.6, "deployer_age_days": 35, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 19},
{"id": 705, "token_symbol": "STRAIT", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 0.0, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 0, "legitimacy_score": 1, "unique_buyers": 18},
{"id": 706, "token_symbol": "MARIO", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 23.7, "deployer_age_days": 12, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 3, "unique_buyers": 19},
{"id": 710, "token_symbol": "Gyutto", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 31.2, "deployer_age_days": 335, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 17},
{"id": 713, "token_symbol": "5", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 27.7, "deployer_age_days": 173, "deployer_token_count": 50, "deployer_score": 1, "legitimacy_score": 1, "unique_buyers": 15},
{"id": 717, "token_symbol": "OILROY", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 27.1, "deployer_age_days": 1, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 12},
{"id": 718, "token_symbol": "AWESOME", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 22.9, "deployer_age_days": 341, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 2, "unique_buyers": 15},
{"id": 719, "token_symbol": "RKITTY", "initial_liquidity": 85.0, "rugcheck_score": 5301, "top_holder_pct": 24.9, "deployer_age_days": 1, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 7},
{"id": 725, "token_symbol": "BOOK", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 22.2, "deployer_age_days": 1, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 19},
{"id": 726, "token_symbol": "SOS", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 21.2, "deployer_age_days": 12, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 15},
{"id": 727, "token_symbol": "Nami", "initial_liquidity": 85.0, "rugcheck_score": 3977, "top_holder_pct": 23.2, "deployer_age_days": 19, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 2, "unique_buyers": 19},
{"id": 728, "token_symbol": "GARY", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.8, "deployer_age_days": 12, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 18},
{"id": 731, "token_symbol": "ARP", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 24.7, "deployer_age_days": 63, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 14},
{"id": 754, "token_symbol": "SHEEP", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.4, "deployer_age_days": 173, "deployer_token_count": 7, "deployer_score": 1, "legitimacy_score": 1, "unique_buyers": 16},
{"id": 755, "token_symbol": "AgentHub", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 22.9, "deployer_age_days": 2, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 19},
{"id": 759, "token_symbol": "SANO", "initial_liquidity": 85.0, "rugcheck_score": 4656, "top_holder_pct": 30.0, "deployer_age_days": 1, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 11},
{"id": 762, "token_symbol": "DREAM", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 23.2, "deployer_age_days": 41, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 18},
{"id": 768, "token_symbol": "BULL", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 21.7, "deployer_age_days": 402, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 17},
{"id": 770, "token_symbol": "EXCESSION", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.1, "deployer_age_days": 53, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 2, "unique_buyers": 13},
{"id": 772, "token_symbol": "BIAO", "initial_liquidity": 85.0, "rugcheck_score": 2401, "top_holder_pct": 28.4, "deployer_age_days": 15, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 15},
{"id": 779, "token_symbol": "KING", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 37.3, "deployer_age_days": 21, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 14},
{"id": 788, "token_symbol": "BIX", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 20.7, "deployer_age_days": 11, "deployer_token_count": 11, "deployer_score": 0, "legitimacy_score": 2, "unique_buyers": 16},
{"id": 790, "token_symbol": "GolemCode", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 24.7, "deployer_age_days": 99, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 2, "unique_buyers": 19},
{"id": 793, "token_symbol": "Scout", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 20.7, "deployer_age_days": 20, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 17},
{"id": 794, "token_symbol": "treasure", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 22.1, "deployer_age_days": 42, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 8},
{"id": 806, "token_symbol": "CLUB", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 20.9, "deployer_age_days": 108, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 14},
{"id": 808, "token_symbol": "Pochita", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 22.3, "deployer_age_days": 22, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 16},
{"id": 816, "token_symbol": "Birdie", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 24.0, "deployer_age_days": 1, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 16},
{"id": 831, "token_symbol": "GameTheory", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 20.8, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 17},
{"id": 833, "token_symbol": "DISTORTED", "initial_liquidity": 85.0, "rugcheck_score": 0, "top_holder_pct": 23.2, "deployer_age_days": 55, "deployer_token_count": 2, "deployer_score": 3, "legitimacy_score": 2, "unique_buyers": 15},
{"id": 851, "token_symbol": "CTO", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.1, "deployer_age_days": 244, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 17},
{"id": 856, "token_symbol": "SporeMesh", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.4, "deployer_age_days": 11, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 18},
{"id": 860, "token_symbol": "clawcoin", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 21.7, "deployer_age_days": 1, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 2, "unique_buyers": 17},
{"id": 868, "token_symbol": "BallDog", "initial_liquidity": 3562.9, "rugcheck_score": 1, "top_holder_pct": 26.3, "deployer_age_days": 6, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 9},
{"id": 872, "token_symbol": "PH", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 20.7, "deployer_age_days": 6, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 18},
{"id": 873, "token_symbol": "MWO", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 25.2, "deployer_age_days": 0, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 17},
{"id": 878, "token_symbol": "Flork", "initial_liquidity": 85.0, "rugcheck_score": 501, "top_holder_pct": 44.9, "deployer_age_days": 3, "deployer_token_count": 0, "deployer_score": 2, "legitimacy_score": 1, "unique_buyers": 16},
{"id": 882, "token_symbol": "archie", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 22.0, "deployer_age_days": 672, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 17},
{"id": 883, "token_symbol": "69", "initial_liquidity": 85.0, "rugcheck_score": 1, "top_holder_pct": 23.4, "deployer_age_days": 91, "deployer_token_count": 0, "deployer_score": 3, "legitimacy_score": 1, "unique_buyers": 13}
]

# Positions with PnL (pool_id -> pnl_sol mapping)
POSITIONS_PNL = {
    525: -0.100, 527: 0.258, 529: -0.217, 535: -0.130, 539: 0.269, 540: -0.136, 541: -0.117,
    545: -0.103, 546: -0.152, 548: -0.106, 549: -0.267, 550: -0.183, 556: -0.135,
    570: -0.061, 572: -0.054, 573: 0.137, 575: -0.037, 577: -0.045, 580: -0.050,
    582: -0.038, 584: 0.099, 601: -0.035, 605: -0.048, 609: -0.046, 617: -0.038,
    618: -0.008, 622: -0.040, 623: -0.040, 627: -0.041, 629: -0.037, 632: 0.116,
    636: -0.044, 638: -0.044, 639: 0.213, 640: -0.041, 642: -0.035, 643: 0.018,
    644: -0.037, 646: -0.046, 648: -0.035, 649: -0.038, 650: 0.011, 652: -0.039,
    654: -0.039, 656: 0.128, 665: -0.035, 670: -0.041, 671: -0.043, 677: 0.349,
    679: 0.206, 682: -0.043, 684: 0.015, 686: -0.037, 689: 0.003, 696: -0.035,
    701: -0.036, 703: 0.135, 705: -0.039, 706: -0.044, 710: -0.049, 713: 0.182,
    717: 0.091, 718: 0.011, 719: -0.080, 725: -0.038, 726: 0.086, 727: -0.095,
    728: -0.052, 731: -0.096, 754: -0.038, 755: -0.041, 759: -0.037, 762: -0.050,
    768: -0.039, 770: -0.035, 772: -0.035, 779: -0.049, 788: -0.038, 790: -0.036,
    793: -0.053, 794: -0.041, 806: -0.039, 808: -0.051, 816: -0.038, 831: -0.042,
    833: -0.041, 851: -0.036, 856: 0.190, 860: -0.061, 868: -0.079, 872: -0.036,
    873: 0.126, 878: 0.030, 882: -0.037, 883: -0.006,
}


def med(values):
    clean = [v for v in values if v is not None and v > 0]
    return round(statistics.median(clean), 2) if clean else 0

def avg(values):
    clean = [v for v in values if v is not None and v > 0]
    return round(statistics.mean(clean), 2) if clean else 0

def pct(values):
    if not values:
        return "N/A"
    return f"{sum(1 for v in values if v) / len(values) * 100:.0f}%"


def main():
    pool_map = {p["id"]: p for p in POOLS}

    winners = []
    losers = []
    for pid, pnl in POSITIONS_PNL.items():
        pool = pool_map.get(pid)
        if not pool:
            continue
        pool["pnl"] = pnl
        if pnl > 0:
            winners.append(pool)
        else:
            losers.append(pool)

    print("=" * 80)
    print(f"  PATTERN ANALYSIS: Winners ({len(winners)}) vs Losers ({len(losers)})")
    print("=" * 80)

    metrics = [
        ("Deployer Age (days)", "deployer_age_days"),
        ("Deployer Token Count", "deployer_token_count"),
        ("Deployer Score", "deployer_score"),
        ("Rugcheck Score", "rugcheck_score"),
        ("Top Holder %", "top_holder_pct"),
        ("Legitimacy Score", "legitimacy_score"),
        ("Unique Buyers (early)", "unique_buyers"),
        ("Initial Liquidity (SOL)", "initial_liquidity"),
    ]

    print(f"\n{'Metric':<30} {'Winners (med)':>14} {'Losers (med)':>14} {'Delta':>10} {'Signal':>10}")
    print("-" * 80)

    for name, key in metrics:
        w_vals = [p[key] for p in winners if p.get(key) is not None]
        l_vals = [p[key] for p in losers if p.get(key) is not None]
        w_med = med(w_vals)
        l_med = med(l_vals)

        if l_med > 0:
            delta = f"{(w_med / l_med - 1) * 100:+.0f}%"
        elif w_med > 0:
            delta = "+INF"
        else:
            delta = "0%"

        signal = ""
        if l_med > 0 and w_med / l_med >= 2:
            signal = "*** HIGH"
        elif l_med > 0 and w_med / l_med >= 1.3:
            signal = "** MED"
        elif l_med > 0 and l_med / w_med >= 1.3:
            signal = "** INVERTED"
        else:
            signal = "low"

        print(f"{name:<30} {w_med:>14.1f} {l_med:>14.1f} {delta:>10} {signal:>10}")

    # Detailed breakdown
    print(f"\n{'=' * 80}")
    print(f"  DETAILED BREAKDOWNS")
    print(f"{'=' * 80}")

    # Deployer age buckets
    print("\n--- Deployer Age vs Win Rate ---")
    buckets = [(0, 0, "0 days"), (1, 10, "1-10 days"), (11, 50, "11-50 days"),
               (51, 200, "51-200 days"), (201, 9999, "200+ days")]
    for lo, hi, label in buckets:
        w = [p for p in winners if lo <= (p.get("deployer_age_days") or 0) <= hi]
        l = [p for p in losers if lo <= (p.get("deployer_age_days") or 0) <= hi]
        total = len(w) + len(l)
        wr = f"{len(w)/total*100:.0f}%" if total > 0 else "N/A"
        print(f"  {label:<15} W:{len(w):>3}  L:{len(l):>3}  WinRate: {wr:>5}  ({total} total)")

    # Unique buyers buckets
    print("\n--- Unique Buyers vs Win Rate ---")
    buckets = [(3, 10, "3-10"), (11, 14, "11-14"), (15, 17, "15-17"), (18, 20, "18-20")]
    for lo, hi, label in buckets:
        w = [p for p in winners if lo <= (p.get("unique_buyers") or 0) <= hi]
        l = [p for p in losers if lo <= (p.get("unique_buyers") or 0) <= hi]
        total = len(w) + len(l)
        wr = f"{len(w)/total*100:.0f}%" if total > 0 else "N/A"
        print(f"  {label:<15} W:{len(w):>3}  L:{len(l):>3}  WinRate: {wr:>5}  ({total} total)")

    # Deployer score
    print("\n--- Deployer Score vs Win Rate ---")
    for score in [0, 1, 2, 3]:
        w = [p for p in winners if p.get("deployer_score") == score]
        l = [p for p in losers if p.get("deployer_score") == score]
        total = len(w) + len(l)
        wr = f"{len(w)/total*100:.0f}%" if total > 0 else "N/A"
        print(f"  Score {score:<10} W:{len(w):>3}  L:{len(l):>3}  WinRate: {wr:>5}  ({total} total)")

    # Legitimacy score
    print("\n--- Legitimacy Score vs Win Rate ---")
    for score in [0, 1, 2, 3]:
        w = [p for p in winners if p.get("legitimacy_score") == score]
        l = [p for p in losers if p.get("legitimacy_score") == score]
        total = len(w) + len(l)
        wr = f"{len(w)/total*100:.0f}%" if total > 0 else "N/A"
        print(f"  Score {score:<10} W:{len(w):>3}  L:{len(l):>3}  WinRate: {wr:>5}  ({total} total)")

    # Top holder % buckets
    print("\n--- Top Holder % vs Win Rate ---")
    buckets = [(0, 22, "< 22%"), (22, 25, "22-25%"), (25, 30, "25-30%"), (30, 100, "30%+")]
    for lo, hi, label in buckets:
        w = [p for p in winners if lo <= (p.get("top_holder_pct") or 0) < hi]
        l = [p for p in losers if lo <= (p.get("top_holder_pct") or 0) < hi]
        total = len(w) + len(l)
        wr = f"{len(w)/total*100:.0f}%" if total > 0 else "N/A"
        print(f"  {label:<15} W:{len(w):>3}  L:{len(l):>3}  WinRate: {wr:>5}  ({total} total)")

    # Hold time analysis
    print(f"\n{'=' * 80}")
    print("  POSITION HOLD TIME (closed_at - opened_at)")
    print("=" * 80)

    # Quick dump winners
    print("\n--- WINNERS (sorted by PnL) ---")
    for p in sorted(winners, key=lambda x: x["pnl"], reverse=True)[:20]:
        print(f"  {p.get('token_symbol') or p['id']:<14} PnL: {p['pnl']:>+.3f}  "
              f"buyers:{p.get('unique_buyers',0):>2}  dep_age:{p.get('deployer_age_days',0):>4}d  "
              f"dep_score:{p.get('deployer_score',0)}  top_h:{p.get('top_holder_pct',0):>5.1f}%  "
              f"legit:{p.get('legitimacy_score',0)}  rug:{p.get('rugcheck_score',0)}")

    print("\n--- BIGGEST LOSERS (sorted by PnL) ---")
    for p in sorted(losers, key=lambda x: x["pnl"])[:15]:
        print(f"  {p.get('token_symbol') or p['id']:<14} PnL: {p['pnl']:>+.3f}  "
              f"buyers:{p.get('unique_buyers',0):>2}  dep_age:{p.get('deployer_age_days',0):>4}d  "
              f"dep_score:{p.get('deployer_score',0)}  top_h:{p.get('top_holder_pct',0):>5.1f}%  "
              f"legit:{p.get('legitimacy_score',0)}  rug:{p.get('rugcheck_score',0)}")

    # Summary
    print(f"\n{'=' * 80}")
    print("  ACTIONABLE RECOMMENDATIONS")
    print("=" * 80)

    w_buyers = med([p["unique_buyers"] for p in winners])
    l_buyers = med([p["unique_buyers"] for p in losers])
    w_dep_age = med([p["deployer_age_days"] for p in winners if p["deployer_age_days"] > 0])
    l_dep_age = med([p["deployer_age_days"] for p in losers if p["deployer_age_days"] > 0])
    w_top_h = med([p["top_holder_pct"] for p in winners if p["top_holder_pct"] > 0])
    l_top_h = med([p["top_holder_pct"] for p in losers if p["top_holder_pct"] > 0])

    print(f"""
  1. UNIQUE BUYERS: Winners median={w_buyers}, Losers median={l_buyers}
     -> Consider raising min_unique_buyers from 3 to 15+

  2. DEPLOYER AGE: Winners median={w_dep_age}d, Losers median={l_dep_age}d
     -> Deployer age shows mixed signals, not a strong differentiator

  3. TOP HOLDER %: Winners median={w_top_h}%, Losers median={l_top_h}%
     -> Similar distributions, current filter is adequate

  4. HOLD TIME: Many losers stop-loss within seconds/minutes
     -> The price dumps before our momentum check can catch it
     -> Need STRONGER momentum/volume filters before entry

  5. MAX_PRICE_SEEN: Many losers show max_price_seen = entry (0.1 SOL)
     -> Token never pumped at all after buy
     -> Need to verify price is ALREADY rising before entry
""")


if __name__ == "__main__":
    main()
