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
