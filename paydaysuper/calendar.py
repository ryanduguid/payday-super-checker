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

DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class Holiday:
    day: date
    name: str
    jurisdictions: tuple[str, ...]
    provisional: bool


class CalendarError(ValueError):
    pass


class BusinessCalendar:
    """`verified_until` is the last day the BUNDLED table was checked against
    the gazettes. `coverage_until` is the last day the table actually says
    anything about, which a --holidays-override supplying later dates raises:
    a user who has entered the 2029 holidays has a calendar that computes
    2029 deadlines correctly, and every horizon test here reads coverage_until
    so it stops calling those deadlines unknowable."""

    def __init__(self, holidays: list[Holiday], verified_from: date, verified_until: date):
        self._holidays: dict[date, Holiday] = {h.day: h for h in holidays}
        self.verified_from = verified_from
        self.verified_until = verified_until
        self.coverage_until = max([verified_until, *self._holidays])

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
        """Past the last day the table holds a holiday for, it is empty rather
        than merely incomplete: no holiday of any kind is recorded there,
        including ones already legislated. Every weekday past that date counts
        as a business day, so a deadline computed across it can only be too
        early.

        Measured against coverage_until, not verified_until, so a user who
        supplied the missing holidays with --holidays-override is not told the
        calendar cannot see them while it is using them."""
        if d > self.coverage_until:
            return (
                f"{d.isoformat()} is beyond the calendar's verified horizon "
                f"({self.coverage_until.isoformat()}, the last day it records a holiday "
                "for). The calendar holds no holidays at all after that date, so "
                "weekends are the only non-business days it sees and the real deadline "
                "can only be later than the one shown"
            )
        return None


def _parse_entry(e: dict, where: str) -> Holiday:
    if not isinstance(e, dict):
        raise CalendarError(f"{where} must be an object with 'date' and 'name'")
    for key in ("date", "name"):
        if key not in e:
            raise CalendarError(f"{where} is missing '{key}'")
    try:
        day = date.fromisoformat(str(e["date"]))
    except ValueError:
        raise CalendarError(
            f"{where} has date {e['date']!r}; write it as YYYY-MM-DD"
        )
    return Holiday(
        day=day,
        name=str(e["name"]),
        jurisdictions=tuple(e.get("jurisdictions", [])),
        provisional=bool(e.get("provisional", False)),
    )


def _calendar_date(raw: object, key: str, where: str) -> date:
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        raise CalendarError(f"{where} has {key} {raw!r}; write it as YYYY-MM-DD")


def _checked_document(doc: object, path: Path) -> dict:
    """Guard the TOP LEVEL of the bundled table.

    Every field of every entry is already checked below, but the keys those
    entries hang off were read straight out of the parsed JSON: a renamed
    'non_business_days' raised KeyError and a top level that is a JSON list
    raised TypeError, and the CLI catches neither, so a one-character edit to
    a data file printed a traceback instead of 'error: ...'."""
    if not isinstance(doc, dict):
        raise CalendarError(
            f"{path} must be a JSON object with 'non_business_days', "
            f"'verified_from' and 'verified_until'; it holds a "
            f"{type(doc).__name__} instead"
        )
    for key in ("non_business_days", "verified_from", "verified_until"):
        if key not in doc:
            raise CalendarError(f"{path} is missing the {key!r} key")
    if not isinstance(doc["non_business_days"], list):
        raise CalendarError(
            f"{path}: 'non_business_days' must be a list of holiday entries"
        )
    return doc


def load_calendar(override_path: str | Path | None = None) -> BusinessCalendar:
    """Load the bundled table, optionally patched by a user override file:
    {"add": [{"date": "...", "name": "...", ...}], "remove": ["2026-11-03"]}
    Overrides exist for late proclamations (one-off public holidays, days of
    mourning) and for the documented Melbourne Cup / part-day ambiguities."""
    path = DATA_DIR / "business_days.json"
    with open(path, encoding="utf-8") as f:
        doc = _checked_document(json.load(f), path)
    holidays = {
        h.day: h
        for h in (
            _parse_entry(e, f"bundled calendar entry {n}")
            for n, e in enumerate(doc["non_business_days"], start=1)
        )
    }

    if override_path is not None:
        with open(override_path, encoding="utf-8") as f:
            override = json.load(f)
        if not isinstance(override, dict):
            raise CalendarError(
                f"{override_path} must be an object with 'add' and 'remove' lists"
            )
        unknown = set(override) - {"add", "remove"}
        if unknown:
            raise CalendarError(f"override file has unknown keys: {sorted(unknown)}")

        add = override.get("add", [])
        remove = override.get("remove", [])
        if not isinstance(add, list):
            raise CalendarError(f"{override_path}: 'add' must be a list of entries")
        if not isinstance(remove, list):
            raise CalendarError(f"{override_path}: 'remove' must be a list of dates")

        for n, e in enumerate(add, start=1):
            h = _parse_entry(e, f"{override_path} add entry {n}")
            holidays[h.day] = h
        for n, iso in enumerate(remove, start=1):
            try:
                day = date.fromisoformat(str(iso))
            except ValueError:
                raise CalendarError(
                    f"{override_path} remove entry {n} is {iso!r}; write it as YYYY-MM-DD"
                )
            removed = holidays.pop(day, None)
            if removed is None:
                raise CalendarError(f"override removes {iso}, which is not in the table")

    return BusinessCalendar(
        holidays=list(holidays.values()),
        verified_from=_calendar_date(doc["verified_from"], "verified_from", str(path)),
        verified_until=_calendar_date(doc["verified_until"], "verified_until", str(path)),
    )
