import json

import pytest

from paydaysuper import profiles
from paydaysuper.csv_io import CsvError
from paydaysuper.profiles import normalise_header


def test_normalise_header_folds_case_space_and_punctuation():
    assert normalise_header("  Employee   Membership #  ") == "employee membership"
    assert normalise_header("Paid Date") == "paid date"
    assert normalise_header("Employee Name") == "employee name"


def test_normalise_header_keeps_digits():
    assert normalise_header("Period 1 To") == "period 1 to"


def test_normalise_header_folds_nbsp_and_tab_as_whitespace():
    # The docstring promises NBSP and tabs are whitespace like any other.
    # A heading pasted from a spreadsheet often carries a non-breaking space
    # (U+00A0) instead of an ordinary one, and it must not glue the words
    # together.
    assert normalise_header("Employee Name") == "employee name"
    assert normalise_header("Employee\tName") == "employee name"


def _write_profile(tmp_path, overrides):
    base = {
        "key": "test-profile",
        "name": "Test Profile",
        "role": "payroll",
        "signature": ["Employee ID"],
        "columns": {
            "employee_id": ["Employee ID"],
            "contribution_type": ["Type"],
        },
    }
    base.update(overrides)
    path = tmp_path / "test-profile.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return path


def test_sg_filter_include_as_a_string_raises_csv_error(tmp_path, monkeypatch):
    # A string is iterable, so without a type check "include": "SGC" would
    # silently build ('S', 'G', 'C') instead of failing loudly.
    monkeypatch.setattr(profiles, "PROFILE_DIR", tmp_path)
    _write_profile(
        tmp_path,
        {"sg_filter": {"column": "contribution_type", "include": "SGC"}},
    )
    with pytest.raises(CsvError):
        profiles.load_profiles()


def test_date_formats_as_a_string_raises_csv_error(tmp_path, monkeypatch):
    # Same failure mode as sg_filter.include: a forgotten pair of brackets
    # must not silently iterate the string's characters.
    monkeypatch.setattr(profiles, "PROFILE_DIR", tmp_path)
    _write_profile(tmp_path, {"date_formats": "%d/%m/%Y"})
    with pytest.raises(CsvError):
        profiles.load_profiles()


def test_verified_as_a_string_raises_csv_error(tmp_path, monkeypatch):
    # bool("false") is True in Python, the opposite of the author's intent
    # on the one field that tells a user whether to trust a profile.
    monkeypatch.setattr(profiles, "PROFILE_DIR", tmp_path)
    _write_profile(tmp_path, {"verified": "false"})
    with pytest.raises(CsvError):
        profiles.load_profiles()
