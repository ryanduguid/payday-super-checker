"""Dated legal rates: GIC quarters and FY super parameters.

Every rate lives in paydaysuper/data/*.json, recording where it came
from and when that was checked. Nothing here is hard-coded because all
of it changes: GIC resets quarterly (TAA 1953 s 8AAD), the SG
parameters change each financial year."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"


def days_in_year(d: date) -> int:
    """TAA 1953 s 8AAD divides the annual GIC rate by the number of days
    in the calendar year, so a leap year uses 366."""
    return (date(d.year, 12, 31) - date(d.year, 1, 1)).days + 1


@dataclass(frozen=True)
class GicQuarter:
    start: date
    end: date
    annual_pct: Decimal
    seen: str = ""


class RatesError(ValueError):
    pass


class GicTable:
    def __init__(self, quarters: list[GicQuarter]):
        self._quarters = sorted(quarters, key=lambda q: q.start)
        if not self._quarters:
            raise RatesError("GIC table is empty")

    @property
    def last_known(self) -> date:
        return self._quarters[-1].end

    def provenance(self) -> str:
        """One line naming the coverage, latest rate and check date, so a
        report can be audited long after it was produced."""
        latest = self._quarters[-1]
        checked = f", checked {latest.seen}" if latest.seen else ""
        return (
            f"GIC table covers {self._quarters[0].start.isoformat()} to "
            f"{latest.end.isoformat()} (latest quarter {latest.annual_pct}% p.a.{checked})"
        )

    def daily_rate(self, d: date) -> Decimal:
        divisor = Decimal(days_in_year(d))
        for q in self._quarters:
            if q.start <= d <= q.end:
                return q.annual_pct / Decimal(100) / divisor
        if d > self.last_known:
            # estimate with the latest known rate; staleness() flags this
            return self._quarters[-1].annual_pct / Decimal(100) / divisor
        raise RatesError(f"no GIC rate on record for {d.isoformat()}")

    def staleness(self, d: date) -> str | None:
        if d > self.last_known:
            return (
                f"GIC rate table ends {self.last_known.isoformat()}; days after that "
                f"use the last known rate ({self._quarters[-1].annual_pct}% p.a.): "
                "update paydaysuper/data/gic_rates.json from the ATO GIC rates page"
            )
        return None


def _quarter_label(entry: dict, n: int) -> str:
    where = f"GIC quarter {n} in {DATA_DIR / 'gic_rates.json'}"
    span = f"{entry.get('from')} to {entry.get('to')}"
    return f"{where} ({span})"


def _rate(raw: object, where: str) -> Decimal:
    """A quarterly rate update is hand-edited, and Decimal is happy to build
    NaN or Infinity from a typo. decimal.InvalidOperation is an
    ArithmeticError rather than a ValueError, so an unguarded conversion here
    escapes the CLI's error handling and prints a traceback; a NaN escapes
    nothing at all and poisons every money figure downstream."""
    try:
        value = Decimal(str(raw))
    except InvalidOperation:
        raise RatesError(
            f"{where} has annual_pct {raw!r}, which is not a number. Fix it and "
            "run again"
        )
    if not value.is_finite():
        raise RatesError(
            f"{where} has annual_pct {raw!r}; a rate must be a finite number, and "
            "nan or infinity would silently poison every figure in the report"
        )
    return value


def _rate_date(raw: object, key: str, where: str) -> date:
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        raise RatesError(f"{where} has {key} {raw!r}; write it as YYYY-MM-DD")


def load_gic() -> GicTable:
    path = DATA_DIR / "gic_rates.json"
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    quarters = []
    for n, e in enumerate(doc["quarters"], start=1):
        if not isinstance(e, dict):
            raise RatesError(f"GIC quarter {n} in {path} is not an object")
        where = _quarter_label(e, n)
        for key in ("from", "to", "annual_pct"):
            if key not in e:
                raise RatesError(f"{where} is missing {key!r}")
        quarters.append(
            GicQuarter(
                start=_rate_date(e["from"], "from", where),
                end=_rate_date(e["to"], "to", where),
                annual_pct=_rate(e["annual_pct"], where),
                seen=str(e.get("seen", "")),
            )
        )
    return GicTable(quarters)


def load_rates() -> dict:
    with open(DATA_DIR / "rates.json", encoding="utf-8") as f:
        return json.load(f)
