# Payroll Export Importers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user run the checker against the two reports their payroll system already produces, instead of hand-writing a column mapping.

**Architecture:** A front end that reads a payroll export and a super payments export through declarative vendor profiles, joins them, and writes the existing canonical contributions CSV. Nothing in the audited calculation path (`csv_io.py`, `deadlines.py`, `sgc.py`, `report.py`) changes behaviour.

**Tech Stack:** Python 3.10+, standard library only. pytest for tests. Profiles are JSON data files shipped as package data.

## Global Constraints

- Python 3.10 or later. No runtime dependencies. `holidays` stays dev-only.
- Runtime strings stay ASCII. Non-console stdout on Windows is cp1252 and a non-ASCII byte kills a redirected run.
- Read every CSV with `encoding="utf-8-sig"`. Write every CSV with `newline=""`.
- Every string written to a CSV passes through `csv_safe` from `paydaysuper/report.py:55`. Do not reimplement it.
- Raise `CsvError` from `paydaysuper/csv_io.py:45` for every user-facing failure. Do not add a new exception subclass: `CsvError` already subclasses `ValueError` and a further layer invites the swallowing bug this repo has hit before.
- No client data in any fixture. Every fixture header says it is synthetic.
- Every profile JSON ships `"verified": false` until someone runs it against a real export.
- Commit identity is already pinned repo-local. Do not pass `--author`.
- Do not push. Pushing needs Ryan's own PowerShell for the credential prompt.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `paydaysuper/profiles.py` | Load and validate profile JSON, normalise headers, score and pick a profile, resolve canonical field to actual heading |
| `paydaysuper/importers.py` | Read source rows through a profile, filter to SG, join payroll to super, write the canonical CSV |
| `paydaysuper/data/profiles/*.json` | Eight vendor profiles |
| `paydaysuper/cli.py` | Dispatch `import` to a second parser; existing invocation untouched |
| `tests/test_profiles.py` | Normalisation, loading, validation, detection, ambiguity refusal |
| `tests/test_importers.py` | Reading, SG filter, join cases, canonical output, injection guard |
| `tests/fixtures/importers/*.csv` | Synthetic vendor-shaped exports |
| `pyproject.toml` | Add `data/profiles/*.json` to package-data |
| `README.md` | Import section |

---

### Task 1: Header normalisation and profile loading

**Files:**
- Create: `paydaysuper/profiles.py`
- Test: `tests/test_profiles.py`

**Interfaces:**
- Consumes: `CsvError` from `paydaysuper.csv_io`
- Produces: `normalise_header(text) -> str`, `SgFilter`, `Profile`, `load_profiles(role=None) -> list[Profile]`, `PROFILE_DIR`, `SOURCE_FIELDS`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profiles.py
import pytest

from paydaysuper.csv_io import CsvError
from paydaysuper.profiles import Profile, load_profiles, normalise_header


def test_normalise_header_folds_case_space_and_punctuation():
    assert normalise_header("  Employee   Membership #  ") == "employee membership"
    assert normalise_header("Paid Date") == "paid date"
    assert normalise_header("Employee Name") == "employee name"


def test_normalise_header_keeps_digits():
    assert normalise_header("Period 1 To") == "period 1 to"


def test_load_profiles_returns_both_roles():
    profiles = load_profiles()
    assert profiles, "no profiles shipped"
    assert {p.role for p in profiles} == {"payroll", "super"}
    assert all(isinstance(p, Profile) for p in profiles)


def test_load_profiles_filters_by_role():
    assert all(p.role == "super" for p in load_profiles("super"))


def test_every_shipped_profile_is_marked_unverified():
    # Flip a profile to verified only after it has met a real export.
    assert all(p.verified is False for p in load_profiles())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_profiles.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'paydaysuper.profiles'`

- [ ] **Step 3: Write minimal implementation**

```python
# paydaysuper/profiles.py
"""Vendor export profiles.

A profile is data, not code: adding a payroll system means writing a JSON
file, and correcting a column name someone renamed is a one-line edit.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .csv_io import CsvError

PROFILE_DIR = Path(__file__).with_name("data") / "profiles"

ROLES = ("payroll", "super")

# Canonical field names a profile may map. A profile naming anything else is
# a typo, and a typo that reaches match time looks like a missing column.
SOURCE_FIELDS = {
    "employee_id",
    "employee_name",
    "payday",
    "period_start",
    "period_end",
    "paid_date",
    "amount",
    "contribution_type",
    "status",
}

_PUNCT = re.compile(r"[^0-9a-z ]+")
_SPACES = re.compile(r"\s+")


def normalise_header(text: str) -> str:
    """Fold a heading to its comparable form: no case, no punctuation, one
    space between words. NBSP and tabs are whitespace like any other."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = _SPACES.sub(" ", folded)
    folded = _PUNCT.sub("", folded)
    return _SPACES.sub(" ", folded).strip()


@dataclass(frozen=True)
class SgFilter:
    column: str
    include: tuple[str, ...]


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    role: str
    verified: bool
    signature: tuple[str, ...]
    columns: dict[str, tuple[str, ...]]
    date_formats: tuple[str, ...]
    sg_filter: SgFilter | None
    notes: str


def _require(raw: dict, field: str, path: Path, kind: type):
    if field not in raw:
        raise CsvError(f"profile {path.name} has no {field!r}")
    value = raw[field]
    if not isinstance(value, kind):
        raise CsvError(
            f"profile {path.name}: {field!r} must be {kind.__name__}, got "
            f"{type(value).__name__}"
        )
    return value


def _build(raw: dict, path: Path) -> Profile:
    role = _require(raw, "role", path, str)
    if role not in ROLES:
        raise CsvError(f"profile {path.name}: role {role!r} is not one of {list(ROLES)}")
    columns_raw = _require(raw, "columns", path, dict)
    unknown = sorted(set(columns_raw) - SOURCE_FIELDS)
    if unknown:
        raise CsvError(
            f"profile {path.name} maps unknown field(s) {unknown}; valid fields "
            f"are {sorted(SOURCE_FIELDS)}"
        )
    columns = {}
    for field, headings in columns_raw.items():
        if not isinstance(headings, list) or not headings:
            raise CsvError(
                f"profile {path.name}: {field!r} must be a non-empty list of headings"
            )
        columns[field] = tuple(str(h) for h in headings)
    sg_raw = raw.get("sg_filter")
    sg_filter = None
    if sg_raw is not None:
        if not isinstance(sg_raw, dict) or "column" not in sg_raw or "include" not in sg_raw:
            raise CsvError(f"profile {path.name}: sg_filter needs 'column' and 'include'")
        if sg_raw["column"] not in columns:
            raise CsvError(
                f"profile {path.name}: sg_filter column {sg_raw['column']!r} is not "
                "one of the mapped columns"
            )
        sg_filter = SgFilter(
            column=str(sg_raw["column"]),
            include=tuple(str(v) for v in sg_raw["include"]),
        )
    return Profile(
        key=_require(raw, "key", path, str),
        name=_require(raw, "name", path, str),
        role=role,
        verified=bool(raw.get("verified", False)),
        signature=tuple(str(h) for h in _require(raw, "signature", path, list)),
        columns=columns,
        date_formats=tuple(str(f) for f in raw.get("date_formats", ())),
        sg_filter=sg_filter,
        notes=str(raw.get("notes", "")),
    )


