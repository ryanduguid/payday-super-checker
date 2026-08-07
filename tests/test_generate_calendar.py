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
