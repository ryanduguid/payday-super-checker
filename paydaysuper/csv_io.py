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
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, cast

from .deadlines import ContribLine

CENTS = Decimal("0.01")

# Characters Excel and Sheets can evaluate at the start of a cell. Classifying
# selected suffixes as safe is not reliable: scientific notation, booleans,
# R1C1 references and workbook-defined names can all be alphanumeric. The
# spreadsheet-facing CSV is therefore always quoted after any leading space;
# the source payroll export remains the record of the unmodified identifier.
FORMULA_LEAD = ("=", "+", "-", "@")


def money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return str(value.quantize(CENTS, rounding=ROUND_HALF_UP))


def cents(value: Decimal | None) -> Decimal:
    return Decimal("0") if value is None else value.quantize(CENTS, rounding=ROUND_HALF_UP)


def remitted_credit(line: ContribLine, remitted_as_at: date | None) -> Decimal:
    """How much of ``sg_amount`` is evidenced as remitted on this as-at date.

    A remitted date with no remitted_amount is a full remittance, which is
    how files written before this column existed are still read. A
    remitted_amount credits only that figure, and only on or after its
    remitted date. A remitted amount without a date is ambiguous and both the
    CSV reader and direct assessment entry point refuse that shape.
    """
    owed = cents(line.sg_amount)
    if line.remitted_amount is not None:
        credited = cents(line.remitted_amount)
        if line.remitted is not None and remitted_as_at is not None:
            return min(credited, owed)
        return Decimal("0")
    if remitted_as_at is not None:
        return owed
    return Decimal("0")


def csv_safe(text: str) -> str:
    """Stop a spreadsheet treating a cell as a formula.

    Applied to every field written from input text, not to a single
    trusted-looking one. `report` writes employee ids; `importers.
    write_canonical` writes employee names as well, and puts its dates and
    amounts through the same guard rather than reasoning per field about
    which of them could ever start with `=`.

    The trigger is looked for after leading whitespace, not at position 0:
    a sheet ignores the space, so testing position 0 let " =cmd" through a
    guard that catches "=cmd". Every formula-leading value is quoted. A
    selective suffix rule leaves data-integrity gaps such as `+1E3`, `-R1C1`,
    `+TRUE` and workbook-defined names."""
    stripped = text.lstrip()
    if stripped[:1] in FORMULA_LEAD:
        return "'" + text
    return text

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
    "remitted_amount": False,
    "matched_amount": False,
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
    # Appended, never inserted: a nine-column file from before this field
    # still parses. The heading sits last so a positional reader keeps its
    # column numbers.
    "remitted_amount": "remitted_amount",
    # Appended after remitted_amount. An explicit value preserves the amount
    # matched to a payday even when the vendor supplied no remittance date.
    # Blank keeps legacy whole-liability receipt semantics.
    "matched_amount": "matched_amount",
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
# followed by a colon-separated ZONE-LESS time. This is the grammar Python
# 3.10, the declared floor, itself parses once the fraction is normalised.
# fromisoformat on 3.11+ additionally reads compact dates (20260709), week
# dates (2026-W28-4), bare year-months (2026-07, as its FIRST day), compact
# times (T000000), comma decimal seconds and hour-only offsets; the
# pre-fromisoformat parser accepted none of them and README documents none
# of them. The shape gate refuses them all on every version: a tool that
# refuses ambiguous dates must not read 2026-07 as 2026-07-01, and
# version-dependent acceptance is how the same file gets two different
# compliance verdicts.
ISO_SHAPE = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}(?::\d{2}(?::\d{2}(?:\.\d{1,6})?)?)?)?$"
)