def load_profiles(role: str | None = None) -> list[Profile]:
    if role is not None and role not in ROLES:
        raise CsvError(f"unknown profile role {role!r}")
    profiles = []
    for path in sorted(PROFILE_DIR.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CsvError(f"profile {path.name} is not valid JSON: {exc}")
        if not isinstance(raw, dict):
            raise CsvError(f"profile {path.name} must be a JSON object")
        profiles.append(_build(raw, path))
    keys = [p.key for p in profiles]
    duplicates = sorted({k for k in keys if keys.count(k) > 1})
    if duplicates:
        raise CsvError(f"duplicate profile key(s): {duplicates}")
    if role is None:
        return profiles
    return [p for p in profiles if p.role == role]
```

- [ ] **Step 4: Run test to verify it fails on the missing profiles only**

Run: `python -m pytest tests/test_profiles.py -v`
Expected: the three `normalise_header` tests PASS; the `load_profiles` tests FAIL because no JSON exists yet. That is correct at this point — Task 2 supplies the files.

- [ ] **Step 5: Commit**

```bash
git add paydaysuper/profiles.py tests/test_profiles.py
git commit -m "feat: profile schema and header normalisation"
```

---

### Task 2: The eight profile files and their packaging

**Files:**
- Create: `paydaysuper/data/profiles/xero-payroll.json`, `xero-super.json`, `myob-ar-payroll.json`, `myob-ar-super.json`, `myob-business-payroll.json`, `myob-business-super.json`, `employment-hero-payroll.json`, `employment-hero-super.json`
- Modify: `pyproject.toml:33`
- Test: `tests/test_profiles.py`

**Interfaces:**
- Consumes: `Profile`, `load_profiles` from Task 1
- Produces: eight loadable profiles, keys `xero-payroll`, `xero-super`, `myob-ar-payroll`, `myob-ar-super`, `myob-business-payroll`, `myob-business-super`, `employment-hero-payroll`, `employment-hero-super`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_profiles.py
import tomllib
from pathlib import Path

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
    for p in load_profiles("super"):
        assert p.sg_filter is not None, f"{p.key} has no sg_filter"
        assert p.sg_filter.column == "contribution_type"


def test_payroll_profiles_map_a_payday():
    for p in load_profiles("payroll"):
        assert "payday" in p.columns, f"{p.key} maps no payday"


def test_profile_data_is_declared_as_package_data():
    # data/*.json does not glob into data/profiles/. Without this line
    # `pip install .` ships a CLI whose importers cannot start.
    root = Path(__file__).resolve().parents[1]
    cfg = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = cfg["tool"]["setuptools"]["package-data"]["paydaysuper"]
    assert "data/profiles/*.json" in patterns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_profiles.py -v`
Expected: FAIL, `AssertionError` on the empty key set, and FAIL on the package-data assertion.

- [ ] **Step 3: Write the profile files**

`paydaysuper/data/profiles/xero-super.json`:

```json
{
  "key": "xero-super",
  "name": "Xero Payroll - Superannuation Payments",
  "role": "super",
  "verified": false,
  "signature": ["Employee", "Contribution Type", "Amount"],
  "columns": {
    "employee_name": ["Employee", "Employee Name"],
    "employee_id": ["Employee Number", "Employee Code"],
    "period_start": ["Period Start", "Pay Period Start", "Period From"],
    "period_end": ["Period End", "Pay Period End", "Period To"],
    "paid_date": ["Payment Date", "Super Payment Date", "Date Sent To Fund", "Sent To Fund"],
    "amount": ["Amount", "Super Amount"],
    "contribution_type": ["Contribution Type"]
  },
  "date_formats": ["%d/%m/%Y", "%Y-%m-%d", "%d %b %Y"],
  "sg_filter": {
    "column": "contribution_type",
    "include": ["Superannuation Guarantee", "SGC", "SG", "Employer Contributions"]
  },
  "notes": "Column names inferred from Xero Central, which publishes no column list. Xero groups this report by Contribution Type, so that column exists. The date is when the payment was sent to the fund, never when the fund received it."
}
```

`paydaysuper/data/profiles/xero-payroll.json`:

```json
{
  "key": "xero-payroll",
  "name": "Xero Payroll - Payroll Activity Details",
  "role": "payroll",
  "verified": false,
  "signature": ["Employee", "Payment Date"],
  "columns": {
    "employee_name": ["Employee", "Employee Name"],
    "employee_id": ["Employee Number", "Employee Code"],
    "payday": ["Payment Date", "Paid Date"],
    "period_end": ["Pay Period End", "Period End"],
    "amount": ["Superannuation", "Super Guarantee", "Superannuation Guarantee", "Qualifying Earnings Super"]
  },
  "date_formats": ["%d/%m/%Y", "%Y-%m-%d", "%d %b %Y"],
  "notes": "Xero Central publishes no column list for this report. The report period is the pay run payment date."
}
```

`paydaysuper/data/profiles/myob-ar-super.json`:

```json
{
  "key": "myob-ar-super",
  "name": "MYOB AccountRight - Superannuation Payments by Employee",
  "role": "super",
  "verified": false,
  "signature": ["Employee Name", "Paid Date", "Amount"],
  "columns": {
    "employee_name": ["Employee Name", "Employee"],
    "employee_id": ["Card ID", "Employee ID"],
    "period_start": ["Period From"],
    "period_end": ["Period To"],
    "paid_date": ["Paid Date"],
    "amount": ["Amount"],
    "contribution_type": ["Superannuation Category"]
  },
  "date_formats": ["%d/%m/%Y", "%d/%m/%y"],
  "sg_filter": {
    "column": "contribution_type",
    "include": ["Superannuation Guarantee", "SGC", "SG"]
  },
  "notes": "Field names come from MYOB help text, not a real export. Paid Date is when MYOB recorded the payment, not when the fund received it."
}
```

`paydaysuper/data/profiles/myob-ar-payroll.json`:

```json
{
  "key": "myob-ar-payroll",
  "name": "MYOB AccountRight - Payroll Activity [Detail]",
  "role": "payroll",
  "verified": false,
  "signature": ["Employee Name", "Date"],
  "columns": {
    "employee_name": ["Employee Name", "Employee"],
    "employee_id": ["Card ID", "Employee ID"],
    "payday": ["Date", "Payment Date", "Cheque Date"],
    "period_end": ["Pay Period End", "Period To"],
    "amount": ["Superannuation Guarantee", "Superannuation", "Amount"]
  },
  "date_formats": ["%d/%m/%Y", "%d/%m/%y"],
  "notes": "MYOB publishes no column list for this report."
}
```

`paydaysuper/data/profiles/myob-business-super.json`:

```json
{
  "key": "myob-business-super",
  "name": "MYOB Business - Superannuation payments",
  "role": "super",
  "verified": false,
  "signature": ["Employee", "Payment date", "Amount"],
  "columns": {
    "employee_name": ["Employee", "Employee name"],
    "employee_id": ["Employee ID"],
    "period_start": ["Pay period start", "Period from"],
    "period_end": ["Pay period end", "Period to"],
    "paid_date": ["Payment date", "Paid date"],
    "amount": ["Amount"],
    "contribution_type": ["Super category", "Contribution type"]
  },
  "date_formats": ["%d/%m/%Y", "%Y-%m-%d"],
  "sg_filter": {
    "column": "contribution_type",
    "include": ["Superannuation Guarantee", "SGC", "SG"]
  },
  "notes": "MYOB Business exports to Excel; column names are inferred, not published."
}
```

`paydaysuper/data/profiles/myob-business-payroll.json`:

```json
{
  "key": "myob-business-payroll",
  "name": "MYOB Business - Payroll activity",
  "role": "payroll",
  "verified": false,
  "signature": ["Employee", "Payment date"],
  "columns": {
    "employee_name": ["Employee", "Employee name"],
    "employee_id": ["Employee ID"],
    "payday": ["Payment date", "Date"],
    "period_end": ["Pay period end", "Period to"],
    "amount": ["Superannuation guarantee", "Superannuation", "Super"]
  },
  "date_formats": ["%d/%m/%Y", "%Y-%m-%d"],
  "notes": "MYOB publishes no column list for this report."
}
```

`paydaysuper/data/profiles/employment-hero-super.json`:

```json
{
  "key": "employment-hero-super",
  "name": "Employment Hero / KeyPay - Super Contributions (payments)",
  "role": "super",
  "verified": false,
  "signature": ["Employee", "Amount", "Status"],
  "columns": {
    "employee_name": ["Employee", "Employee Name"],
    "employee_id": ["Employee Id", "External Id", "Payroll Id"],
    "period_start": ["Period Start", "Pay Period Start"],
    "period_end": ["Period End", "Pay Period End"],
    "paid_date": ["Payment Date", "Date Paid", "Paid Date"],
    "amount": ["Amount"],
    "contribution_type": ["Contribution Type", "Super Contribution Type"],
    "status": ["Status"]
  },
  "date_formats": ["%d/%m/%Y", "%Y-%m-%d"],
  "sg_filter": {
    "column": "contribution_type",
    "include": ["Super Guarantee", "Superannuation Guarantee", "SGC", "SG", "Employer Contributions"]
  },
  "notes": "The payments CSV carries a Status column at the far right. Beam statuses run Created, Submission accepted, Awaiting payment, Awaiting clearance, Sent to fund, Reconciled. None of them is a fund receipt date."
}
```

`paydaysuper/data/profiles/employment-hero-payroll.json`:

```json
{
  "key": "employment-hero-payroll",
  "name": "Employment Hero / KeyPay - Detailed Activity Report",
  "role": "payroll",
  "verified": false,
  "signature": ["Employee", "Date Paid"],
  "columns": {
    "employee_name": ["Employee", "Employee Name"],
    "employee_id": ["Employee Id", "External Id", "Payroll Id"],
    "payday": ["Date Paid", "Payment Date"],
    "period_end": ["Pay Period Ending", "Period End"],
    "amount": ["Super Guarantee", "Superannuation", "Employer Contributions"]
  },
  "date_formats": ["%d/%m/%Y", "%Y-%m-%d"],
  "notes": "From 1 July 2026 Employment Hero renames its OTE report to OTE/QE and adds a QE column, because qualifying earnings replace ordinary time earnings as the SG base."
}
```

- [ ] **Step 4: Add the package-data line**

In `pyproject.toml`, replace line 33:

```toml
paydaysuper = ["data/*.json", "data/profiles/*.json"]
```

`MANIFEST.in:3` already reads `recursive-include paydaysuper/data *.json`, so the sdist is covered. Do not change it.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_profiles.py -v`
Expected: PASS, all tests including `test_profile_data_is_declared_as_package_data`.

- [ ] **Step 6: Commit**

```bash
git add paydaysuper/data/profiles pyproject.toml tests/test_profiles.py
git commit -m "feat: ship eight vendor profiles as package data"
```

---

### Task 3: Detection and column resolution

**Files:**
- Modify: `paydaysuper/profiles.py`
- Test: `tests/test_profiles.py`

**Interfaces:**
- Consumes: `Profile`, `normalise_header`, `load_profiles`
- Produces: `score(profile, headers) -> int | None`, `detect(headers, role, vendor=None) -> Profile`, `resolve_columns(profile, headers) -> dict[str, str]`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_profiles.py
from paydaysuper.profiles import detect, resolve_columns, score

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
    # Two profiles matching equally cannot be told apart, and picking the
    # first would silently read the wrong column as the amount.
    tied = ["Employee", "Contribution Type", "Amount", "Status", "Payment Date"]
    with pytest.raises(CsvError) as exc:
        detect(tied, "super")
    assert "could not tell" in str(exc.value)


def test_vendor_override_skips_detection():
    assert detect(["anything"], "super", vendor="myob-ar-super").key == "myob-ar-super"


def test_vendor_override_rejects_an_unknown_key():
    with pytest.raises(CsvError):
        detect(MYOB_SUPER, "super", vendor="sage")


def test_resolve_columns_returns_the_actual_heading():
    profile = detect(MYOB_SUPER, "super")
    resolved = resolve_columns(profile, MYOB_SUPER)
    assert resolved["paid_date"] == "Paid Date"
    assert resolved["contribution_type"] == "Superannuation Category"
    assert "employee_id" not in resolved  # MYOB export has no Card ID column
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_profiles.py -k "score or detect or resolve" -v`
Expected: FAIL, `ImportError: cannot import name 'detect'`

- [ ] **Step 3: Write the implementation**

Append to `paydaysuper/profiles.py`:

```python
def _index(headers: list[str]) -> dict[str, str]:
    """Normalised heading to the heading as it appears in the file."""
    found: dict[str, str] = {}
    for h in headers:
        if h is None:
            continue
        key = normalise_header(h)
        if key and key not in found:
            found[key] = h
    return found


def resolve_columns(profile: Profile, headers: list[str]) -> dict[str, str]:
    """Canonical field to the heading this file actually uses. A field whose
    headings are all absent is left out, not set to None: the caller decides
    whether it can proceed without it."""
    found = _index(headers)
    resolved = {}
    for field, candidates in profile.columns.items():
        for candidate in candidates:
            actual = found.get(normalise_header(candidate))
            if actual is not None:
                resolved[field] = actual
                break
    return resolved


def score(profile: Profile, headers: list[str]) -> int | None:
    """How well this profile fits, or None when a signature heading is
    missing. A missing signature heading is disqualifying, not a low score."""
    found = _index(headers)
    for heading in profile.signature:
        if normalise_header(heading) not in found:
            return None
    return len(resolve_columns(profile, headers))


def detect(headers: list[str], role: str, vendor: str | None = None) -> Profile:
    profiles = load_profiles(role)
    if vendor is not None:
        for profile in profiles:
            if profile.key == vendor or profile.key.startswith(f"{vendor}-"):
                return profile
        raise CsvError(
            f"--vendor {vendor!r} matches no {role} profile. Available: "
            f"{sorted(p.key for p in profiles)}"
        )
    scored = [(score(p, headers), p) for p in profiles]
    live = [(s, p) for s, p in scored if s is not None]
    if not live:
        wanted = "; ".join(
            f"{p.key} wanted {list(p.signature)}" for _, p in sorted(scored, key=lambda x: x[1].key)
        )
        raise CsvError(
            f"no {role} profile recognises these columns: {headers}. Candidates: "
            f"{wanted}. Force one with --vendor, or map the columns by hand."
        )
    live.sort(key=lambda x: (-x[0], x[1].key))
    if len(live) > 1 and live[0][0] == live[1][0]:
        raise CsvError(
            f"could not tell {live[0][1].key} from {live[1][1].key} for this {role} "
            f"file: both match {live[0][0]} column(s). Force one with --vendor."
        )
    return live[0][1]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_profiles.py -v`
Expected: PASS. If `test_detect_refuses_a_tie_rather_than_guessing` does not raise, the tied header list needs a heading each rival profile maps equally; adjust the fixture headings until two profiles score the same, and keep the test.

- [ ] **Step 5: Commit**

```bash
git add paydaysuper/profiles.py tests/test_profiles.py
git commit -m "feat: profile detection with refusal on ties and no match"
```

---

### Task 4: Reading source rows and filtering to super guarantee

**Files:**
- Create: `paydaysuper/importers.py`
- Create: `tests/fixtures/importers/myob_super.csv`, `tests/fixtures/importers/myob_payroll.csv`
- Test: `tests/test_importers.py`

**Interfaces:**
- Consumes: `detect`, `resolve_columns`, `Profile` from `paydaysuper.profiles`; `CsvError`, `parse_date_text`, `_parse_amount` behaviour from `paydaysuper.csv_io`
- Produces: `PayrollRow`, `SuperRow`, `read_payroll(path, vendor=None) -> tuple[list[PayrollRow], Profile]`, `read_super(path, vendor=None) -> tuple[list[SuperRow], Profile]`

- [ ] **Step 1: Write the fixtures**

`tests/fixtures/importers/myob_super.csv` (synthetic, no client data):

```csv
Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount
Test Employee One,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,612.00
Test Employee One,Salary Sacrifice,01/07/2026,09/07/2026,14/07/2026,200.00
Test Employee Two,Superannuation Guarantee,01/07/2026,09/07/2026,30/07/2026,540.00
```

`tests/fixtures/importers/myob_payroll.csv` (synthetic, no client data):

```csv
Employee Name,Date,Pay Period End,Superannuation Guarantee
Test Employee One,09/07/2026,09/07/2026,612.00
Test Employee Two,09/07/2026,09/07/2026,540.00
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_importers.py
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from paydaysuper.csv_io import CsvError
from paydaysuper.importers import read_payroll, read_super

FIXTURES = Path(__file__).parent / "fixtures" / "importers"


def test_read_super_keeps_only_super_guarantee():
    rows, profile = read_super(FIXTURES / "myob_super.csv")
    assert profile.key == "myob-ar-super"
    assert len(rows) == 2, "salary sacrifice row was not excluded"
    assert {r.amount for r in rows} == {Decimal("612.00"), Decimal("540.00")}


def test_read_super_reads_australian_day_first_dates():
    rows, _ = read_super(FIXTURES / "myob_super.csv")
    assert rows[0].paid_date == date(2026, 7, 14)
    assert rows[0].period_end == date(2026, 7, 9)


def test_read_payroll_reads_payday_and_amount():
    rows, profile = read_payroll(FIXTURES / "myob_payroll.csv")
    assert profile.key == "myob-ar-payroll"
    assert rows[0].payday == date(2026, 7, 9)
    assert rows[0].sg_amount == Decimal("612.00")


def test_super_file_without_a_contribution_type_column_is_refused(tmp_path):
    # Summing every contribution type would fold salary sacrifice into the SG
    # figure and understate the shortfall.
    path = tmp_path / "no_type.csv"
    path.write_text(
        "Employee Name,Period From,Period To,Paid Date,Amount\n"
        "Test Employee One,01/07/2026,09/07/2026,14/07/2026,612.00\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError) as exc:
        read_super(path, vendor="myob-ar-super")
    assert "contribution type" in str(exc.value).lower()


def test_mis_grouped_amount_is_refused(tmp_path):
    path = tmp_path / "bad_amount.csv"
    path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "Test Employee One,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,\"612,00\"\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError):
        read_super(path, vendor="myob-ar-super")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_importers.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'paydaysuper.importers'`

- [ ] **Step 4: Write the implementation**

```python
# paydaysuper/importers.py
"""Read a payroll export and a super payments export, join them, and write
the canonical contributions CSV.

No vendor export carries a fund receipt date. Xero gives the date a payment
was sent to the fund, MYOB gives a Paid Date, Employment Hero gives a Beam
status. The deadline in s 18C tests receipt, and clearing-house transit is
the employer's risk, so every vendor date lands in `remitted` and the receipt
column is left empty.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .csv_io import CsvError, parse_date_text
from .profiles import Profile, detect, normalise_header, resolve_columns

# A separator is allowed only where a thousands separator belongs. Stripping
# every comma turns the European decimal 612,00 into 61200.
_AMOUNT = re.compile(r"^-?\d{1,3}(?:[ ,]\d{3})*(?:\.\d+)?$|^-?\d+(?:\.\d+)?$")


@dataclass(frozen=True)
class PayrollRow:
    employee_id: str | None
    employee_name: str | None
    payday: date
    period_end: date | None
    sg_amount: Decimal
    row: int

    @property
    def effective_period_end(self) -> date:
        return self.period_end or self.payday


@dataclass(frozen=True)
class SuperRow:
    employee_id: str | None
    employee_name: str | None
    period_start: date | None
    period_end: date | None
    paid_date: date | None
    amount: Decimal
    row: int


def _read_dicts(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise CsvError(f"{path} has no header row")
            headers = [h for h in reader.fieldnames if h and h.strip()]
            rows = [dict(r) for r in reader]
    except UnicodeDecodeError as exc:
        raise CsvError(
            f"{path} is not UTF-8 text (byte {exc.object[exc.start]:#04x} at position "
            f"{exc.start}). Excel's plain 'CSV' export uses the Windows code page: "
            "re-save it as 'CSV UTF-8 (Comma delimited)' and run again."
        )
    if not rows:
        raise CsvError(f"{path} has a header but no data rows")
    return headers, rows


def _date(value: str, field: str, row: int, formats: tuple[str, ...]) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    parsed = parse_date_text(text)
    if parsed is None:
        raise CsvError(f"row {row}: cannot read {field} value {value!r} as a date")
    return parsed


def _amount(value: str, field: str, row: int) -> Decimal:
    text = (value or "").strip().replace("$", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    if not text:
        raise CsvError(f"row {row}: {field} is empty")
    if not _AMOUNT.match(text):
        raise CsvError(
            f"row {row}: cannot read {field} value {value!r} as an amount. A comma or "
            "space is only read as a thousands separator, so 612,00 is refused rather "
            "than read as 61200."
        )
    try:
        amount = Decimal(text.replace(",", "").replace(" ", ""))
    except InvalidOperation:
        raise CsvError(f"row {row}: cannot read {field} value {value!r} as an amount")
    if not amount.is_finite():
        raise CsvError(f"row {row}: cannot read {field} value {value!r} as an amount")
    if amount < 0:
        raise CsvError(f"row {row}: {field} is negative ({value!r})")
    return amount


def _cell(row: dict[str, str], resolved: dict[str, str], field: str) -> str:
    heading = resolved.get(field)
    if heading is None:
        return ""
    return (row.get(heading) or "").strip()


def read_super(path: str | Path, vendor: str | None = None) -> tuple[list[SuperRow], Profile]:
    headers, raw_rows = _read_dicts(path)
    profile = detect(headers, "super", vendor)
    resolved = resolve_columns(profile, headers)
    if "amount" not in resolved:
        raise CsvError(f"{path}: no amount column found for profile {profile.key}")
    if profile.sg_filter is not None and profile.sg_filter.column not in resolved:
        raise CsvError(
            f"{path} has no contribution type column, so salary sacrifice and "
            "additional contributions cannot be told apart from super guarantee. "
            "Re-run the report with that column included, or map the file by hand."
        )
    wanted = {normalise_header(v) for v in (profile.sg_filter.include if profile.sg_filter else ())}
    rows: list[SuperRow] = []
    for i, raw in enumerate(raw_rows, start=2):
        if profile.sg_filter is not None:
            kind = normalise_header(_cell(raw, resolved, profile.sg_filter.column))
            if kind not in wanted:
                continue
        rows.append(
            SuperRow(
                employee_id=_cell(raw, resolved, "employee_id") or None,
                employee_name=_cell(raw, resolved, "employee_name") or None,
                period_start=_date(_cell(raw, resolved, "period_start"), "period start", i, profile.date_formats),
                period_end=_date(_cell(raw, resolved, "period_end"), "period end", i, profile.date_formats),
                paid_date=_date(_cell(raw, resolved, "paid_date"), "paid date", i, profile.date_formats),
                amount=_amount(_cell(raw, resolved, "amount"), "amount", i),
                row=i,
            )
        )
    if not rows:
        raise CsvError(
            f"{path} has rows but none of them is super guarantee. Check the "
            f"contribution types against {list(profile.sg_filter.include)}"
            if profile.sg_filter
            else f"{path} has no usable rows"
        )
    return rows, profile


def read_payroll(path: str | Path, vendor: str | None = None) -> tuple[list[PayrollRow], Profile]:
    headers, raw_rows = _read_dicts(path)
    profile = detect(headers, "payroll", vendor)
    resolved = resolve_columns(profile, headers)
    for required in ("payday", "amount"):
        if required not in resolved:
            raise CsvError(
                f"{path}: no {required} column found for profile {profile.key}. "
                f"Columns found: {headers}"
            )
    rows: list[PayrollRow] = []
    for i, raw in enumerate(raw_rows, start=2):
        payday = _date(_cell(raw, resolved, "payday"), "payday", i, profile.date_formats)
        if payday is None:
            raise CsvError(f"row {i}: payday is empty")
        rows.append(
            PayrollRow(
                employee_id=_cell(raw, resolved, "employee_id") or None,
                employee_name=_cell(raw, resolved, "employee_name") or None,
                payday=payday,
                period_end=_date(_cell(raw, resolved, "period_end"), "period end", i, profile.date_formats),
                sg_amount=_amount(_cell(raw, resolved, "amount"), "sg amount", i),
                row=i,
            )
        )
    return rows, profile
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_importers.py -v`
Expected: PASS, all five tests.

- [ ] **Step 6: Commit**

```bash
git add paydaysuper/importers.py tests/test_importers.py tests/fixtures
git commit -m "feat: read payroll and super exports through a profile"
```

---

### Task 5: The join

**Files:**
- Modify: `paydaysuper/importers.py`
- Test: `tests/test_importers.py`

**Interfaces:**
- Consumes: `PayrollRow`, `SuperRow` from Task 4
- Produces: `MatchOutcome`, `JoinResult`, `join(payroll_rows, super_rows) -> JoinResult`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_importers.py
from paydaysuper.importers import PayrollRow, SuperRow, join


def payroll(name, payday, amount, period_end=None, row=2):
    return PayrollRow(None, name, date.fromisoformat(payday), 
                      date.fromisoformat(period_end) if period_end else None,
                      Decimal(amount), row)


def super_row(name, start, end, paid, amount, row=2):
    return SuperRow(None, name, date.fromisoformat(start), date.fromisoformat(end),
                    date.fromisoformat(paid), Decimal(amount), row)


def test_exact_match_sets_the_remittance_date():
    result = join([payroll("A", "2026-07-09", "612.00")],
                  [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00")])
    assert result.outcomes[0].remitted == date(2026, 7, 14)
    assert result.outcomes[0].flag == ""
    assert result.orphans == []


def test_split_payment_takes_the_later_date():
    # The obligation is not met until the whole amount reaches the fund.
    result = join([payroll("A", "2026-07-09", "612.00")],
                  [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "300.00", row=2),
                   super_row("A", "2026-07-01", "2026-07-09", "2026-07-21", "312.00", row=3)])
    assert result.outcomes[0].remitted == date(2026, 7, 21)
    assert result.outcomes[0].flag == ""


def test_short_payment_is_flagged_partial():
    result = join([payroll("A", "2026-07-09", "612.00")],
                  [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "500.00")])
    assert "partial" in result.outcomes[0].flag
    assert "500.00" in result.outcomes[0].flag and "612.00" in result.outcomes[0].flag


def test_overpayment_is_flagged():
    result = join([payroll("A", "2026-07-09", "612.00")],
                  [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "812.00")])
    assert "over" in result.outcomes[0].flag


