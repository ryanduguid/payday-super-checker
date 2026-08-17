"""CSV reading with loud failures.

Payroll exports vary, so column names are mapped explicitly. Nothing is
guessed and nothing is coerced silently: a value the parser cannot read
raises with its row number rather than defaulting to zero or today.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .deadlines import ContribLine

CANONICAL = {
    "employee_id": True,
    "qe_day": True,
    "sg_amount": True,
    "remitted": False,
    "received": False,
    "first_to_fund": False,
    "out_of_cycle": False,
    "next_standard_qe_day": False,
    "db_interest": False,
}

DEFAULT_MAPPING = {
    "employee_id": "employee_id",
    "qe_day": "payment_date",
    "sg_amount": "sg_amount",
    "remitted": "remitted_date",
    "received": "fund_received_date",
    "first_to_fund": "first_contribution_to_fund",
    "out_of_cycle": "out_of_cycle",
    "next_standard_qe_day": "next_standard_payday",
    "db_interest": "defined_benefit",
}

TRUE_WORDS = {"y", "yes", "true", "1", "t"}
FALSE_WORDS = {"", "n", "no", "false", "0", "f"}

# What an amount may look like once "$" and surrounding space are gone. A
# comma or space is read as a separator only where a THOUSANDS separator
# belongs: stripping every comma regardless of position turns the European
# decimal 612,00 into 61200, a hundredfold overstatement of a shortfall in
# a file this tool invites you to hand-edit. `importers.py` reads this same
# constant, so one package cannot ship two amount parsers that disagree
# about what a figure means.
#
# Everything Decimal itself reads is allowed through wherever no comma or
# space is involved: a leading "+", a bare fraction (.50), a trailing point
# (612.), and exponent notation (1e2), all of which a spreadsheet or an ERP
# extract emits and all of which this reader accepted until the separator
# rule arrived and narrowed the pattern past its own purpose. The rule is
# about WHERE a separator sits, so it constrains nothing else; 612,00 and
# 1,23 and 12,34,567 stay refused.
AMOUNT_TEXT = re.compile(
    r"^[-+]?(?:\d{1,3}(?:[ ,]\d{3})+|\d+)(?:\.\d*)?(?:[eE][-+]?\d+)?$"
    r"|^[-+]?\.\d+(?:[eE][-+]?\d+)?$"
)


class CsvError(ValueError):
    pass


def load_mapping(
    path: str | Path | None, overrides: list[str] | None = None
) -> tuple[dict[str, str], set[str]]:
    """Returns the column mapping and the set of fields the user mapped
    explicitly. A field the user named must exist in the CSV: silently
    ignoring a typo there would change every verdict."""
    mapping = dict(DEFAULT_MAPPING)
    explicit: set[str] = set()
    if path is not None:
        with open(path, encoding="utf-8") as f:
            try:
                user = json.load(f)
            except json.JSONDecodeError as exc:
                raise CsvError(f"{path} is not valid JSON: {exc}")
        if not isinstance(user, dict):
            raise CsvError(f"{path} must be a JSON object of field: column pairs")
        # Keys starting with an underscore are comments, not mappings.
        user = {k: v for k, v in user.items() if not k.startswith("_")}
        unknown = set(user) - set(CANONICAL)
        if unknown:
            raise CsvError(
                f"mapping file has unknown fields: {sorted(unknown)}; "
                f"valid fields are {sorted(CANONICAL)}"
            )
        bad = sorted(
            k for k, v in user.items() if not isinstance(v, str) or not v.strip()
        )
        if bad:
            raise CsvError(
                f"{path} maps {bad} to something that is not a column name. Each value "
                "must be the column heading as it appears in your CSV."
            )
        mapping.update(user)
        explicit.update(user)
    for item in overrides or []:
        if "=" not in item:
            raise CsvError(f"--map expects field=column, got {item!r}")
        field, column = item.split("=", 1)
        if field not in CANONICAL:
            raise CsvError(f"--map field {field!r} is not one of {sorted(CANONICAL)}")
        mapping[field] = column
        explicit.add(field)
    return mapping, explicit


DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d/%m/%y",
    "%d %b %Y",  # 9 Jul 2026
    "%d %B %Y",  # 9 July 2026
)

# Payroll exports use either an ISO date, an Australian day-first date, or one
# of the spelled-month forms above. A time of day is harmless because the law
# tests whole days, but arbitrary text is not: accepting ``2026-07-09 typo``
# as a real payday can turn a source-data problem into a compliance verdict.
TIME_FORMATS = (
    "%H:%M",
    "%H:%M:%S",
    "%H:%M:%S.%f",
    "%I:%M %p",
    "%I:%M:%S %p",
)

# No payroll date is beyond this. Sentinels such as 9999-12-31 are routine in
# ERP extracts and would otherwise compound interest for millennia.
LATEST_SANE_YEAR = 2200

# .NET and SQL Server timestamps carry seven fractional-second digits
# (2026-07-09T00:00:00.0000000). fromisoformat on Python 3.11+ truncates a
# long fraction itself; 3.10, the declared floor, refuses it, so the same
# export parsed on one interpreter and was refused on another. Truncated to
# microseconds here, anchored to the seconds field so a digit run elsewhere
# in a malformed string cannot be rewritten into something parseable.
FRACTION_OVERFLOW = re.compile(r"(:\d{2}\.\d{6})\d+")

# Python 3.10 fromisoformat accepts only 3- or 6-digit fractions; 3.11+
# accepts any length. Zero-padding to microseconds makes every interpreter
# parse the same fraction surface. Anchored to the seconds field like
# FRACTION_OVERFLOW, and applied after it, so only 1-5 digit runs remain.
FRACTION_PAD = re.compile(r"(:\d{2})\.(\d{1,5})(?!\d)")

# The ISO surface this tool accepts: a hyphenated calendar date, alone or
# followed by a colon-separated time and an optional numeric offset — the
# grammar Python 3.10, the declared floor, itself parses once Z and the
# fraction are normalised. fromisoformat on 3.11+ additionally reads compact
# dates (20260709), week dates (2026-W28-4), bare year-months (2026-07, as
# its FIRST day), compact times (T000000), comma decimal seconds and
# hour-only offsets; the pre-fromisoformat parser accepted none of them and
# README documents none of them. The shape gate refuses them all on every
# version: a tool that refuses ambiguous dates must not read 2026-07 as
# 2026-07-01, and version-dependent acceptance is how the same file gets
# two different compliance verdicts.
ISO_SHAPE = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}(?::\d{2}(?::\d{2}(?:\.\d{1,6})?)?)?"
    r"(?:[+-]\d{2}:\d{2}(?::\d{2})?)?)?$"
)


def parse_date_text(text: str) -> date | None:
    """Read a date in any format this tool accepts, or None.

    A time component is dropped. The law tests whole days, so a receipt
    stamped 14:30 is neither earlier nor later than one stamped midnight."""
    text = text.strip()
    if not text:
        return None
    # datetime.fromisoformat accepts ISO dates and ISO date-times (including a
    # space or T separator). Normalise first — Z for Python versions before
    # 3.11, the fraction truncated then zero-padded to microseconds — and
    # shape-check the normalised text, so the gate and the parser see the
    # same string and every supported interpreter accepts the same surface.
    iso_text = text.removesuffix("Z") + "+00:00" if text.endswith("Z") else text
    iso_text = FRACTION_OVERFLOW.sub(r"\1", iso_text)
    iso_text = FRACTION_PAD.sub(lambda m: m.group(1) + "." + m.group(2).ljust(6, "0"), iso_text)
    if ISO_SHAPE.match(iso_text):
        try:
            return datetime.fromisoformat(iso_text).date()
        except ValueError:
            pass

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
        for time_fmt in TIME_FORMATS:
            try:
                return datetime.strptime(text, f"{fmt} {time_fmt}").date()
            except ValueError:
                pass
    return None


def _parse_date(value: str, field: str, row: int) -> date:
    parsed = parse_date_text(value)
    if parsed is None:
        raise CsvError(
            f"row {row}: cannot read {field} value {value!r}: use YYYY-MM-DD or "
            "DD/MM/YYYY (day first, Australian order)"
        )
    if parsed.year > LATEST_SANE_YEAR:
        raise CsvError(
            f"row {row}: {field} value {value!r} is not a real date. Leave placeholder "
            "dates such as 9999-12-31 blank instead"
        )
    return parsed


def _parse_amount(value: str, field: str, row: int) -> Decimal:
    # Stripped AGAIN after the "$" comes out. Excel's accounting format puts
    # the sign flush left and the figure flush right, so a copied cell reads
    # "$ 612.00" or "$  1,234.00", and the space the dollar sign left behind
    # is still in `text` when AMOUNT_TEXT is matched against it below. That
    # refused the file and blamed a comma for a space.
    text = value.strip().replace("$", "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1].strip()
    loose = text.replace(",", "").replace(" ", "")
    try:
        amount = Decimal(loose)
        finite = amount.is_finite()
    except (InvalidOperation, ValueError):
        raise CsvError(f"row {row}: cannot read {field} value {value!r} as an amount")
    if not finite:
        # Decimal accepts "nan" and "Infinity"; neither is an amount.
        raise CsvError(f"row {row}: cannot read {field} value {value!r} as an amount")
    if amount.adjusted() > 15:
        # Beyond this the value cannot be rounded to cents under the default
        # decimal context, and no super contribution is this large.
        raise CsvError(
            f"row {row}: {field} value {value!r} is too large to be a real amount"
        )
    if not AMOUNT_TEXT.match(text):
        # Checked after the magnitude guard so an out-of-range figure still
        # gets the message that names its real problem.
        raise CsvError(
            f"row {row}: cannot read {field} value {value!r} as an amount. A comma or "
            "space is only read as a thousands separator, so 612,00 is refused rather "
            "than read as 61200."
        )
    if amount < 0:
        raise CsvError(f"row {row}: {field} is negative ({value!r})")
    return amount


def _parse_bool(value: str, field: str, row: int) -> bool:
    text = value.strip().lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    raise CsvError(f"row {row}: cannot read {field} value {value!r} as yes/no")


MISSING = object()  # marks a field the row never supplied at all


def parse_rows(
    path: str | Path, mapping: dict[str, str], explicit: set[str] | None = None
) -> list[ContribLine]:
    explicit = explicit or set()
    try:
        return _parse_rows(path, mapping, explicit)
    except UnicodeDecodeError as exc:
        raise CsvError(
            f"{path} is not UTF-8 text (byte {exc.object[exc.start]:#04x} at position "
            f"{exc.start}). Excel's plain 'CSV' export uses the Windows code page: "
            "re-save it as 'CSV UTF-8 (Comma delimited)' and run again."
        )


def _parse_rows(
    path: str | Path, mapping: dict[str, str], explicit: set[str]
) -> list[ContribLine]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, restval=MISSING)
        if reader.fieldnames is None:
            raise CsvError(f"{path} has no header row")

        named = [h.strip() for h in reader.fieldnames if h and h.strip()]
        duplicates = sorted({h for h in named if named.count(h) > 1})
        if duplicates:
            raise CsvError(
                f"{path} has duplicate column name(s): {duplicates}. Only the last "
                "one would be read, so the figures cannot be trusted. Rename them."
            )
        headers = set(named)

        missing = [
            mapping[field]
            for field, required in CANONICAL.items()
            if required and mapping[field] not in headers
        ]
        if missing:
            raise CsvError(
                f"{path} is missing required column(s): {missing}. Columns found: "
                f"{sorted(headers)}. Map your own names with --map field=column. The "
                "amount column must hold super guarantee only, not salary sacrifice or "
                "additional contributions."
            )
        mismapped = sorted(
            f"{field} -> {mapping[field]}"
            for field in explicit
            if mapping[field] not in headers
        )
        if mismapped:
            raise CsvError(
                f"mapped column(s) not found in {path}: {mismapped}. Columns found: "
                f"{sorted(headers)}. Remove the mapping for any field your export "
                "does not have."
            )

        lines: list[ContribLine] = []
        # Cell-level problems are collected so a messy export can be fixed in
        # one pass. A structurally broken row is skipped, because its cells
        # cannot be read at all.
        problems: list[str] = []
        for i, raw in enumerate(reader, start=2):  # row 1 is the header
            row = {(k.strip() if k else k): v for k, v in raw.items()}
            short = sorted(k for k, v in row.items() if v is MISSING and k)
            if short:
                problems.append(
                    f"row {i} stops early and supplies no value for {short}. A truncated "
                    "row is not the same as a blank field, so it is not assumed empty."
                )
                continue
            surplus = [v for v in (row.get(None) or []) if v and v.strip()]
            if surplus:
                problems.append(
                    f"row {i} carries more values than the header has columns: "
                    f"{surplus}. They would be dropped, so the row is refused instead."
                )
                continue
            row = {k: (v or "") for k, v in row.items() if k is not None}

            def optional(field: str, row: dict = row) -> str:
                return row.get(mapping[field], "")

            employee = row[mapping["employee_id"]].strip()
            if not employee:
                problems.append(f"row {i}: employee_id is empty")
                continue

            remitted_raw = optional("remitted").strip()
            received_raw = optional("received").strip()
            next_raw = optional("next_standard_qe_day").strip()

            try:
                line = ContribLine(
                    employee_id=employee,
                    qe_day=_parse_date(row[mapping["qe_day"]], "qe_day", i),
                    sg_amount=_parse_amount(row[mapping["sg_amount"]], "sg_amount", i),
                    remitted=(
                        _parse_date(remitted_raw, "remitted", i) if remitted_raw else None
                    ),
                    received=(
                        _parse_date(received_raw, "received", i) if received_raw else None
                    ),
                    first_to_fund=_parse_bool(
                        optional("first_to_fund"), "first_to_fund", i
                    ),
                    out_of_cycle=_parse_bool(optional("out_of_cycle"), "out_of_cycle", i),
                    next_standard_qe_day=(
                        _parse_date(next_raw, "next_standard_qe_day", i) if next_raw else None
                    ),
                    db_interest=_parse_bool(optional("db_interest"), "db_interest", i),
                    row=i,
                )
            except CsvError as exc:
                problems.append(str(exc))
                continue
            lines.append(line)

    if problems:
        shown = problems[:20]
        more = (
            f" ... and {len(problems) - 20} more problem(s)."
            if len(problems) > 20
            else ""
        )
        raise CsvError(
            f"{len(problems)} problem(s) in {path}:\n  - " + "\n  - ".join(shown) + more
        )
    if not lines:
        raise CsvError(f"{path} has a header but no data rows")
    return lines