# A date-time carrying an explicit zone marker: Z, or the [+-]HH:MM(:SS)
# offset the old gate read through. Its as-written calendar day belongs to
# that zone, not necessarily to the Australian day the law tests:
# 2026-07-21T20:00:00Z is already 22 July 2026 in AEST, so reading the
# written day moves a fund receipt one day early and can turn a LATE
# receipt into a false ON_TIME, the one direction this tool refuses to
# fail in. Refused loudly rather than converted: the tool does not know
# which Australian zone the operator means, and DST splits the country
# across two. A zone-less time is different (dropping it cannot move the
# day), so ISO_SHAPE above still reads it. Hour-only offsets (+10) never
# parsed here on any version and keep their ordinary refusal.
ISO_OFFSET_SHAPE = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"[T ]\d{2}(?::\d{2}(?::\d{2}(?:\.\d{1,6})?)?)?"
    r"(?:[Zz]|[+-]\d{2}:\d{2}(?::\d{2})?)$"
)


def parse_date_text(text: str) -> date | None:
    """Read a date in any format this tool accepts, or None.

    A zone-less time component is dropped. The law tests whole days, so a
    receipt stamped 14:30 is neither earlier nor later than one stamped
    midnight. A date-time carrying a Z or UTC-offset marker is refused with
    a CsvError instead: its as-written day belongs to that zone, and
    silently keeping it can move a receipt one day early against the
    Australian calendar (see ISO_OFFSET_SHAPE)."""
    text = text.strip()
    if not text:
        return None
    # datetime.fromisoformat accepts ISO dates and ISO date-times (including a
    # space or T separator). Normalise the fraction first, truncated then
    # zero-padded to microseconds, and shape-check the normalised text, so
    # the gate and the parser see the same string and every supported
    # interpreter accepts the same surface.
    iso_text = FRACTION_OVERFLOW.sub(r"\1", text)
    iso_text = FRACTION_PAD.sub(lambda m: m.group(1) + "." + m.group(2).ljust(6, "0"), iso_text)
    if ISO_OFFSET_SHAPE.match(iso_text):
        raise CsvError(
            f"value {text!r} carries a UTC or timezone offset marker, and its "
            "as-written calendar day belongs to that zone, not necessarily to "
            "the Australian day the law tests -- 2026-07-21T20:00:00Z is "
            "already 22 July 2026 in AEST, so keeping the written day would "
            "read a receipt one day early. Convert it to the Australian local "
            "calendar date and supply that instead"
        )
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
    try:
        parsed = parse_date_text(value)
    except CsvError as exc:
        # parse_date_text's offset refusal carries no row context; name the
        # cell the way every other message here does.
        raise CsvError(f"row {row}: {field} {exc}")
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
    # Quantised to the cent HERE, at the read boundary, exactly as
    # importers._amount does, and refusing the one case quantising would
    # destroy. The two readers exist to agree about what a figure means
    # (see AMOUNT_TEXT above), and they had drifted on precision: the
    # importer read 1,234.567 as 1234.57 while this reader kept 1234.567,
    # so a hand-edited canonical file -- which the README invites --
    # carried sub-cent residue the imported file could not. Every figure
    # the checker matches, writes and reports is a cent figure;
    # ROUND_HALF_UP through cents(), the same rounding money() applies on
    # the way out.
    rounded = cents(amount)
    if rounded == 0 and amount != 0:
        raise CsvError(
            f"row {row}: {field} value {value!r} is under half a cent, so reading it "
            "to the cent leaves the row carrying no money at all. Every figure this "
            "tool matches, writes and reports is a cent figure. Round it yourself, or "
            "take the row out."
        )
    return rounded


def _parse_bool(value: str, field: str, row: int) -> bool:
    text = value.strip().lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    raise CsvError(f"row {row}: cannot read {field} value {value!r} as yes/no")


MISSING = object()  # marks a field the row never supplied at all

# How many row problems an error message lists in full before summarising
# the rest as a count. Enough to fix a messy export in one pass without
# printing a report-sized error for a file that is wrong in every row.
MAX_PROBLEMS_SHOWN = 20


