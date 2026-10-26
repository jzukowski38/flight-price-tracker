"""AAdvantage Loyalty Points estimate for a Main Cabin ticket.

Basic Economy bought on or after Dec 17, 2025 earns no Loyalty Points, so the
estimate always uses the Main Cabin price. Members earn on the fare excluding
government taxes: 5 points per dollar without status, 7 at Gold.
"""

from __future__ import annotations

from .config import LoyaltyConfig


def estimate_loyalty_points(main_cabin_price: int | None, cfg: LoyaltyConfig) -> int | None:
    if main_cabin_price is None:
        return None
    earning_base = max(0.0, main_cabin_price - cfg.taxes_estimate)
    return int(round(earning_base * cfg.lp_per_dollar, -1))  # nearest 10: it's an estimate
