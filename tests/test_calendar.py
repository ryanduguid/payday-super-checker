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


def _easter_2029_override(tmp_path):
    """The 2029 national holidays the bundled table stops short of."""
    override = tmp_path / "override.json"
    override.write_text(
        json.dumps(
            {
                "add": [
                    {
                        "date": "2029-03-30",
                        "name": "Good Friday",
                        "jurisdictions": ["ALL"],
                    },
                    {
                        "date": "2029-04-02",
                        "name": "Easter Monday",
                        "jurisdictions": ["ALL"],
                    },
                    {
                        "date": "2029-04-25",
                        "name": "Anzac Day",
                        "jurisdictions": ["ALL"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return override


def test_an_override_raises_the_coverage_end_past_verified_until(tmp_path, cal):
    """verified_until records when the BUNDLED table was last checked. A user
    who supplies later holidays has a calendar that covers them, and the
    coverage end has to say so or every horizon test reads a stale date."""
    patched = load_calendar(_easter_2029_override(tmp_path))
    assert patched.verified_until == date(2028, 12, 31)
    assert patched.coverage_until == date(2029, 4, 25)
    assert cal.coverage_until == date(2028, 12, 31)


def test_check_horizon_reads_the_table_not_the_verified_date(tmp_path):
    """A deadline the supplied holidays actually moved must not be told the
    calendar cannot see them."""
    patched = load_calendar(_easter_2029_override(tmp_path))
    assert patched.add_business_days(date(2029, 3, 27), 7) == date(2029, 4, 9)
    assert patched.check_horizon(date(2029, 4, 9)) is None
    # Past the last holiday it now holds, the warning is still owed.
    warning = patched.check_horizon(date(2029, 5, 1))
    assert warning is not None
    assert "2029-04-25" in warning


def test_an_unpatched_calendar_computes_the_earlier_deadline(cal):
    """The other half of the pair above: without the override the same QE day
    lands four days earlier, which is what makes the horizon warning real."""
    assert cal.add_business_days(date(2029, 3, 27), 7) == date(2029, 4, 5)
    assert cal.check_horizon(date(2029, 4, 5)) is not None


def _write_bundled(tmp_path, doc):
    (tmp_path / "business_days.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )
    return tmp_path


GOOD_DOC = {
    "verified_from": "2026-07-01",
    "verified_until": "2028-12-31",
    "non_business_days": [
        {"date": "2026-08-03", "name": "Picnic Day", "jurisdictions": ["NT"]}
    ],
}


def test_a_good_bundled_table_still_loads(tmp_path, monkeypatch):
    from paydaysuper import calendar as cal_module

    monkeypatch.setattr(cal_module, "DATA_DIR", _write_bundled(tmp_path, GOOD_DOC))
    loaded = load_calendar()
    assert not loaded.is_business_day(date(2026, 8, 3))
    assert loaded.coverage_until == date(2028, 12, 31)


@pytest.mark.parametrize("key", ["non_business_days", "verified_from", "verified_until"])
def test_a_missing_top_level_key_is_named(tmp_path, monkeypatch, key):
    """These three were read straight off the parsed JSON, so a renamed key
    raised KeyError, which the CLI's handler tuple does not catch."""
    from paydaysuper import calendar as cal_module

    doc = {k: v for k, v in GOOD_DOC.items() if k != key}
    monkeypatch.setattr(cal_module, "DATA_DIR", _write_bundled(tmp_path, doc))
    with pytest.raises(CalendarError) as exc:
        load_calendar()
    message = str(exc.value)
    assert key in message
    assert "business_days.json" in message


def test_a_list_at_the_top_level_is_refused(tmp_path, monkeypatch):
    """A JSON list gave TypeError, which the CLI does not catch either."""
    from paydaysuper import calendar as cal_module

    monkeypatch.setattr(
        cal_module, "DATA_DIR", _write_bundled(tmp_path, [GOOD_DOC])
    )
    with pytest.raises(CalendarError) as exc:
        load_calendar()
    assert "must be a JSON object" in str(exc.value)


def test_non_business_days_must_be_a_list(tmp_path, monkeypatch):
    from paydaysuper import calendar as cal_module

    doc = dict(GOOD_DOC, non_business_days={"2026-08-03": "Picnic Day"})
    monkeypatch.setattr(cal_module, "DATA_DIR", _write_bundled(tmp_path, doc))
    with pytest.raises(CalendarError) as exc:
        load_calendar()
    assert "must be a list" in str(exc.value)


@pytest.mark.parametrize("key", ["verified_from", "verified_until"])
def test_an_unreadable_verified_date_is_named(tmp_path, monkeypatch, key):
    from paydaysuper import calendar as cal_module

    doc = dict(GOOD_DOC, **{key: "31/12/2028"})
    monkeypatch.setattr(cal_module, "DATA_DIR", _write_bundled(tmp_path, doc))
    with pytest.raises(CalendarError) as exc:
        load_calendar()
    message = str(exc.value)
    assert key in message
    assert "YYYY-MM-DD" in message


def test_the_cli_prints_a_calendar_error_without_a_traceback(tmp_path, monkeypatch, capsys):
    from conftest import SAMPLE
    from paydaysuper import calendar as cal_module
    from paydaysuper.cli import EXIT_ERROR, main

    doc = {k: v for k, v in GOOD_DOC.items() if k != "non_business_days"}
    doc["holidays"] = GOOD_DOC["non_business_days"]
    monkeypatch.setattr(cal_module, "DATA_DIR", _write_bundled(tmp_path, doc))
    assert main([str(SAMPLE), "-o", str(tmp_path / "r.csv"), "--as-at", "2026-08-10"]) == (
        EXIT_ERROR
    )
    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert "Traceback" not in err
    assert "non_business_days" in err


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
