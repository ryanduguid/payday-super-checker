import json
from pathlib import Path

import pytest

from paydaysuper import profiles
from paydaysuper.csv_io import CsvError
from paydaysuper.profiles import normalise_header, Profile, load_profiles
from paydaysuper.profiles import detect, resolve_columns, score


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


MYOB_SUPER = ["Employee Name", "Superannuation Category", "Period From", "Period To", "Paid Date", "Amount"]


def test_score_is_none_when_a_signature_heading_is_missing():
    profile = next(p for p in load_profiles("super") if p.key == "myob-ar-super")
    assert score(profile, ["Employee Name", "Amount"]) is None


def test_detect_picks_the_profile_whose_signature_fits():
    assert detect(MYOB_SUPER, "super").key == "myob-ar-super"


def test_detect_refuses_when_nothing_matches_and_names_what_was_wanted():
    with pytest.raises(CsvError) as exc:
        detect(["Name", "Total"], "super")
    message = str(exc.value)
    assert "Name" in message and "Total" in message
    assert "myob-ar-super" in message


def test_detect_refuses_a_tie_rather_than_guessing():
    # Xero's Superannuation Payments report and MYOB Business's Superannuation
    # payments report both use Employee, Contribution Type (or Payment date)
    # and Amount, and both accept "Payment Date" as the paid_date heading.
    # A file with exactly these four columns is a genuine tie: xero-super and
    # myob-business-super each resolve 4 fields, and picking one would guess
    # which vendor actually produced the file. Verified against the real
    # shipped profiles: employment-hero-super and myob-ar-super both fail
    # their signature check on this header row (no Status / no Employee Name
    # + Paid Date), so only the tied pair is live.
    tied = ["Employee", "Contribution Type", "Amount", "Payment Date"]
    with pytest.raises(CsvError) as exc:
        detect(tied, "super")
    assert "could not tell" in str(exc.value)


def test_vendor_override_skips_detection():
    assert detect(["anything"], "super", vendor="myob-ar-super").key == "myob-ar-super"


def test_vendor_override_rejects_an_unknown_key():
    with pytest.raises(CsvError):
        detect(MYOB_SUPER, "super", vendor="sage")


def test_an_unknown_vendor_is_not_advised_to_type_a_vendor_it_never_mentioned():
    # COSMETIC FINDING (final re-review). The unknown-vendor message always
    # ended with the advice written for one specific mistake: naming a real
    # profile key that is one half of a vendor's pair, which the OTHER file
    # then refuses. Someone who typed "quickbooks" got told to write
    # 'myob-ar' instead of 'myob-ar-payroll', two names they had never used
    # and neither of which this tool has a profile for.
    with pytest.raises(CsvError) as exc:
        detect(MYOB_SUPER, "super", vendor="quickbooks")
    message = str(exc.value)
    assert "matches no super profile" in message
    assert "myob" not in message.replace("myob-ar-super", "").replace(
        "myob-business-super", ""
    )
    assert "name the stem" not in message
    # What is available is still listed. That is the part that answers the
    # question this user actually asked.
    assert "xero-super" in message


def test_a_vendors_own_key_worn_too_long_is_told_the_stem_it_shares():
    # The other side of the same gate, and the mistake the advice was
    # written for: the import command passes ONE --vendor to both files, so
    # the payroll profile's own key fails on the super file. The stem is
    # named from what was typed now, rather than the myob pair the sentence
    # used to hard-code whatever the vendor was.
    with pytest.raises(CsvError) as exc:
        detect(MYOB_SUPER, "super", vendor="xero-payroll")
    message = str(exc.value)
    assert "matches no super profile" in message
    assert "'xero'" in message
    assert "'xero-payroll'" in message
    assert "myob" not in message.replace("myob-ar-super", "").replace(
        "myob-business-super", ""
    )


def test_vendor_prefix_matching_exactly_one_profile_resolves_it():
    # "employment-hero" is a prefix of only one super profile's key.
    assert detect(["anything"], "super", vendor="employment-hero").key == "employment-hero-super"


def test_vendor_prefix_matching_more_than_one_profile_raises_naming_both():
    # "myob" is a prefix of both myob-ar-super and myob-business-super.
    # Picking one silently would feed the wrong column mapping into a legal
    # deadline calculation, so this must refuse like the no-vendor tie does.
    with pytest.raises(CsvError) as exc:
        detect(["anything"], "super", vendor="myob")
    message = str(exc.value)
    assert "myob-ar-super" in message
    assert "myob-business-super" in message


