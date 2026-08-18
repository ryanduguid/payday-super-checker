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
    """Fold a HEADING to its comparable form: no case, no punctuation, one
    space between words. NBSP and tabs are whitespace like any other.

    For headings only. It strips every character outside `[0-9a-z ]`, which
    is right for `Employee Membership #` and wrong for anything read out of
    a data cell: an employee id folds to a different employee's id, and a
    name written in Chinese, Korean, Greek, Cyrillic or Arabic folds to the
    empty string. Use `normalise_name` for a person's name, and compare ids
    exactly."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = _SPACES.sub(" ", folded)
    folded = _PUNCT.sub("", folded)
    return _SPACES.sub(" ", folded).strip()


def normalise_name(text: str) -> str:
    """Fold a person's NAME to its comparable form: no case, one space
    between words, nothing else removed.

    Punctuation stays, unlike `normalise_header`. A heading's punctuation is
    decoration; a name's is part of the name, and dropping it merges
    O'Brien into OBrien. Every character outside the Latin alphabet stays
    too, so a name in any script keeps a usable key: the guarantee this
    gives its caller is that a name with any non-whitespace character in it
    never folds to the empty string."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _SPACES.sub(" ", folded).strip()


@dataclass(frozen=True)
class SgFilter:
    column: str
    include: tuple[str, ...]


@dataclass(frozen=True)
class RemittedStatus:
    """How a vendor status column decides whether a payment left the employer.

    `sent` holds the statuses that evidence the payment was actually made;
    `not_sent` holds the ones that mean the money never left (a batch merely
    created, submitted or still awaiting the employer's payment). Both lists
    together must cover the vendor's whole ladder: a status in neither is
    refused at read time rather than guessed either way."""

    column: str
    sent: tuple[str, ...]
    not_sent: tuple[str, ...]


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
    remitted_status: RemittedStatus | None
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
        include_raw = sg_raw["include"]
        if not isinstance(include_raw, list) or not include_raw:
            raise CsvError(
                f"profile {path.name}: sg_filter 'include' must be a non-empty list "
                "of values"
            )
        sg_filter = SgFilter(
            column=str(sg_raw["column"]),
            include=tuple(str(v) for v in include_raw),
        )
    rs_raw = raw.get("remitted_status")
    remitted_status = None
    if rs_raw is not None:
        if (
            not isinstance(rs_raw, dict)
            or "column" not in rs_raw
            or "sent" not in rs_raw
            or "not_sent" not in rs_raw
        ):
            raise CsvError(
                f"profile {path.name}: remitted_status needs 'column', 'sent' and "
                "'not_sent'"
            )
        if rs_raw["column"] not in columns:
            raise CsvError(
                f"profile {path.name}: remitted_status column {rs_raw['column']!r} "
                "is not one of the mapped columns"
            )
        for list_name in ("sent", "not_sent"):
            if not isinstance(rs_raw[list_name], list) or not rs_raw[list_name]:
                raise CsvError(
                    f"profile {path.name}: remitted_status {list_name!r} must be a "
                    "non-empty list of values"
                )
        sent = tuple(str(v) for v in rs_raw["sent"])
        not_sent = tuple(str(v) for v in rs_raw["not_sent"])
        overlap = sorted(
            {normalise_header(v) for v in sent} & {normalise_header(v) for v in not_sent}
        )
        if overlap:
            # One status cannot mean both "the money left" and "it did not":
            # whichever branch read it first would silently win.
            raise CsvError(
                f"profile {path.name}: remitted_status lists {overlap} as both "
                "'sent' and 'not_sent'"
            )
        remitted_status = RemittedStatus(
            column=str(rs_raw["column"]), sent=sent, not_sent=not_sent
        )
    if "date_formats" in raw:
        date_formats_raw = raw["date_formats"]
        if not isinstance(date_formats_raw, list) or not date_formats_raw:
            raise CsvError(
                f"profile {path.name}: 'date_formats' must be a non-empty list of "
                "formats"
            )
        date_formats = tuple(str(f) for f in date_formats_raw)
    else:
        date_formats = ()
    verified_raw = raw.get("verified", False)
    if not isinstance(verified_raw, bool):
        raise CsvError(
            f"profile {path.name}: 'verified' must be true or false, got "
            f"{type(verified_raw).__name__}"
        )
    return Profile(
        key=_require(raw, "key", path, str),
        name=_require(raw, "name", path, str),
        role=role,
        verified=verified_raw,
        signature=tuple(str(h) for h in _require(raw, "signature", path, list)),
        columns=columns,
        date_formats=date_formats,
        sg_filter=sg_filter,
        remitted_status=remitted_status,
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


def _vendor_stem(vendor: str, profiles: list[Profile]) -> str | None:
    """The longest leading dash-delimited part of `vendor` that a profile in
    THIS role does answer to, or None when the name shares nothing with any
    of them.

    What tells 'myob-ar-payroll' handed to the super reader (a real key of
    this vendor's, just the wrong half of the pair, and 'myob-ar' is the
    answer) apart from 'quickbooks' (a vendor with no profiles at all,
    which no stem of any length will help)."""
    parts = vendor.split("-")
    for cut in range(len(parts) - 1, 0, -1):
        stem = "-".join(parts[:cut])
        if any(p.key == stem or p.key.startswith(f"{stem}-") for p in profiles):
            return stem
    return None


def detect(headers: list[str], role: str, vendor: str | None = None) -> Profile:
    profiles = load_profiles(role)
    if vendor is not None:
        exact = [p for p in profiles if p.key == vendor]
        if exact:
            return exact[0]
        prefixed = [p for p in profiles if p.key.startswith(f"{vendor}-")]
        if len(prefixed) > 1:
            # Advice that has to work for the `import` command, which passes
            # ONE --vendor to the payroll file and the super file together:
            # "name the exact profile key" was followed and then failed on
            # the other file, because myob-ar-payroll is not a super profile.
            # The stem both of a vendor's profiles share is the answer.
            raise CsvError(
                f"--vendor {vendor!r} matches more than one {role} profile: "
                f"{sorted(p.key for p in prefixed)}. Lengthen it until it picks one, "
                "keeping the part both files' profiles share -- 'myob-ar' rather than "
                "'myob', which picks myob-ar-payroll and myob-ar-super together. The "
                "import command passes one --vendor to both files."
            )
        if prefixed:
            return prefixed[0]
        message = (
            f"--vendor {vendor!r} matches no {role} profile. Available: "
            f"{sorted(p.key for p in profiles)}."
        )
        stem = _vendor_stem(vendor, profiles)
        if stem is not None:
            # Only where the name typed really is one of this vendor's keys
            # worn too long, which is the mistake this advice answers: the
            # user named the payroll profile and the super file refused it.
            # `--vendor quickbooks` matches nothing and shares nothing, so
            # it used to be told to type 'myob-ar', a vendor it had not
            # mentioned and does not have a profile for either.
            message += (
                " The import command passes one --vendor to the payroll file and the "
                f"super file together, so name the stem both of a vendor's profiles "
                f"start with -- {stem!r}, not {vendor!r}, which is not a {role} "
                "profile and fails on the second file."
            )
        raise CsvError(message)
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
