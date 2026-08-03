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
AMOUNT_TEXT = re.compile(r"^-?\d{1,3}(?:[ ,]\d{3})*(?:\.\d+)?$|^-?\d+(?:\.\d+)?$")


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
            user = json.load(f)
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

# No payroll date is beyond this. Sentinels such as 9999-12-31 are routine in
# ERP extracts and would otherwise compound interest for millennia.
LATEST_SANE_YEAR = 2200


def parse_date_text(text: str) -> date | None:
    """Read a date in any format this tool accepts, or None.

    A time component is dropped. The law tests whole days, so a receipt
    stamped 14:30 is neither earlier nor later than one stamped midnight."""
    text = text.strip()
    if not text:
        return None
    candidates = [text, text.split("T")[0].strip(), text.split(" ")[0].strip()]
    for candidate in candidates:
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    # "9 Jul 2026 00:00:00" needs the first three words, not the first one.
    words = text.split()
    if len(words) >= 3:
        head = " ".join(words[:3])
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(head, fmt).date()
            except ValueError:
                continue
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
    text = value.strip().replace("$", "")
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

            def optional(field: str) -> str:
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
