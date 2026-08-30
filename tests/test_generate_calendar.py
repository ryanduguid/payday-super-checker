"""Regression coverage for the hand-review-only calendar generator."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_raw_generator_is_provisional_until_the_reviewed_table_confirms_dates():
    """Generation is not primary-source review. The shipped table confirms
    Business Victoria's 25 September 2026 date, while raw output keeps it and
    the fixture-dependent 2027 candidate provisional."""

    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "generate_calendar.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    generated = json.loads(completed.stdout)
    raw_2026 = next(
        holiday
        for holiday in generated["non_business_days"]
        if holiday["date"] == "2026-09-25"
    )
    future = next(
        holiday
        for holiday in generated["non_business_days"]
        if holiday["jurisdictions"] == ["VIC"]
        and "Grand Final" in holiday["name"]
        and holiday["date"].startswith("2027-")
    )

    reviewed = json.loads(
        (ROOT / "paydaysuper" / "data" / "business_days.json").read_text(
            encoding="utf-8"
        )
    )
    reviewed_2026 = next(
        holiday
        for holiday in reviewed["non_business_days"]
        if holiday["date"] == "2026-09-25"
    )

    assert raw_2026["name"] == "Friday before the AFL Grand Final"
    assert raw_2026["jurisdictions"] == ["VIC"]
    assert raw_2026["provisional"] is True
    assert reviewed_2026["provisional"] is False
    assert future["provisional"] is True


def test_generator_excludes_locally_substitutable_dates():
    """WA King's Birthday and Melbourne Cup Day do not apply throughout
    their respective State according to the official jurisdiction pages."""
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "generate_calendar.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    generated = json.loads(completed.stdout)
    names = [entry["name"] for entry in generated["non_business_days"]]

    assert "Melbourne Cup Day" not in names
    assert not any(
        entry["jurisdictions"] == ["WA"] and entry["name"] == "King's Birthday"
        for entry in generated["non_business_days"]
    )
    assert generated["verified_until"] == "2026-07-01"
    assert generated["official_sources"]["checked"] is None


def test_generator_requests_public_holidays_only_and_emits_no_bank_holiday():
    """A bank holiday is not a public holiday for the whole of a State, so
    admitting one would extend a deadline and manufacture a false ON_TIME.

    The exclusion lives in the generator's category argument, not in
    NOT_WHOLE_OF_JURISDICTION and not in the shipped table's dates: the
    NSW/ACT August bank holiday falls on the first Monday in August, which NT
    Picnic Day already removes, so is_business_day can never observe it."""
    source = (ROOT / "tools" / "generate_calendar.py").read_text(encoding="utf-8")
    assert 'categories=("public",)' in source
    assert source.count("holidays.Australia(") == 1

    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "generate_calendar.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    generated = json.loads(completed.stdout)

    assert not [
        entry
        for entry in generated["non_business_days"]
        if "bank holiday" in entry["name"].lower()
    ]


def test_generator_provenance_reflects_the_environment_that_ran():
    """The pin in _comment and the generation date come from the installed
    holidays package and the clock, not from literals: a hardcoded pin
    survived the 0.101 -> 0.102 bump, and a hardcoded date would stamp any
    future regeneration with a false generation date."""
    from datetime import date

    import holidays

    before = date.today()
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "generate_calendar.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    after = date.today()
    generated = json.loads(completed.stdout)

    assert f"holidays=={holidays.__version__}" in generated["_comment"]
    # Bracketed rather than compared to a single call so a run that crosses
    # midnight cannot fail spuriously.
    assert generated["generated"] in {before.isoformat(), after.isoformat()}
