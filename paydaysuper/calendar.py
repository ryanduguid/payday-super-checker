"""National business-day calendar for SGAA 1992 s 6(1).

"business day means a day other than: (a) a Saturday or a Sunday; or
(b) a day which is a public holiday for the whole of: (i) any State; or
(ii) the Australian Capital Territory; or (iii) the Northern Territory."

One national calendar for every employer, regardless of location. The
holiday table ships in data/business_days.json (curated; see
tools/generate_calendar.py). Part-day holidays are treated as business
days; regional holidays never appear in the table.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Holiday:
    day: date
    name: str
    jurisdictions: tuple[str, ...]
    provisional: bool


class CalendarError(ValueError):
    pass


class BusinessCalendar:
    def __init__(self, holidays: list[Holiday], verified_from: date, verified_until: date):
        self._holidays: dict[date, Holiday] = {h.day: h for h in holidays}
        self.verified_from = verified_from
        self.verified_until = verified_until

    def is_business_day(self, d: date) -> bool:
        if d.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        return d not in self._holidays

    def add_business_days(self, d: date, n: int) -> date:
        """The n-th business day after d. d itself is never counted
        (SGAA s 6(1) 'usual period' ends on the seventh business day
        AFTER the QE day)."""
        if n < 0:
            raise CalendarError("n must be >= 0")
        cur = d
        counted = 0
        while counted < n:
            cur += timedelta(days=1)
            if self.is_business_day(cur):
                counted += 1
        return cur

    def provisional_hits(self, start: date, end: date) -> list[str]:
        """Provisional (rule-derived, not yet gazetted) holidays in
        [start, end]: a deadline depending on one may shift."""
        return [
            f"{h.day.isoformat()} {h.name}"
            for day, h in sorted(self._holidays.items())
            if start <= day <= end and h.provisional
        ]

    def check_horizon(self, d: date) -> str | None:
        if d > self.verified_until:
            return (
                f"{d.isoformat()} is beyond the calendar's verified horizon "
                f"({self.verified_until.isoformat()}); holidays proclaimed later "
                "could move this deadline"
            )
        return None


def _parse_entry(e: dict, provisional_default: bool = False) -> Holiday:
    return Holiday(
        day=date.fromisoformat(e["date"]),
        name=e["name"],
        jurisdictions=tuple(e.get("jurisdictions", [])),
        provisional=bool(e.get("provisional", provisional_default)),
    )


def load_calendar(override_path: str | Path | None = None) -> BusinessCalendar:
    """Load the bundled table, optionally patched by a user override file:
    {"add": [{"date": "...", "name": "...", ...}], "remove": ["2026-11-03"]}
    Overrides exist for late proclamations (one-off public holidays, days of
    mourning) and for the documented Melbourne Cup / part-day ambiguities."""
    with open(DATA_DIR / "business_days.json", encoding="utf-8") as f:
        doc = json.load(f)
    holidays = {h.day: h for h in (_parse_entry(e) for e in doc["non_business_days"])}

    if override_path is not None:
        with open(override_path, encoding="utf-8") as f:
            override = json.load(f)
        unknown = set(override) - {"add", "remove"}
        if unknown:
            raise CalendarError(f"override file has unknown keys: {sorted(unknown)}")
        for e in override.get("add", []):
            h = _parse_entry(e)
            holidays[h.day] = h
        for iso in override.get("remove", []):
            removed = holidays.pop(date.fromisoformat(iso), None)
            if removed is None:
                raise CalendarError(f"override removes {iso}, which is not in the table")

    return BusinessCalendar(
        holidays=list(holidays.values()),
        verified_from=date.fromisoformat(doc["verified_from"]),
        verified_until=date.fromisoformat(doc["verified_until"]),
    )