def malformed_row_problem(row: dict, i: int) -> str | None:
    """The problem with a row whose field count does not match the header,
    or None for a well-shaped row.

    A truncated row is refused because a missing cell is not the same as a
    blank one, and a row with surplus values is refused because a misaligned
    row (an unescaped comma inside a name, say) shifts every later column
    one place left, so an amount could be a different column's value read
    under the wrong name. `row` must come from a DictReader constructed with
    restval=MISSING: an empty string is a legitimate cell value and cannot
    also mean "this row never supplied a value for this column at all".
    Shared with importers._read_dicts so the checker and the importer cannot
    drift on what a malformed row is."""
    short = sorted(k for k, v in row.items() if v is MISSING and k)
    if short:
        return (
            f"row {i} stops early and supplies no value for {short}. A truncated "
            "row is not the same as a blank field, so it is not assumed empty."
        )
    surplus = [v for v in (row.get(None) or []) if v and v.strip()]
    if surplus:
        return (
            f"row {i} carries more values than the header has columns: "
            f"{surplus}. They would be dropped, so the row is refused instead."
        )
    return None


def raise_problems(problems: list[str], path: str | Path) -> None:
    """Raise the collected row problems as one CsvError, at most
    MAX_PROBLEMS_SHOWN of them in full, so a messy export can be fixed in
    one pass without the message scrolling off the terminal."""
    shown = problems[:MAX_PROBLEMS_SHOWN]
    more = (
        f" ... and {len(problems) - MAX_PROBLEMS_SHOWN} more problem(s)."
        if len(problems) > MAX_PROBLEMS_SHOWN
        else ""
    )
    raise CsvError(
        f"{len(problems)} problem(s) in {path}:\n  - " + "\n  - ".join(shown) + more
    )


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
        reader = csv.DictReader(f, restval=cast(Any, MISSING))
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
            malformed = malformed_row_problem(row, i)
            if malformed is not None:
                problems.append(malformed)
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
            remitted_amount_raw = optional("remitted_amount").strip()
            matched_amount_raw = optional("matched_amount").strip()

            try:
                sg_amount = _parse_amount(row[mapping["sg_amount"]], "sg_amount", i)
                remitted_amount = (
                    _parse_amount(remitted_amount_raw, "remitted_amount", i)
                    if remitted_amount_raw
                    else None
                )
                matched_amount = (
                    _parse_amount(matched_amount_raw, "matched_amount", i)
                    if matched_amount_raw
                    else None
                )
                if remitted_amount is not None and not remitted_raw:
                    raise CsvError(
                        f"row {i}: remitted_amount requires remitted_date so an "
                        "as-at report cannot credit the payment before it occurred"
                    )
                if remitted_amount is not None and remitted_amount > sg_amount:
                    raise CsvError(
                        f"row {i}: remitted_amount {money(remitted_amount)} is greater "
                        f"than sg_amount {money(sg_amount)}"
                    )
                if matched_amount is not None and matched_amount > sg_amount:
                    raise CsvError(
                        f"row {i}: matched_amount {money(matched_amount)} is greater "
                        f"than sg_amount {money(sg_amount)}"
                    )
                if (
                    matched_amount is not None
                    and remitted_amount is not None
                    and remitted_amount > matched_amount
                ):
                    raise CsvError(
                        f"row {i}: remitted_amount {money(remitted_amount)} is greater "
                        f"than matched_amount {money(matched_amount)}"
                    )
                if (
                    matched_amount is not None
                    and matched_amount < sg_amount
                    and remitted_raw
                    and remitted_amount is None
                ):
                    raise CsvError(
                        f"row {i}: matched_amount below sg_amount requires "
                        "remitted_amount when remitted_date is present; otherwise "
                        "the legacy blank-amount fallback would treat the whole "
                        "liability as remitted"
                    )
                line = ContribLine(
                    employee_id=employee,
                    qe_day=_parse_date(row[mapping["qe_day"]], "qe_day", i),
                    sg_amount=sg_amount,
                    remitted=(
                        _parse_date(remitted_raw, "remitted", i) if remitted_raw else None
                    ),
                    remitted_amount=remitted_amount,
                    matched_amount=matched_amount,
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
        raise_problems(problems, path)
    if not lines:
        raise CsvError(f"{path} has a header but no data rows")
    return lines
