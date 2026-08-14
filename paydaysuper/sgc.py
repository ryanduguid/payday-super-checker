"""SG-charge exposure estimates for late contributions.

Components (SGAA s 16B(2)) modelled here:
- final SG shortfall (input: the unpaid individual SG amount)
- notional earnings component (s 19A): daily compounding at the GIC rate
  on the BASE shortfall, starting the day AFTER the last on-time day (final
  LCR 2026/3 worked example) and running while the final shortfall exceeds
  nil, so it ends on the day the fund receives the late contribution, or
  runs to the as-at date while the money is still outstanding
- administrative uplift (s 19B(1)): 60% of (shortfalls + notional
  earnings), reduced by reg 13C (clean 24-month history: -20 points;
  transitional: lookback starts 1 Jul 2026 for QE days to 30 Jun 2028)
  and reg 13D (voluntary disclosure statement lodged within 30/60/120/120+
  days of the QE day: -40/-35/-30/-15 points). Floor 0%.

NOT modelled: choice loading (s 20A: not detectable from pay data),
the post-assessment late payment penalty, GIC on an unpaid assessment.
Estimates are indicative only; the ATO assesses.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from .rates import GicTable

# reg 13D VDS-timing reduction points, applied against the 60% start rate,
# with (reg 13C) and without the extra 20-point clean-history reduction.
UPLIFT_PCT = {
    "clean_history": {
        "vds_within_30d": Decimal("0"),
        "vds_31_60d": Decimal("5"),
        "vds_61_120d": Decimal("10"),
        "vds_after_120d": Decimal("25"),
        "no_vds": Decimal("40"),
    },
    "prior_history": {
        "vds_within_30d": Decimal("20"),
        "vds_31_60d": Decimal("25"),
        "vds_61_120d": Decimal("30"),
        "vds_after_120d": Decimal("45"),
        "no_vds": Decimal("60"),
    },
}


def notional_earnings(
    shortfall: Decimal, due: date, end: date, gic: GicTable
) -> Decimal:
    """NEC accrued over [due + 1 day, end] inclusive.

    Caller chooses `end`: the day the fund received a late contribution
    clearing the shortfall, or the as-at date while it is still unpaid.
    `shortfall` is the BASE shortfall: the statutory notional sum
    compounds on it until the final shortfall reaches nil, so a partial
    late payment does not slow the accrual.
    Each day's accrual = (shortfall + NEC so far) x daily GIC rate."""
    if shortfall < 0:
        raise ValueError("shortfall cannot be negative")
    nec = Decimal("0")
    d = due + timedelta(days=1)
    while d <= end:
        nec += (shortfall + nec) * gic.daily_rate(d)
        d += timedelta(days=1)
    return nec


def uplift_scenarios(final_shortfall: Decimal, nec: Decimal) -> dict[str, dict[str, Decimal]]:
    """Administrative uplift under every reg 13C/13D scenario.

    For QE days 1 Jul 2026 - 30 Jun 2028, reg 13C(3) shortens the historical
    period tested for the clean-history reduction. It does not establish that
    a particular employer meets the remaining conditions, so both rows are
    retained."""
    base = final_shortfall + nec
    return {
        history: {scenario: base * pct / Decimal(100) for scenario, pct in row.items()}
        for history, row in UPLIFT_PCT.items()
    }


def exposure_range(final_shortfall: Decimal, nec: Decimal) -> tuple[Decimal, Decimal]:
    """(low, high) total SGC estimate excluding choice loading.

    Low: clean history + VDS within 30 days (uplift 0%).
    High: prior history + no VDS (uplift 60%)."""
    scenarios = uplift_scenarios(final_shortfall, nec)
    low = final_shortfall + nec + scenarios["clean_history"]["vds_within_30d"]
    high = final_shortfall + nec + scenarios["prior_history"]["no_vds"]
    return low, high
