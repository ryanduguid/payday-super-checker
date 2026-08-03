"""Read a payroll export and a super payments export, join them, and write
the canonical contributions CSV.

No vendor export carries a fund receipt date. Xero gives the date a payment
was sent to the fund, MYOB gives a Paid Date, Employment Hero gives a Beam
status. The deadline in s 18C tests receipt, and clearing-house transit is
the employer's risk, so every vendor date lands in `remitted` and the receipt
column is left empty.

Duplicate headers: `profiles._index` normalises headings and silently keeps
the first of two that collide, because column *matching* only needs one
usable candidate. Reading a real file is different: two columns that both
normalise to "amount" mean the tool cannot tell which one is the real
figure, and every amount it reports becomes a guess. `csv_io.py` already
refuses a file outright over duplicate column names for the same reason.
This module carries that same refusal for the general case (headings equal
once case, punctuation and spacing are folded, not only when they are
byte-for-byte identical), checked once here rather than by changing
`_index`, because `_index`'s silent-first behaviour is still correct for
`detect`/`resolve_columns` scoring a header row that was never going to be
read as data.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .csv_io import MISSING, CsvError, parse_date_text
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


def _check_duplicate_headers(headers: list[str], path: str | Path) -> None:
    """Refuse a file where two headings normalise to the same field.

    `resolve_columns` (via `profiles._index`) would silently read whichever
    one of them happened to come first, and there is no way for the rest of
    this module to tell that happened. See the module docstring."""
    groups: dict[str, list[str]] = {}
    for h in headers:
        key = normalise_header(h)
        if key:
            groups.setdefault(key, []).append(h)
    duplicates = {k: v for k, v in groups.items() if len(v) > 1}
    if duplicates:
        detail = "; ".join(
            f"{sorted(headings)} all read as {key!r}"
            for key, headings in sorted(duplicates.items())
        )
        raise CsvError(
            f"{path} has two or more columns that normalise to the same heading: "
            f"{detail}. Only one of them would be read and there is no reliable way "
            "to tell which, so no figure from this file can be trusted. Rename the "
            "columns so each heading is unique."
        )


def _read_dicts(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, restval=MISSING)
            if reader.fieldnames is None:
                raise CsvError(f"{path} has no header row")
            headers = [h for h in reader.fieldnames if h and h.strip()]
            raw_rows = list(reader)
    except UnicodeDecodeError as exc:
        raise CsvError(
            f"{path} is not UTF-8 text (byte {exc.object[exc.start]:#04x} at position "
            f"{exc.start}). Excel's plain 'CSV' export uses the Windows code page: "
            "re-save it as 'CSV UTF-8 (Comma delimited)' and run again."
        )
    _check_duplicate_headers(headers, path)

    # A row with the wrong number of fields is never read as data: a
    # misaligned row (an unescaped comma inside a name, say) shifts every
    # later column one place left, so an amount this tool reports could
    # actually be a different column's value read under the wrong name.
    # csv_io.py's _parse_rows refuses exactly this; mirrored here with the
    # same restval sentinel technique, because an empty string is a
    # legitimate cell value and cannot also mean "this row never supplied a
    # value for this column at all".
    problems: list[str] = []
    rows: list[dict[str, str]] = []
    for i, raw in enumerate(raw_rows, start=2):  # row 1 is the header
        short = sorted(k for k, v in raw.items() if v is MISSING and k)
        if short:
            problems.append(
                f"row {i} stops early and supplies no value for {short}. A truncated "
                "row is not the same as a blank field, so it is not assumed empty."
            )
            continue
        surplus = [v for v in (raw.get(None) or []) if v and v.strip()]
        if surplus:
            problems.append(
                f"row {i} carries more values than the header has columns: "
                f"{surplus}. They would be dropped, so the row is refused instead."
            )
            continue
        rows.append({k: (v or "") for k, v in raw.items() if k is not None})

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


def _check_reversed_periods(super_rows: list[SuperRow]) -> None:
    """A super period where the start is after the end cannot be matched to
    any payday without guessing: `_covers` would compare `start <= target <=
    end` with `start > end`, which is false for every target, so the row
    would silently become an orphan and the payroll row it actually settled
    would read "no super payment found" -- a real payment made invisible
    rather than a genuine gap. Refuse outright instead."""
    for s in super_rows:
        if (
            s.period_start is not None
            and s.period_end is not None
            and s.period_start > s.period_end
        ):
            raise CsvError(
                f"row {s.row}: pay period start {s.period_start.isoformat()} is after "
                f"period end {s.period_end.isoformat()}. That is not a valid pay period, "
                "so this payment cannot be matched to a payday without guessing which "
                "one was meant."
            )


def join(payroll_rows: list[PayrollRow], super_rows: list[SuperRow]) -> JoinResult:
    _check_reversed_periods(super_rows)

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
