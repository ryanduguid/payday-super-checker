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
JURISDICTIONS = {"ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA", "ALL"}


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
    official jurisdiction sources. `coverage_until` is the last day the
    table is COMPLETE to, which an override raises only by saying so in its
    own `verified_until`.

    Completeness is a claim, and holding a holiday is not evidence for it.
    An override that adds Christmas 2029 says nothing about whether the 2029
    Easter holidays are in the table, so inferring coverage from the latest
    date present would silence the horizon warning across a gap the table
    cannot see - turning an on-time contribution into a reported LATE with an
    SG charge attached. Only the user knows they entered a whole year, so
    only the user can declare it."""

    def __init__(
        self,
        holidays: list[Holiday],
        verified_from: date,
        verified_until: date,
        coverage_until: date | None = None,
    ):
        self._holidays: dict[date, Holiday] = {h.day: h for h in holidays}
        self.verified_from = verified_from
        self.verified_until = verified_until
        # An override declaring an EARLIER date cannot shrink the bundled
        # table's own verified span; adding holidays never invalidates it.
        self.coverage_until = max(verified_until, coverage_until or verified_until)

    def is_business_day(self, d: date) -> bool:
        if d.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        holiday = self._holidays.get(d)
        # A rule-derived or otherwise unconfirmed date must not extend a
        # statutory deadline. Treat it as a business day until an official
        # source confirms it; the row-level caveat tells the operator that an
        # override may move the deadline later. This direction can produce a
        # conservative false alarm, never a false on-time verdict.
        return holiday is None or holiday.provisional

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
        """Unconfirmed holidays in [start, end]. They are not applied to the
        deadline by default, so confirmation may move that deadline later."""
        return [
            f"{h.day.isoformat()} {h.name}"
            for day, h in sorted(self._holidays.items())
            if start <= day <= end and h.provisional
        ]

    def check_horizon(self, d: date) -> str | None:
        """Past the day the table is complete to, it is incomplete rather than
        merely unverified: holidays already legislated may be missing. A
        missing holiday can only add a non-business day, so a deadline computed
        across that gap can only be too early.

        Measured against coverage_until, so a user who supplied a whole year
        with --holidays-override and declared it is not told the calendar
        cannot see holidays it is using."""
        if d > self.coverage_until:
            return (
                f"{d.isoformat()} is beyond the calendar's coverage "
                f"({self.coverage_until.isoformat()}, the last day the holiday table "
                "is complete to). Holidays after that date may be missing, so the "
                "real deadline can only be later than the one shown"
            )
        return None


def _parse_entry(e: dict, where: str) -> Holiday:
    if not isinstance(e, dict):
        raise CalendarError(f"{where} must be an object with 'date' and 'name'")
    # jurisdictions is required, not optional. A holiday only stops the clock
    # where it is gazetted, so an entry that does not say where it applies has
    # no defensible default: an empty list would never match and "ALL" would
    # silently move every deadline in the country.
    for key in ("date", "name", "jurisdictions"):
        if key not in e:
            raise CalendarError(f"{where} is missing '{key}'")
    raw_date = e["date"]
    try:
        day = date.fromisoformat(raw_date) if isinstance(raw_date, str) else None
    except ValueError:
        day = None
    if day is None or raw_date != day.isoformat():
        raise CalendarError(
            f"{where} has date {e['date']!r}; write it as YYYY-MM-DD"
        )
    # An override file is user-authored by design, so a scalar here is a
    # plausible typo rather than a corrupt bundle: tuple(5) is a TypeError
    # the CLI's handler does not catch, and a bare string would silently
    # become one jurisdiction per character.
    juris = e["jurisdictions"]
    if not isinstance(juris, list):
        raise CalendarError(
            f"{where} has jurisdictions {juris!r}; write it as a list of "
            'codes, e.g. ["NSW", "VIC"] or ["ALL"]'
        )
    if not all(isinstance(j, str) for j in juris):
        raise CalendarError(f"{where} has a jurisdiction that is not a string: {juris!r}")
    if not juris or len(juris) != len(set(juris)) or not set(juris) <= JURISDICTIONS:
        raise CalendarError(
            f"{where} has invalid or duplicate jurisdictions {juris!r}; use one or more of "
            f"{sorted(JURISDICTIONS)}"
        )
    name = e["name"]
    if not isinstance(name, str) or not name.strip() or any(ord(char) < 32 for char in name):
        raise CalendarError(f"{where} has an invalid holiday name")
    provisional = e.get("provisional", False)
    if not isinstance(provisional, bool):
        raise CalendarError(f"{where} provisional must be true or false")
    return Holiday(
        day=day,
        name=name.strip(),
        jurisdictions=tuple(juris),
        provisional=provisional,
    )


def _calendar_date(raw: object, key: str, where: str) -> date:
    try:
        parsed = date.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        parsed = None
    if parsed is None or raw != parsed.isoformat():
        raise CalendarError(f"{where} has {key} {raw!r}; write it as YYYY-MM-DD")
    return parsed


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
    {"add": [{"date": "...", "name": "...", ...}], "remove": ["2026-09-25"],
     "verified_until": "2029-12-31"}
    Overrides exist for late proclamations (one-off public holidays, days of
    mourning), corrected official dates and later completed calendars.

    `verified_until` is optional and is the user asserting they have entered
    EVERY national holiday through that date. It alone moves the horizon;
    adding holidays does not, because a file holding one 2029 holiday is not
    a file that has 2029 covered."""
    path = DATA_DIR / "business_days.json"
    with open(path, encoding="utf-8") as f:
        try:
            doc = _checked_document(json.load(f), path)
        except json.JSONDecodeError as exc:
            raise CalendarError(f"{path} is not valid JSON: {exc}")
    holidays: dict[date, Holiday] = {}
    for n, entry in enumerate(doc["non_business_days"], start=1):
        holiday = _parse_entry(entry, f"bundled calendar entry {n}")
        if holiday.day in holidays:
            raise CalendarError(f"bundled calendar contains duplicate date {holiday.day}")
        holidays[holiday.day] = holiday

    declared_until: date | None = None
    if override_path is not None:
        with open(override_path, encoding="utf-8") as f:
            try:
                override = json.load(f)
            except json.JSONDecodeError as exc:
                raise CalendarError(f"{override_path} is not valid JSON: {exc}")
        if not isinstance(override, dict):
            raise CalendarError(
                f"{override_path} must be an object with 'add' and 'remove' lists"
            )
        unknown = set(override) - {"add", "remove", "verified_until"}
        if unknown:
            raise CalendarError(f"override file has unknown keys: {sorted(unknown)}")

        if "verified_until" in override:
            declared_until = _calendar_date(
                override["verified_until"], "verified_until", str(override_path)
            )

        add = override.get("add", [])
        remove = override.get("remove", [])
        if not isinstance(add, list):
            raise CalendarError(f"{override_path}: 'add' must be a list of entries")
        if not isinstance(remove, list):
            raise CalendarError(f"{override_path}: 'remove' must be a list of dates")

        added_dates: set[date] = set()
        for n, e in enumerate(add, start=1):
            h = _parse_entry(e, f"{override_path} add entry {n}")
            if h.day in added_dates:
                raise CalendarError(f"override adds duplicate date {h.day}")
            added_dates.add(h.day)
            holidays[h.day] = h
        for n, iso in enumerate(remove, start=1):
            try:
                day = date.fromisoformat(iso) if isinstance(iso, str) else None
            except ValueError:
                day = None
            if day is None or iso != day.isoformat():
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
        coverage_until=declared_until,
    )
