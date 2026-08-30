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
    assert not cal.is_business_day(date(2026, 9, 25))  # confirmed VIC Grand Final day


def test_locally_substitutable_dates_do_not_stop_the_national_clock(cal):
    """The official WA and Victorian pages say these dates are replaced in
    parts of their State, so neither is a holiday for the whole State under
    SGAA s 6(1)."""
    assert cal.is_business_day(date(2026, 9, 28))  # WA King's Birthday
    assert cal.is_business_day(date(2026, 11, 3))  # Melbourne Cup Day


def test_no_bank_holiday_reaches_the_shipped_table():
    """The NSW/ACT August bank holiday is a bank holiday, not a general
    public holiday, so it must never remove a business day.

    This cannot be observed through is_business_day: the bank holiday is the
    first Monday in August, which NT Picnic Day already makes a non-business
    day every year (2026-08-03, 2027-08-02, 2028-08-07). So assert the
    exclusion on the table itself. tests/test_generate_calendar.py guards the
    generator that produces it."""
    table = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "paydaysuper"
            / "data"
            / "business_days.json"
        ).read_text(encoding="utf-8")
    )
    assert not [
        entry
        for entry in table["non_business_days"]
        if "bank holiday" in entry["name"].lower()
    ]


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
    assert cal.check_horizon(date(2027, 8, 31)) is None
    assert "beyond the calendar's coverage" in cal.check_horizon(date(2027, 9, 1))
    assert "beyond the calendar's coverage" in cal.check_horizon(date(2029, 1, 1))