def test_payday_with_no_super_payment_is_flagged_and_left_blank():
    result = join([payroll("A", "2026-07-09", "612.00")], [])
    assert result.outcomes[0].remitted is None
    assert result.outcomes[0].flag == "no super payment found"


def test_super_payment_matching_nothing_becomes_an_orphan():
    result = join([payroll("A", "2026-07-09", "612.00")],
                  [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00"),
                   super_row("B", "2026-07-01", "2026-07-09", "2026-07-14", "99.00", row=3)])
    assert [o.row for o in result.orphans] == [3]


def test_two_identical_paydays_refuse_rather_than_guess():
    # Assigning the payment to the wrong one moves the exposure to a
    # different deadline.
    with pytest.raises(CsvError) as exc:
        join([payroll("A", "2026-07-09", "612.00", row=2),
              payroll("A", "2026-07-09", "612.00", row=3)],
             [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00")])
    assert "rows 2, 3" in str(exc.value)


def test_name_matching_warns():
    result = join([payroll("A", "2026-07-09", "612.00")],
                  [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00")])
    assert result.key_mode == "name"
    assert any("name" in w for w in result.warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_importers.py -k join -v`
Expected: FAIL, `ImportError: cannot import name 'join'`

- [ ] **Step 3: Write the implementation**

Append to `paydaysuper/importers.py`:

```python
@dataclass
class MatchOutcome:
    payroll: PayrollRow
    remitted: date | None
    flag: str


@dataclass
class JoinResult:
    outcomes: list[MatchOutcome]
    orphans: list[SuperRow]
    key_mode: str
    warnings: list[str]


def _key(row, mode: str) -> str:
    value = row.employee_id if mode == "id" else row.employee_name
    return normalise_header(value or "")


def _covers(s: SuperRow, target: date) -> bool:
    if s.period_start is None and s.period_end is None:
        return True  # period-less row; the caller only reaches this for a lone payday
    start = s.period_start or s.period_end
    end = s.period_end or s.period_start
    return start <= target <= end


def join(payroll_rows: list[PayrollRow], super_rows: list[SuperRow]) -> JoinResult:
    warnings: list[str] = []
    both_have_ids = all(r.employee_id for r in payroll_rows) and all(
        r.employee_id for r in super_rows
    )
    key_mode = "id" if both_have_ids else "name"
    if key_mode == "name":
        warnings.append(
            "matched on employee name because one of the files has no id column. "
            "Two employees sharing a name would be merged."
        )

    grouped: dict[str, list[PayrollRow]] = {}
    for row in payroll_rows:
        key = _key(row, key_mode)
        if not key:
            raise CsvError(f"row {row.row}: the employee column is empty")
        grouped.setdefault(key, []).append(row)

    for key, rows in grouped.items():
        seen: dict[tuple[date, Decimal], list[int]] = {}
        for row in rows:
            seen.setdefault((row.effective_period_end, row.sg_amount), []).append(row.row)
        for (period_end, amount), numbers in seen.items():
            if len(numbers) > 1:
                joined = ", ".join(str(n) for n in sorted(numbers))
                raise CsvError(
                    f"rows {joined} are the same employee, the same pay period ending "
                    f"{period_end.isoformat()} and the same amount {amount}, so a super "
                    "payment cannot be assigned to one of them. Remove the duplicate or "
                    "give the rows distinct pay periods."
                )

    claimed: set[int] = set()
    outcomes: list[MatchOutcome] = []
    for row in payroll_rows:
        key = _key(row, key_mode)
        matches = [
            s
            for s in super_rows
            if _key(s, key_mode) == key
            and s.row not in claimed
            and (
                _covers(s, row.effective_period_end)
                if (s.period_start or s.period_end)
                else len(grouped[key]) == 1
            )
        ]
        if not matches:
            outcomes.append(MatchOutcome(row, None, "no super payment found"))
            continue
        claimed.update(s.row for s in matches)
        paid = [s.paid_date for s in matches if s.paid_date is not None]
        remitted = max(paid) if paid else None
        total = sum((s.amount for s in matches), Decimal("0"))
        flag = ""
        if total < row.sg_amount:
            flag = f"partial: {total} of {row.sg_amount} matched"
        elif total > row.sg_amount:
            flag = (
                f"over: {total} against {row.sg_amount}, check for salary sacrifice "
                "in the contribution types"
            )
        if remitted is None:
            flag = (flag + "; " if flag else "") + "matched super rows carry no payment date"
        outcomes.append(MatchOutcome(row, remitted, flag))

    orphans = [s for s in super_rows if s.row not in claimed]
    return JoinResult(outcomes, orphans, key_mode, warnings)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_importers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add paydaysuper/importers.py tests/test_importers.py
git commit -m "feat: join payroll rows to super payments"
```

---

### Task 6: Writing the canonical CSV

**Files:**
- Modify: `paydaysuper/importers.py`
- Test: `tests/test_importers.py`

**Interfaces:**
- Consumes: `JoinResult`, `MatchOutcome`; `csv_safe` from `paydaysuper.report`
- Produces: `CANONICAL_HEADER`, `write_canonical(result, path) -> None`, `ImportReport`, `import_files(payroll_path, super_path, out_path, vendor=None) -> ImportReport`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_importers.py
import csv as _csv

from paydaysuper.importers import import_files


def test_canonical_output_feeds_the_normal_check(tmp_path):
    out = tmp_path / "contributions.csv"
    report = import_files(FIXTURES / "myob_payroll.csv", FIXTURES / "myob_super.csv", out)
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert [r["employee_id"] for r in rows] == ["Test Employee One", "Test Employee Two"]
    assert rows[0]["payment_date"] == "2026-07-09"
    assert rows[0]["sg_amount"] == "612.00"
    assert rows[0]["remitted_date"] == "2026-07-14"
    assert rows[0]["fund_received_date"] == ""  # no vendor export carries it
    assert report.matched == 2


def test_a_formula_in_an_employee_name_is_guarded(tmp_path):
    src = tmp_path / "payroll.csv"
    src.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "=cmd()|'/c calc',09/07/2026,09/07/2026,612.00\n"
        "-00123,09/07/2026,09/07/2026,540.00\n",
        encoding="utf-8",
    )
    sup = tmp_path / "super.csv"
    sup.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "=cmd()|'/c calc',Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,612.00\n"
        "-00123,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,540.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    import_files(src, sup, out)
    text = out.read_text(encoding="utf-8-sig")
    assert "'=cmd()" in text, "formula lead was not neutralised"
    assert "-00123" in text and "'-00123" not in text, "a plain code was mangled"


def test_output_refuses_to_overwrite_an_input(tmp_path):
    src = tmp_path / "payroll.csv"
    src.write_text("Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
                   "A,09/07/2026,09/07/2026,1.00\n", encoding="utf-8")
    with pytest.raises(CsvError):
        import_files(src, FIXTURES / "myob_super.csv", src)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_importers.py -k canonical -v`
Expected: FAIL, `ImportError: cannot import name 'import_files'`

- [ ] **Step 3: Write the implementation**

Append to `paydaysuper/importers.py`:

```python
from .report import csv_safe  # placed here to keep the import list beside its use

CANONICAL_HEADER = [
    "employee_id",
    "payment_date",
    "sg_amount",
    "remitted_date",
    "fund_received_date",
    "first_contribution_to_fund",
    "out_of_cycle",
    "next_standard_payday",
    "defined_benefit",
]


@dataclass
class ImportReport:
    payroll_profile: Profile
    super_profile: Profile
    matched: int
    partial: int
    unmatched: int
    orphans: int
    key_mode: str
    warnings: list[str]

    @property
    def clean(self) -> bool:
        return not (self.partial or self.unmatched or self.orphans)


def _iso(value: date | None) -> str:
    return value.isoformat() if value else ""


def write_canonical(result: JoinResult, path: str | Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(CANONICAL_HEADER)
        for outcome in result.outcomes:
            row = outcome.payroll
            label = row.employee_id or row.employee_name or ""
            writer.writerow(
                [
                    csv_safe(label),
                    _iso(row.payday),
                    str(row.sg_amount.quantize(Decimal("0.01"))),
                    _iso(outcome.remitted),
                    "",  # fund receipt: no vendor export carries it
                    "",  # first contribution to fund
                    "",  # out of cycle
                    "",  # next standard payday
                    "",  # defined benefit
                ]
            )


def import_files(
    payroll_path: str | Path,
    super_path: str | Path,
    out_path: str | Path,
    vendor: str | None = None,
) -> ImportReport:
    out = Path(out_path).resolve()
    for source in (payroll_path, super_path):
        if Path(source).resolve() == out:
            raise CsvError(
                f"the output would overwrite {source}. Choose a different path with -o."
            )
    payroll_rows, payroll_profile = read_payroll(payroll_path, vendor)
    super_rows, super_profile = read_super(super_path, vendor)
    result = join(payroll_rows, super_rows)
    write_canonical(result, out)
    partial = sum(1 for o in result.outcomes if o.flag.startswith(("partial", "over")))
    unmatched = sum(1 for o in result.outcomes if o.flag == "no super payment found")
    return ImportReport(
        payroll_profile=payroll_profile,
        super_profile=super_profile,
        matched=sum(1 for o in result.outcomes if not o.flag),
        partial=partial,
        unmatched=unmatched,
        orphans=len(result.orphans),
        key_mode=result.key_mode,
        warnings=result.warnings
        + [
            f"row {o.payroll.row}: {o.flag}" for o in result.outcomes if o.flag
        ]
        + [f"super row {s.row} matched no payday" for s in result.orphans],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_importers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add paydaysuper/importers.py tests/test_importers.py
git commit -m "feat: write the canonical contributions CSV from an import"
```

---

### Task 7: The import subcommand

**Files:**
- Modify: `paydaysuper/cli.py:82-147`
- Test: `tests/test_importers.py`

**Interfaces:**
- Consumes: `import_files`, `ImportReport`
- Produces: `build_import_parser()`, `import_main(argv) -> int`; `main` dispatches when `argv[0] == "import"`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_importers.py
from paydaysuper.cli import main


def test_import_subcommand_writes_the_file(tmp_path, capsys):
    out = tmp_path / "contributions.csv"
    code = main(["import", "--payroll", str(FIXTURES / "myob_payroll.csv"),
                 "--super", str(FIXTURES / "myob_super.csv"), "-o", str(out)])
    assert code == 0
    assert out.exists()
    printed = capsys.readouterr().out
    assert "myob-ar-super" in printed
    assert "unverified" in printed
    assert "receipt" in printed.lower()


def test_import_returns_two_when_a_payday_has_no_payment(tmp_path):
    src = tmp_path / "payroll.csv"
    src.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "Test Employee One,09/07/2026,09/07/2026,612.00\n"
        "Test Employee Three,09/07/2026,09/07/2026,700.00\n",
        encoding="utf-8",
    )
    code = main(["import", "--payroll", str(src), "--super",
                 str(FIXTURES / "myob_super.csv"), "-o", str(tmp_path / "out.csv")])
    assert code == 2


def test_existing_invocation_still_works(tmp_path):
    out = tmp_path / "report.csv"
    code = main(["examples/sample_payrun.csv", "-o", str(out), "--as-at", "2026-09-01"])
    assert code in (0, 2)
    assert out.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_importers.py -k subcommand -v`
Expected: FAIL, argparse treats `import` as `csv_path` and errors on the unknown `--payroll` flag.

- [ ] **Step 3: Write the implementation**

In `paydaysuper/cli.py`, add after `build_parser`:

```python
def build_import_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="payday-super-check import",
        description=(
            "Build the contributions CSV from a payroll export and a super "
            "payments export. No payroll system exports a fund receipt date, so "
            "the receipt column is left blank for you to fill in."
        ),
    )
    parser.add_argument("--payroll", required=True, help="payroll activity export")
    parser.add_argument("--super", dest="super_path", required=True, help="super payments export")
    parser.add_argument("-o", "--output", default="contributions.csv", help="CSV to write")
    parser.add_argument(
        "--vendor",
        help="force a profile instead of detecting one (e.g. xero, myob-ar, employment-hero)",
    )
    return parser


EXIT_IMPORT_UNRESOLVED = 2


def import_main(argv: list[str]) -> int:
    from .importers import import_files

    args = build_import_parser().parse_args(argv)
    try:
        report = import_files(args.payroll, args.super_path, args.output, args.vendor)
    except (CsvError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except FileNotFoundError as exc:
        print(f"error: file not found: {exc.filename}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"error: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_ERROR

    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="backslashreplace")
    lines = [
        f"payroll profile: {report.payroll_profile.key}"
        + ("" if report.payroll_profile.verified else " (unverified against a real export)"),
        f"super profile:   {report.super_profile.key}"
        + ("" if report.super_profile.verified else " (unverified against a real export)"),
        f"matched {report.matched}, partial or over {report.partial}, "
        f"no payment {report.unmatched}, orphan super rows {report.orphans}",
        f"employee key: {report.key_mode}",
        f"wrote {args.output}",
        "",
        "No payroll export carries a fund receipt date, so fund_received_date is "
        "blank. The deadline tests receipt, not remittance: fill the column in from "
        "your fund or clearing house before relying on a charge figure.",
    ]
    for warning in report.warnings[:20]:
        lines.append(f"  - {warning}")
    if len(report.warnings) > 20:
        lines.append(f"  ... and {len(report.warnings) - 20} more")
    print("\n".join(lines))
    return EXIT_OK if report.clean else EXIT_IMPORT_UNRESOLVED
```

Then change the first line of `main` (currently `paydaysuper/cli.py:83`) from:

```python
    args = build_parser().parse_args(argv)
```

to:

```python
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "import":
        return import_main(argv[1:])
    args = build_parser().parse_args(argv)
```

- [ ] **Step 4: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS, previous 122 tests plus the new ones.

- [ ] **Step 5: Commit**

```bash
git add paydaysuper/cli.py tests/test_importers.py
git commit -m "feat: import subcommand"
```

---

### Task 8: Prove the regression tests can fail, then document

**Files:**
- Modify: `README.md`
- Test: no new file

**Interfaces:** none

- [ ] **Step 1: Prove each guard test fails against a broken implementation**

For each, make the edit, run the named test, confirm FAIL, then revert. A test that passes both ways is testing nothing, and this repo has already shipped one of those.

| Break | Test that must fail |
| --- | --- |
| In `_AMOUNT`, replace the pattern with `.*` | `test_mis_grouped_amount_is_refused` |
| In `read_super`, drop the `sg_filter` skip | `test_read_super_keeps_only_super_guarantee` |
| In `join`, change `max(paid)` to `min(paid)` | `test_split_payment_takes_the_later_date` |
| In `join`, delete the duplicate-group check | `test_two_identical_paydays_refuse_rather_than_guess` |
| In `detect`, return `live[0][1]` without the tie check | `test_detect_refuses_a_tie_rather_than_guessing` |
| In `write_canonical`, drop `csv_safe` | `test_a_formula_in_an_employee_name_is_guarded` |
| In `pyproject.toml`, revert package-data | `test_profile_data_is_declared_as_package_data` |

Record the result of each in the commit body.

- [ ] **Step 2: Verify the package still installs and runs from a wheel**

```bash
python -m pip wheel --no-deps -w dist .
python -m venv /tmp/pdsv
/tmp/pdsv/bin/pip install --no-index --find-links dist payday-super-checker
/tmp/pdsv/bin/payday-super-check import --payroll tests/fixtures/importers/myob_payroll.csv --super tests/fixtures/importers/myob_super.csv -o /tmp/c.csv
```

Expected: the command runs and writes `/tmp/c.csv`. A `FileNotFoundError` on the profiles directory means the package-data line did not take.

- [ ] **Step 3: Add the README section**

Insert after the existing usage section:

```markdown
## Import from your payroll system

Instead of writing a column mapping, point the importer at the two reports your payroll system already produces:

    payday-super-check import --payroll "Payroll Activity Details.csv" --super "Superannuation Payments.csv" -o contributions.csv
    payday-super-check contributions.csv

Profiles ship for Xero Payroll, MYOB AccountRight, MYOB Business and Employment Hero / KeyPay. Force one with `--vendor` when detection cannot pick.

**Every profile is unverified.** The column names come from vendor documentation, which does not publish a column list, so the first real export may match nothing. When that happens the importer prints the headings it found and the headings each profile wanted. Send those two lists and the profile becomes a one-line fix.

**No payroll system exports a fund receipt date.** Xero gives the date a payment was sent to the fund, MYOB gives a Paid Date, Employment Hero gives a Beam status. The deadline tests receipt by the fund, and clearing-house transit is the employer's risk, so the importer writes the vendor date to `remitted_date` and leaves `fund_received_date` blank. Fill it in from your fund or clearing house before relying on a charge figure.
```

- [ ] **Step 4: Run the whole suite one last time**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: import subcommand and its two honest limits"
```

---

## Self-Review

**Spec coverage.** Profile schema, detection with refusal, SG-only filter with refusal, employee key with name fallback warning, period bracket match, latest-date remittance, amount reconciliation table, ambiguity refusal, canonical output with blank receipt, `csv_safe`, exit codes, the eight profile files, the test list and the unverified marker each map to a task. Packaging was not in the spec and is now Task 2 Step 4 plus a test, because `data/*.json` does not glob into `data/profiles/`.

**Placeholders.** None. Every code step carries the code.

**Type consistency.** `read_payroll` and `read_super` both return `(rows, Profile)`. `join` takes the row lists only and returns `JoinResult`. `import_files` returns `ImportReport`. `CANONICAL_HEADER` matches the nine columns in `examples/sample_payrun.csv`. `csv_safe` is imported from `report.py`, not redefined.

**Known rough edge.** `test_detect_refuses_a_tie_rather_than_guessing` depends on two shipped profiles scoring equally on a synthetic header list. Task 3 Step 4 says to adjust the fixture headings until they do, rather than delete the test.
