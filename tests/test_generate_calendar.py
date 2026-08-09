"""Regression coverage for the hand-review-only calendar generator."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_generator_keeps_victorian_afl_final_day_provisional():
    """A source-label update must not remove the existing provisional flag.

    The generator is development-time only: runtime uses the reviewed JSON
    table.  Victoria's official 2026 calendar calls 25 September the Friday
    before the AFL Grand Final; it remains fixture-dependent for generation
    purposes and must therefore retain the pre-existing provisional marking.
    """

    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "generate_calendar.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    generated = json.loads(completed.stdout)
    entry = next(
        holiday
        for holiday in generated["non_business_days"]
        if holiday["date"] == "2026-09-25"
    )

    assert entry["name"] == "Friday before the AFL Grand Final"
    assert entry["jurisdictions"] == ["VIC"]
    assert entry["provisional"] is True


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
