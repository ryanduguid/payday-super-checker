import json
from pathlib import Path

import pytest

from paydaysuper import profiles
from paydaysuper.csv_io import CsvError
from paydaysuper.profiles import normalise_header, Profile, load_profiles


def test_normalise_header_folds_case_space_and_punctuation():
    assert normalise_header("  Employee   Membership #  ") == "employee membership"
    assert normalise_header("Paid Date") == "paid date"
    assert normalise_header("Employee\u00a0Name") == "employee name"


def test_normalise_header_keeps_digits():
    assert normalise_header("Period 1 To") == "period 1 to"


def test_normalise_header_folds_nbsp_and_tab_as_whitespace():
    # The docstring promises NBSP and tabs are whitespace like any other.
    # A heading pasted from a spreadsheet often carries a non-breaking space
    # (U+00A0) instead of an ordinary one, and it must not glue the words
    # together.
    assert normalise_header("Employee\u00a0Name") == "employee name"
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


EXPECTED_KEYS = {
    "xero-payroll", "xero-super",
    "myob-ar-payroll", "myob-ar-super",
    "myob-business-payroll", "myob-business-super",
    "employment-hero-payroll", "employment-hero-super",
}


def test_all_eight_profiles_load():
    assert {p.key for p in load_profiles()} == EXPECTED_KEYS


def test_super_profiles_can_isolate_super_guarantee():
    # Without a contribution-type column the importer cannot exclude salary
    # sacrifice, and summing everything overstates the SG figure.
    super_profiles = load_profiles("super")
    assert len(super_profiles) == 4, f"expected 4 super profiles, got {len(super_profiles)}"
    for p in super_profiles:
        assert p.sg_filter is not None, f"{p.key} has no sg_filter"
        assert p.sg_filter.column == "contribution_type"


def test_payroll_profiles_map_a_payday():
    payroll_profiles = load_profiles("payroll")
    assert len(payroll_profiles) == 4, f"expected 4 payroll profiles, got {len(payroll_profiles)}"
    for p in payroll_profiles:
        assert "payday" in p.columns, f"{p.key} maps no payday"


def test_profile_data_is_declared_as_package_data():
    # data/*.json does not glob into data/profiles/. Without this line
    # `pip install .` ships a CLI whose importers cannot start.
    root = Path(__file__).resolve().parents[1]
    pyproject_text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "data/profiles/*.json" in pyproject_text


def test_load_profiles_returns_both_roles():
    profiles = load_profiles()
    assert profiles, "no profiles shipped"
    assert {p.role for p in profiles} == {"payroll", "super"}
    assert all(isinstance(p, Profile) for p in profiles)


def test_load_profiles_filters_by_role():
    super_profiles = load_profiles("super")
    assert len(super_profiles) == 4, f"expected 4 super profiles, got {len(super_profiles)}"
    assert all(p.role == "super" for p in super_profiles)


def test_every_shipped_profile_is_marked_unverified():
    # Flip a profile to verified only after it has met a real export.
    assert all(p.verified is False for p in load_profiles())