def _write_profiles(tmp_path, specs):
    for i, overrides in enumerate(specs):
        base = {
            "name": overrides.get("key", f"profile-{i}"),
            "role": "super",
            "signature": ["Employee"],
            "columns": {"employee_name": ["Employee"], "amount": ["Amount"]},
        }
        base.update(overrides)
        (tmp_path / f"profile-{i}.json").write_text(json.dumps(base), encoding="utf-8")


def test_vendor_exact_key_wins_over_a_prefix_collision(tmp_path, monkeypatch):
    # A vendor string that is itself a full profile key must resolve to that
    # profile outright, even when the same string is also a valid
    # startswith-prefix of a different profile's key (here "myob-ar" starts
    # with "myob-"). Exact match is not merely tried first, it must win
    # without ever considering the prefix branch as an ambiguity.
    monkeypatch.setattr(profiles, "PROFILE_DIR", tmp_path)
    _write_profiles(tmp_path, [{"key": "myob"}, {"key": "myob-ar"}])
    assert detect(["anything"], "super", vendor="myob").key == "myob"


def test_detect_picks_the_strictly_higher_scorer_among_several_live_profiles():
    # Three real super profiles are live on this header row with different
    # scores (verified by printing every profile's score first): xero-super
    # resolves 6 fields, employment-hero-super and myob-business-super each
    # resolve 5, myob-ar-super fails its signature and is not live at all.
    # The top score is not tied with the runner-up, so detect must return
    # the strict winner rather than falling through to any tie logic.
    headers = [
        "Employee", "Employee Number", "Contribution Type", "Amount",
        "Payment Date", "Period From", "Status",
    ]
    assert detect(headers, "super").key == "xero-super"


def test_resolve_columns_returns_the_actual_heading():
    profile = detect(MYOB_SUPER, "super")
    resolved = resolve_columns(profile, MYOB_SUPER)
    assert resolved["paid_date"] == "Paid Date"
    assert resolved["contribution_type"] == "Superannuation Category"
    assert "employee_id" not in resolved  # MYOB export has no Card ID column


def test_shipped_beam_status_ladder_is_fully_classified():
    # Every status Beam runs (see the profile's notes) must land in exactly
    # one of the two lists: a status in neither is refused at read time, and
    # a missing rung here would refuse real exports.
    profile = next(p for p in load_profiles("super") if p.key == "employment-hero-super")
    ladder = profile.remitted_status
    assert ladder is not None
    assert ladder.column == "status"
    assert set(ladder.sent) == {"Awaiting clearance", "Sent to fund", "Reconciled"}
    assert set(ladder.not_sent) == {"Created", "Submission accepted", "Awaiting payment"}


def test_only_the_employment_hero_super_profile_classifies_a_status():
    # The other vendors export a bare date with no status column; a profile
    # growing one must classify it deliberately, not inherit this gate.
    for p in load_profiles():
        if p.key != "employment-hero-super":
            assert p.remitted_status is None, p.key


def test_remitted_status_list_as_a_string_raises_csv_error(tmp_path, monkeypatch):
    # Same failure mode as sg_filter.include: a string is iterable, so
    # "sent": "Reconciled" would silently build single-letter statuses.
    monkeypatch.setattr(profiles, "PROFILE_DIR", tmp_path)
    _write_profile(
        tmp_path,
        {
            "remitted_status": {
                "column": "contribution_type",
                "sent": "Reconciled",
                "not_sent": ["Created"],
            }
        },
    )
    with pytest.raises(CsvError):
        profiles.load_profiles()


def test_remitted_status_with_a_status_in_both_lists_raises_csv_error(tmp_path, monkeypatch):
    # One status cannot mean both "the money left" and "it did not", and the
    # comparison folds case, so "Created" and "created" collide too.
    monkeypatch.setattr(profiles, "PROFILE_DIR", tmp_path)
    _write_profile(
        tmp_path,
        {
            "remitted_status": {
                "column": "contribution_type",
                "sent": ["Created"],
                "not_sent": ["created"],
            }
        },
    )
    with pytest.raises(CsvError, match="both"):
        profiles.load_profiles()
