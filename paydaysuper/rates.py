"""Dated legal rates: GIC quarters and FY super parameters.

Every number lives in data/*.json with a source URL and seen-date.
Nothing here is hard-coded because all of it changes: GIC resets
quarterly (TAA 1953 s 8AAD), the SG parameters change each financial
year."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

DAYS_IN_YEAR = 365  # ATO publishes daily GIC as annual rate / 365


@dataclass(frozen=True)
class GicQuarter:
    start: date
    end: date
    annual_pct: Decimal


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

    def daily_rate(self, d: date) -> Decimal:
        for q in self._quarters:
            if q.start <= d <= q.end:
                return q.annual_pct / Decimal(100) / Decimal(DAYS_IN_YEAR)
        if d > self.last_known:
            # estimate with the latest known rate; staleness() flags this
            return self._quarters[-1].annual_pct / Decimal(100) / Decimal(DAYS_IN_YEAR)
        raise RatesError(f"no GIC rate on record for {d.isoformat()}")

    def staleness(self, d: date) -> str | None:
        if d > self.last_known:
            return (
                f"GIC rate table ends {self.last_known.isoformat()}; days after that "
                f"use the last known rate ({self._quarters[-1].annual_pct}% p.a.): "
                "update data/gic_rates.json from the ATO GIC rates page"
            )
        return None


def load_gic() -> GicTable:
    with open(DATA_DIR / "gic_rates.json", encoding="utf-8") as f:
        doc = json.load(f)
    return GicTable(
        [
            GicQuarter(
                start=date.fromisoformat(e["from"]),
                end=date.fromisoformat(e["to"]),
                annual_pct=Decimal(e["annual_pct"]),
            )
            for e in doc["quarters"]
        ]
    )


def load_rates() -> dict:
    with open(DATA_DIR / "rates.json", encoding="utf-8") as f:
        return json.load(f)