def _easter_2029_override(tmp_path, declare_until="2029-04-25"):
    """The 2029 national holidays the bundled table stops short of.

    `declare_until` is the user asserting the file is complete to that date.
    Drop it to model the far more common case: a partial override."""
    override = tmp_path / "override.json"
    doc = {} if declare_until is None else {"verified_until": declare_until}
    override.write_text(
        json.dumps(
            {
                **doc,
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


def test_a_declared_override_raises_the_coverage_end_past_verified_until(tmp_path, cal):
    """verified_until records when the BUNDLED table was last checked. A user
    who supplies later holidays AND says how far they go has a calendar that
    covers them, and the coverage end has to say so or every horizon test
    reads a stale date."""
    patched = load_calendar(_easter_2029_override(tmp_path))
    assert patched.verified_until == date(2027, 8, 31)
    assert patched.coverage_until == date(2029, 4, 25)
    assert cal.coverage_until == date(2027, 8, 31)


def test_an_undeclared_override_does_not_raise_the_coverage_end(tmp_path):
    """Holding a holiday is not evidence the table is complete to it.

    Inferring coverage from the latest date present let a file carrying one
    2029 holiday silence the horizon warning for the whole of 2029 - and the
    holidays it was missing would have moved a real deadline, turning an
    on-time contribution into a reported LATE with an SG charge attached."""
    partial = load_calendar(_easter_2029_override(tmp_path, declare_until=None))
    assert partial.coverage_until == date(2027, 8, 31)
    # The holidays are still USED; only the completeness claim is withheld.
    assert not partial.is_business_day(date(2029, 3, 30))
    assert partial.add_business_days(date(2029, 3, 27), 7) == date(2029, 4, 9)
    assert partial.check_horizon(date(2029, 4, 9)) is not None


def test_one_far_future_holiday_does_not_cover_the_gap_before_it(tmp_path):
    """The sharpest form: an override adding only Christmas 2029 says nothing
    about the 2029 Easter holidays nine months earlier."""
    override = tmp_path / "sparse.json"
    override.write_text(
        json.dumps(
            {"add": [{"date": "2029-12-25", "name": "Christmas Day",
                      "jurisdictions": ["ALL"]}]}
        ),
        encoding="utf-8",
    )
    sparse = load_calendar(override)
    assert sparse.coverage_until == date(2027, 8, 31)
    assert sparse.check_horizon(date(2029, 4, 5)) is not None


def test_an_override_declaring_an_earlier_date_cannot_shrink_coverage(tmp_path):
    """Adding a holiday never invalidates the span the bundled table already
    verified, so a declaration below it is ignored rather than obeyed."""
    override = tmp_path / "shrink.json"
    override.write_text(
        json.dumps({"verified_until": "2027-01-01", "add": []}), encoding="utf-8"
    )
    assert load_calendar(override).coverage_until == date(2027, 8, 31)


def test_check_horizon_reads_the_declared_coverage_not_the_verified_date(tmp_path):
    """A deadline the supplied holidays actually moved must not be told the
    calendar cannot see them."""
    patched = load_calendar(_easter_2029_override(tmp_path))
    assert patched.add_business_days(date(2029, 3, 27), 7) == date(2029, 4, 9)
    assert patched.check_horizon(date(2029, 4, 9)) is None
    # Past the date the user declared, the warning is still owed.
    warning = patched.check_horizon(date(2029, 5, 1))
    assert warning is not None
    assert "2029-04-25" in warning


def test_a_bad_declared_coverage_date_is_named(tmp_path):
    override = tmp_path / "baddate.json"
    override.write_text(
        json.dumps({"verified_until": "31/12/2029", "add": []}), encoding="utf-8"
    )
    with pytest.raises(CalendarError, match="write it as YYYY-MM-DD"):
        load_calendar(override)


@pytest.mark.parametrize("missing", ["date", "name", "jurisdictions"])
def test_an_override_entry_names_the_key_it_is_missing(tmp_path, missing):
    """A holiday only stops the clock where it is gazetted, so an entry that
    omits jurisdictions is incomplete, not a request for a default."""
    entry = {"date": "2029-03-30", "name": "Good Friday", "jurisdictions": ["ALL"]}
    del entry[missing]
    override = tmp_path / "incomplete.json"
    override.write_text(json.dumps({"add": [entry]}), encoding="utf-8")

    with pytest.raises(CalendarError, match=f"is missing '{missing}'"):
        load_calendar(override)


@pytest.mark.parametrize("bad", [5, "NSW", {"state": "NSW"}, [1, 2]])
def test_a_non_list_jurisdictions_value_is_named(tmp_path, bad):
    """tuple(5) is a TypeError the CLI does not catch, and a bare "NSW" would
    silently become one jurisdiction per character. An override file is
    user-authored, so both are plausible typos rather than a corrupt bundle."""
    override = tmp_path / "juris.json"
    override.write_text(
        json.dumps(
            {"add": [{"date": "2029-03-30", "name": "Good Friday",
                      "jurisdictions": bad}]}
        ),
        encoding="utf-8",
    )
    with pytest.raises(CalendarError, match="jurisdiction"):
        load_calendar(override)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", 7, "holiday name"),
        ("name", " ", "holiday name"),
        ("provisional", "false", "true or false"),
        ("jurisdictions", ["NSW", "NSW"], "invalid or duplicate"),
        ("jurisdictions", ["XYZ"], "invalid or duplicate"),
    ],
)
def test_override_entries_reject_ambiguous_metadata(tmp_path, field, value, message):
    entry = {
        "date": "2029-03-30",
        "name": "Good Friday",
        "jurisdictions": ["ALL"],
        field: value,
    }
    override = tmp_path / "bad-entry.json"
    override.write_text(json.dumps({"add": [entry]}), encoding="utf-8")

    with pytest.raises(CalendarError, match=message):
        load_calendar(override)


def test_override_rejects_duplicate_additions(tmp_path):
    entry = {"date": "2029-03-30", "name": "Good Friday", "jurisdictions": ["ALL"]}
    override = tmp_path / "duplicates.json"
    override.write_text(json.dumps({"add": [entry, entry]}), encoding="utf-8")

    with pytest.raises(CalendarError, match="duplicate date"):
        load_calendar(override)


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
    hits = cal.provisional_hits(date(2027, 9, 1), date(2027, 10, 1))
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
                "remove": ["2026-09-25"],
            }
        ),
        encoding="utf-8",
    )
    patched = load_calendar(override)
    assert not patched.is_business_day(date(2026, 8, 12))
    assert patched.is_business_day(date(2026, 9, 25))
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
    assert 'paydaysuper = ["data/*.json", "data/profiles/*.json", "py.typed"]' in pyproject
