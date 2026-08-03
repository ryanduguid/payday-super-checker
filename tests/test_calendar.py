import json
from datetime import date
from pathlib import Path

import pytest

from paydaysuper.calendar import CalendarError, load_calendar


@pytest.fixture(scope="module")
def cal():
    return load_calendar()


def test_weekends_are_not_business_days(cal):
    assert not cal.is_business_day(date(2026, 8, 8))  # Saturday
    assert not cal.is_business_day(date(2026, 8, 9))  # Sunday
    assert cal.is_business_day(date(2026, 8, 10))     # Monday


def test_ekka_is_a_business_day(cal):
    """Royal Queensland Show is a Brisbane-area holiday, not whole-of-state,
    so it does not stop the clock (SGAA s 6(1)(b) 'for the whole of')."""
    assert cal.is_business_day(date(2026, 8, 12))


def test_state_wide_holiday_anywhere_stops_the_clock(cal):
    assert not cal.is_business_day(date(2027, 6, 7))   # WA Day
    assert not cal.is_business_day(date(2026, 8, 3))   # NT Picnic Day
    assert not cal.is_business_day(date(2026, 11, 3))  # Melbourne Cup Day (VIC)


def test_nsw_act_bank_holiday_is_a_business_day(cal):
    """The August bank holiday is a bank holiday, not a general public
    holiday, so it stays a business day."""
    assert cal.is_business_day(date(2026, 8, 4))


def test_add_business_days_skips_weekends(cal):
    # 7 business days after Thu 9 Jul 2026; this window holds no holidays
    assert cal.add_business_days(date(2026, 7, 9), 7) == date(2026, 7, 20)


def test_ato_new_employee_example(cal):
    """ATO worked example: first QE day 9 Jul 2026, contribution due
    7 Aug 2026 (20 business days, with NT Picnic Day on 3 Aug removed)."""
    assert cal.add_business_days(date(2026, 7, 9), 20) == date(2026, 8, 7)


def test_window_containing_picnic_day_extends_by_one(cal):
    """NT Picnic Day (Mon 3 Aug 2026) is whole-of-NT, so it pushes the
    deadline out a day nationally."""
    assert cal.add_business_days(date(2026, 7, 28), 7) == date(2026, 8, 7)


def test_zero_business_days_returns_same_day(cal):
    assert cal.add_business_days(date(2026, 7, 9), 0) == date(2026, 7, 9)


def test_negative_business_days_rejected(cal):
    with pytest.raises(CalendarError):
        cal.add_business_days(date(2026, 7, 9), -1)


def test_horizon_warning(cal):
    assert cal.check_horizon(date(2027, 1, 1)) is None
    assert "verified horizon" in cal.check_horizon(date(2029, 1, 1))


def test_provisional_hits_flags_grand_final_day(cal):
    hits = cal.provisional_hits(date(2026, 9, 1), date(2026, 10, 1))
    assert any("Grand Final" in h for h in hits)
    assert cal.provisional_hits(date(2026, 7, 1), date(2026, 7, 31)) == []


def test_override_add_and_remove(tmp_path, cal):
    override = tmp_path / "override.json"
    override.write_text(
        json.dumps(
            {
                "add": [
                    {
                        "date": "2026-08-12",
                        "name": "One-off state-wide holiday",
                        "jurisdictions": ["QLD"],
                    }
                ],
                "remove": ["2026-11-03"],
            }
        ),
        encoding="utf-8",
    )
    patched = load_calendar(override)
    assert not patched.is_business_day(date(2026, 8, 12))
    assert patched.is_business_day(date(2026, 11, 3))
    # bundled calendar untouched
    assert cal.is_business_day(date(2026, 8, 12))


def test_override_removing_unknown_date_errors(tmp_path):
    override = tmp_path / "override.json"
    override.write_text(json.dumps({"remove": ["2026-08-05"]}), encoding="utf-8")
    with pytest.raises(CalendarError):
        load_calendar(override)


def test_override_unknown_key_errors(tmp_path):
    override = tmp_path / "override.json"
    override.write_text(json.dumps({"delete": ["2026-08-05"]}), encoding="utf-8")
    with pytest.raises(CalendarError):
        load_calendar(override)


def test_christmas_new_year_cluster(cal):
    """Four non-business days stack up over Christmas 2026, including the
    substitute Boxing Day holiday on Monday 28 December."""
    for day in (date(2026, 12, 25), date(2026, 12, 26), date(2026, 12, 28)):
        assert not cal.is_business_day(day)
    assert cal.is_business_day(date(2026, 12, 29))
    assert not cal.is_business_day(date(2027, 1, 1))
    # Christmas Day, the Boxing Day substitute and New Year's Day all fall
    # inside this window, pushing a 24 Dec payday out to 7 Jan.
    assert cal.add_business_days(date(2026, 12, 24), 7) == date(2027, 1, 7)


def test_easter_cluster_2027(cal):
    for day in (date(2027, 3, 26), date(2027, 3, 29)):
        assert not cal.is_business_day(day)
    assert cal.is_business_day(date(2027, 3, 30))
    assert cal.add_business_days(date(2027, 3, 25), 7) == date(2027, 4, 7)


def test_data_files_ship_inside_the_package():
    """Installed copies resolve DATA_DIR under site-packages, so the JSON
    must live in the package, not beside it."""
    from paydaysuper import calendar as cal_module
    from paydaysuper import rates as rates_module

    package_root = Path(cal_module.__file__).resolve().parent
    for data_dir in (cal_module.DATA_DIR, rates_module.DATA_DIR):
        assert data_dir == package_root / "data"
        assert data_dir.is_dir()
    for name in ("business_days.json", "gic_rates.json", "rates.json"):
        assert (package_root / "data" / name).is_file()

    pyproject = (package_root.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert 'paydaysuper = ["data/*.json", "data/profiles/*.json"]' in pyproject
