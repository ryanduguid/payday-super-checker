"""Read a payroll export and a super payments export, join them, and write
the canonical contributions CSV.

No vendor export carries a fund receipt date. Xero gives the date a payment
was sent to the fund, MYOB gives a Paid Date, Employment Hero gives a Beam
status. The deadline in s 18C tests receipt, and clearing-house transit is
the employer's risk, so every vendor date lands in `remitted` and the receipt
column is left empty. Where a profile classifies a status column
(`Profile.remitted_status`), a vendor date only lands in `remitted` when the
row's status shows the payment actually left the employer: a Beam batch
still at Created, Submission accepted or Awaiting payment carries a Payment
Date for money that was never sent, and writing that date as a remittance
would read a wholly unfunded payday as remitted by the deadline.

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
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .atomic_io import atomic_text_output
from .csv_io import (
    AMOUNT_TEXT,
    LATEST_SANE_YEAR,
    MISSING,
    CsvError,
    cents,
    csv_safe,
    malformed_row_problem,
    money,
    parse_date_text,
    raise_problems,
)
from .deadlines import REGIME_START
from .profiles import (
    Profile,
    detect,
    normalise_header,
    normalise_name,
    resolve_columns,
)

# A separator is allowed only where a thousands separator belongs. Stripping
# every comma turns the European decimal 612,00 into 61200. The pattern
# lives in csv_io so this module and the checker's own reader cannot drift
# apart on what an amount is; see csv_io.AMOUNT_TEXT.
_AMOUNT = AMOUNT_TEXT


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
    # The vendor status that showed this payment never left the employer
    # (whitespace-collapsed, as written otherwise), set only where a
    # profile's `remitted_status` classified the row as not sent. Such a
    # row always carries `paid_date=None`, whatever its date cell said:
    # the date belongs to a payment that was not made. None everywhere
    # else, including for rows whose status shows the payment WAS sent.
    unpaid_status: str | None = None


def _check_duplicate_headers(headers: list[str], path: str | Path) -> None:
    """Refuse a file where two headings normalise to the same field.

    `resolve_columns` (via `profiles._index`) would silently read whichever
    one of them happened to come first, and there is no way for the rest of
    this module to tell that happened. See the module docstring."""
    groups: dict[str, list[str]] = {}
    for h in headers:
        # A heading that folds away to nothing -- "###", say -- is still a
        # heading, and csv_io refuses two byte-identical ones. Skipping the
        # falsy key here made this module's refusal narrower than csv_io's
        # for exactly those files, contradicting the module docstring's
        # claim that it is a superset. Such a heading falls back to its own
        # collapsed text, so two identical ones still collide and two
        # different ones still do not.
        key = normalise_header(h) or " ".join(h.split()).casefold()
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
    # csv_io.py's _parse_rows refuses exactly this, and the refusal is now
    # written once as csv_io.malformed_row_problem (fed by the same restval
    # sentinel above), so the checker and the importer cannot drift on what
    # a malformed row is.
    problems: list[str] = []
    rows: list[dict[str, str]] = []
    for i, raw in enumerate(raw_rows, start=2):  # row 1 is the header
        malformed = malformed_row_problem(raw, i)
        if malformed is not None:
            problems.append(malformed)
            continue
        rows.append({k: (v or "") for k, v in raw.items() if k is not None})

    if problems:
        raise_problems(problems, path)
    if not rows:
        raise CsvError(f"{path} has a header but no data rows")
    return headers, rows


def _date(value: str, field: str, row: int, formats: tuple[str, ...]) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    parsed: date | None = None
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        # The profile's own formats first, then every format the checker
        # accepts. A vendor that writes one column ISO and another
        # day-first still reads, instead of failing on a date a human can
        # see is a date.
        try:
            parsed = parse_date_text(text)
        except CsvError as exc:
            # The offset refusal carries no row context of its own; name
            # the cell the way every other message here does.
            raise CsvError(f"row {row}: {field} {exc}")
    if parsed is None:
        raise CsvError(f"row {row}: cannot read {field} value {value!r} as a date")
    if parsed.year > LATEST_SANE_YEAR:
        # The same ceiling csv_io._parse_date applies, for the same reason
        # _amount's magnitude guard mirrors csv_io's: a value this module
        # accepts and the checker would refuse must be refused HERE, at the
        # point closest to the bad input. Without it, an ERP sentinel of
        # 31/12/9999 imported with exit 0 and "matched 2", and the very
        # next command refused the file this one had just written.
        raise CsvError(
            f"row {row}: {field} value {value!r} is not a real date. Leave placeholder "
            "dates such as 9999-12-31 blank instead"
        )
    return parsed


def _amount(value: str, field: str, row: int) -> Decimal:
    """Read one amount cell, to the cent.

    Every figure that leaves this module is a cent figure: `write_canonical`
    writes `money(...)`, the checker reads the file back at that precision,
    and the report it produces is in dollars and cents. Quantising HERE, at
    the read boundary, is what makes `PayrollRow.sg_amount` and
    `SuperRow.amount` cent-clean by construction, so no arithmetic
    downstream can leave a sub-cent residue for the allocator to spend.

    A payroll row of 540.004 settled by a super payment of 540.00 used to
    leave `_unmet` holding 0.004. The next super row whose period reached
    that payday spent the 0.004 on it, and its own later payment date then
    became the payday's remittance date: a payday whose every payable cent
    arrived five days inside the deadline reported LATE with the full
    540.00 as a shortfall and an SG-charge estimate on top, or, where that
    second payment carried no date, UNPAID for the same 540.00. Comparing
    to the cent at the point of the verdict fixed the verdict and left the
    residue in place to move a date; there is no residue to move now.

    ROUND_HALF_UP through `report.cents`, the same rounding `money()`
    applies on the way out, so the figure this reads and the figure it
    writes are the same number rather than two roundings of one input.

    Rounding is per row, and a row is the unit of obligation: one payroll
    row is one payday's liability for one employee, one super row is one
    payment. Nothing here is ever summed across rows to reach a verdict, so
    quantising each row on its own is the same granularity the law and the
    report already work at. What it costs is under half a cent per row, and
    the alternative is the defect above.

    A value that is not zero in the file but rounds to zero is refused
    rather than rounded, because that is the one case where quantising
    would destroy the row instead of trimming it: a payment worth 0.004
    would become a 0.00 payment that still carries a date and still matches
    a payday, and a 0.004 liability would become a payday owing nothing. An
    exact 0 in the file is untouched -- a payday that genuinely owes no
    super guarantee is ordinary, and already has its own outcome."""
    text = (value or "").strip().replace("$", "").strip()
    if text.startswith("(") and text.endswith(")"):
        # Stripped inside the parens too, mirroring _parse_amount: Excel's
        # accounting format writes a negative as "($ 612.00)", and without
        # this strip the space the "$" left behind broke the pattern match,
        # so the refusal blamed a comma for a space instead of naming the
        # negative the way the checker's reader does.
        text = "-" + text[1:-1].strip()
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
    if amount.adjusted() > 15:
        # Mirrors csv_io._parse_amount's own guard: beyond this the value
        # cannot be rounded to cents under the default decimal context (28
        # significant digits), and no super contribution is this large.
        # Without this check here, `write_canonical`'s `money()` call is
        # the first place such a value would be quantized, raising a raw
        # decimal.InvalidOperation that is not a CsvError and so escapes
        # the CLI's `except (CsvError, ..., ValueError)` -- a value this
        # module accepted and the checker itself would refuse must be
        # refused here, at the point closest to the bad input, not left to
        # fail unpredictably downstream.
        raise CsvError(f"row {row}: {field} value {value!r} is too large to be a real amount")
    if amount < 0:
        raise CsvError(f"row {row}: {field} is negative ({value!r})")
    rounded = cents(amount)
    if rounded == 0 and amount != 0:
        raise CsvError(
            f"row {row}: {field} value {value!r} is under half a cent, so reading it "
            "to the cent leaves the row carrying no money at all. Every figure this "
            "tool matches, writes and reports is a cent figure. Round it yourself, or "
            "take the row out."
        )
    return rounded


def _cell(row: dict[str, str], resolved: dict[str, str], field: str) -> str:
    heading = resolved.get(field)
    if heading is None:
        return ""
    return (row.get(heading) or "").strip()


def read_super(
    path: str | Path, vendor: str | None = None
) -> tuple[list[SuperRow], Profile, dict[str, str]]:
    """Read a super payments export.

    Returns the rows, the profile that matched, and the canonical-field-to-
    heading mapping `resolve_columns` found for THIS file's headers. The
    third element exists so a caller such as `import_files` can tell "this
    file's period_start/period_end columns are structurally absent" from
    "this row's period cell happened to be blank" -- `join`'s
    `super_has_period_start`/`super_has_period_end` need exactly that
    file-level fact, and it is gone once the rows below are built."""
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
    status_rule = profile.remitted_status
    if status_rule is not None and status_rule.column not in resolved:
        raise CsvError(
            f"{path} has no payment status column, so a batch whose money never "
            "left the employer cannot be told apart from one that was paid, and "
            "every payment date in the file would be read as a remittance. "
            "Re-run the report with that column included, or map the file by hand."
        )
    wanted = {normalise_header(v) for v in (profile.sg_filter.include if profile.sg_filter else ())}
    sent_statuses = {normalise_header(v) for v in (status_rule.sent if status_rule else ())}
    not_sent_statuses = {normalise_header(v) for v in (status_rule.not_sent if status_rule else ())}
    rows: list[SuperRow] = []
    for i, raw in enumerate(raw_rows, start=2):
        if profile.sg_filter is not None:
            kind = normalise_header(_cell(raw, resolved, profile.sg_filter.column))
            if kind not in wanted:
                continue
        paid_date = _date(_cell(raw, resolved, "paid_date"), "paid date", i, profile.date_formats)
        unpaid_status = None
        if status_rule is not None:
            status_text = _cell(raw, resolved, status_rule.column)
            status_key = normalise_header(status_text)
            if status_key in not_sent_statuses:
                # The date cell belongs to a payment the status says was
                # never made. Written through as a remittance, it would read
                # a wholly unfunded payday as remitted by the deadline --
                # the same rule `join` applies to an undated row: no
                # evidence the money went is a blank date, not a date.
                unpaid_status = " ".join(status_text.split())
                paid_date = None
            elif status_key not in sent_statuses:
                raise CsvError(
                    f"row {i}: status {status_text!r} is not one this tool knows "
                    f"for profile {profile.key} (payment left the employer: "
                    f"{list(status_rule.sent)}; money not yet sent: "
                    f"{list(status_rule.not_sent)}), so there is no way to tell "
                    "whether this payment was made. Correct the status column, "
                    "or map the file by hand."
                )
        rows.append(
            SuperRow(
                employee_id=_cell(raw, resolved, "employee_id") or None,
                employee_name=_cell(raw, resolved, "employee_name") or None,
                period_start=_date(_cell(raw, resolved, "period_start"), "period start", i, profile.date_formats),
                period_end=_date(_cell(raw, resolved, "period_end"), "period end", i, profile.date_formats),
                paid_date=paid_date,
                amount=_amount(_cell(raw, resolved, "amount"), "amount", i),
                row=i,
                unpaid_status=unpaid_status,
            )
        )
    if not rows:
        raise CsvError(
            f"{path} has rows but none of them is super guarantee. Check the "
            f"contribution types against {list(profile.sg_filter.include)}"
            if profile.sg_filter
            else f"{path} has no usable rows"
        )
    return rows, profile, resolved


def read_payroll(
    path: str | Path, vendor: str | None = None
) -> tuple[list[PayrollRow], Profile, dict[str, str]]:
    """Read a payroll export. Returns the rows, the matched profile, and the
    canonical-field-to-heading mapping `resolve_columns` found for this
    file's headers -- see `read_super`'s docstring for why the third
    element exists."""
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
    return rows, profile, resolved


@dataclass
class MatchOutcome:
    payroll: PayrollRow
    remitted: date | None
    flag: str
    last_known_paid_date: date | None


# Why a super payment ended up unused. An orphan is surfaced either way,
# but "no payday matched" and "every payday it reached was already paid"
# are opposite findings: the first is a payment the tool could not place at
# all, the second is a genuine overpayment that no payroll row's `over:`
# flag can show, because nothing was allocated to any row for it to be over
# against. Reporting both as "matched no payday" reads to an accountant as
# unmatchable data when the second is a real excess contribution.
ORPHAN_NO_PAYDAY = "no payday matched"
ORPHAN_PAYDAYS_SETTLED = "paydays already settled"
ORPHAN_NOTHING_OWED = "paydays owe nothing"
ORPHAN_NO_AMOUNT = "payment has nothing to allocate"


@dataclass
class OrphanReason:
    """Why one orphaned super row went unused.

    `code` is one of the four `ORPHAN_*` constants, for a caller that needs
    to branch or count. `message` is the user-facing phrase, written to
    follow "super row N" so a report can render it directly."""

    super_row: SuperRow
    code: str
    message: str


@dataclass
class JoinResult:
    outcomes: list[MatchOutcome]
    orphans: list[SuperRow]
    key_mode: str
    warnings: list[str]
    # Same super rows as `orphans`, same order, one entry each, plus why.
    # A separate list rather than a dict keyed by `.row` (row numbers are
    # only unique within one file) or by `id()` (a footgun the moment it
    # outlives the objects).
    orphan_reasons: list[OrphanReason]


def _key(row, mode: str) -> str:
    """The identity the two files are matched on.

    An id is compared EXACTLY, with nothing folded. Ids are opaque codes,
    not prose: `E-001` and `E001` are two different employees at plenty of
    employers, and folding punctuation out of them merges the two into one
    record. That merge understates -- the first employee's payment settles
    the second employee's payday, and the workpaper reports someone who
    received nothing as owing nothing -- which is the one direction the
    rest of this design refuses to fail in.

    The documented name fallback folds case and whitespace and nothing
    else (`profiles.normalise_name`), so `O'Brien` and `OBrien` stay two
    people and a name written in any script keeps a non-empty key. The old
    code sent both id and name through `profiles.normalise_header`, whose
    own docstring says it folds HEADINGS: it strips `[^0-9a-z ]+`, so a
    name with no ASCII alphanumerics in it came back empty and `join`
    below refused the whole import over a populated employee column."""
    if mode == "id":
        return row.employee_id or ""
    return normalise_name(row.employee_name or "")


def _covers(s: SuperRow, target: date) -> bool:
    """Whether a super row's period includes a target date, inclusive of
    both ends.

    An exclusive start was tried to stop one period's end being repeated as
    the next period's start from re-claiming the earlier payday. It broke the
    opposite, equally normal convention -- a period that starts ON the
    payday it covers, or a payday that lands on a period's own start date --
    turning a clean match into a false orphan. Inclusive coverage preserves
    the export facts; contribution ordering and oldest-shortfall allocation
    in `join`, behind import_files' explicit reconciliation gate, decide what
    receives the money.

    The sole real call site (`_coverage`) never reaches this with both
    period fields `None` -- a period-less row's ambiguity is resolved
    against a payroll row set, not a single target date -- but a future
    direct caller could, so this defends itself instead of letting
    `None <= target` raise `TypeError`. `False` is the defensible answer:
    without any period at all, claiming this row covers one specific date
    would be a guess."""
    if s.period_start is None and s.period_end is None:
        return False
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


def _coverage(s: SuperRow, candidates: list[PayrollRow]) -> list[PayrollRow]:
    """Which of one employee's payroll rows a super row could have settled.

    A super row with no period at all rules nothing out: it is exactly as
    ambiguous against two candidates as a dated row whose range brackets
    both, so it is treated the same way (all of them), rather than being
    silently handed to whichever candidate happens to be alone."""
    if s.period_start is None and s.period_end is None:
        return list(candidates)
    return [r for r in candidates if _covers(s, r.effective_period_end)]


def _check_defensible(s: SuperRow, competing: list[PayrollRow]) -> None:
    """Refuse only where apportionment cannot produce a defensible answer:
    two or more of the payroll rows still competing for this super row's
    money are indistinguishable in every field that affects the outcome --
    same payday, same effective period end, same sg_amount. Anything else
    (different payday, different period, different amount, or a row that
    is no longer competing at all because something else already met its
    balance) sorts and apportions instead; see `_allocate`.

    `competing` -- not the super row's raw structural coverage -- because a
    row whose balance is already fully met by an earlier allocation is not
    actually contested by this payment even if the super row's period
    still technically spans its payday. Refusing over a row that needs
    nothing from this payment would be a false alarm, not a defensible
    caution."""
    groups: dict[tuple[date, date, Decimal], list[PayrollRow]] = {}
    for r in competing:
        groups.setdefault((r.payday, r.effective_period_end, r.sg_amount), []).append(r)
    for rows in groups.values():
        if len(rows) <= 1:
            continue
        numbers = ", ".join(str(r.row) for r in sorted(rows, key=lambda r: r.row))
        if s.period_start is None and s.period_end is None:
            # The super file, not the payroll file, is why this is
            # ambiguous: with no period recorded, this row is treated as
            # covering every payday for the employee, so it is the super
            # file's missing column(s) that need naming as the cause, not
            # the payroll rows that just happen to collide.
            raise CsvError(
                f"super row {s.row} has no pay period on record, so it is treated as "
                f"covering every payday for this employee, and rows {numbers} are "
                "identical in payday, pay period and amount as well, so there is no "
                "defensible way to decide which of them the payment settled. The "
                "super file is missing its pay period column(s) -- add them so the "
                "payment can be matched to a specific payday, or give the payroll "
                "rows distinct pay periods or amounts."
            )
        raise CsvError(
            f"super row {s.row} covers rows {numbers}, which are identical in payday, "
            "pay period and amount, so there is no defensible way to decide which of "
            "them the payment settled. Give them distinct pay periods or amounts, or "
            "merge the duplicate."
        )


def _unmet(row: PayrollRow, allocated_total: dict[int, Decimal]) -> Decimal:
    """How much of a payroll row's sg_amount has not yet been covered by
    anything allocated to it so far, from any super row, in either pass.
    Never negative: a row that has already received its full sg_amount (or
    more, from an overpayment) has nothing left to be short of.

    Never sub-cent either, for any input. `sg_amount` and every super row's
    `amount` are quantised to cents by `_amount` as they are read, and
    every step between there and here is exact Decimal arithmetic on cent
    figures: a share is `min` of two of them, `remaining` is one of them
    less the shares taken off it, and the leftover added to the newest
    allocation is what is left of one. Subtraction and `min` over cent
    figures cannot produce a third decimal place, so this balance is always
    a whole number of cents, and there is no fractional remainder for a
    later super row to spend on a payday that is already settled."""
    return max(Decimal("0"), row.sg_amount - allocated_total.get(id(row), Decimal("0")))


def _allocate(
    s: SuperRow, covered: list[PayrollRow], allocated_total: dict[int, Decimal]
) -> list[tuple[PayrollRow, Decimal]]:
    """Spread a super row's amount across the payroll rows it covers, each
    taking at most its own UNMET balance -- what is left of its sg_amount
    after everything already allocated to it, from any super row, in either
    pass -- not its full sg_amount regardless of what it has already
    received. A row already settled by something else takes nothing here,
    however wide this payment's own period reaches.

    Order: oldest QE day with an unmet balance first. LCR 2026/2 paragraphs
    31-33 say an eligible contribution is applied by law to the earliest QE
    day with a base or final shortfall, in fund-receipt order. A vendor pay-
    period end is not a statutory allocation instruction and cannot move a
    contribution past an earlier shortfall.

    Both sort keys are total orders over distinct payroll rows -- row
    numbers are unique within one file, so the sort never has to fall back
    on how `payroll_rows` happened to be ordered when it was passed to
    `join`. The same input, in any order, apportions the same way.

    Any amount left over once every covered row's balance is satisfied lands
    on the chronologically last row that received an allocation, where the
    importer can surface it as an unattributable excess."""
    ordered = sorted(
        covered,
        key=lambda r: (
            r.payday,
            r.effective_period_end,
            r.row,
        ),
    )
    remaining = s.amount
    allocations: list[tuple[PayrollRow, Decimal]] = []
    for row in ordered:
        if remaining <= 0:
            break
        share = min(remaining, _unmet(row, allocated_total))
        if share > 0:
            allocations.append((row, share))
        remaining -= share
    if remaining > 0 and allocations:
        newest = max(
            range(len(allocations)),
            key=lambda i: (
                allocations[i][0].payday,
                allocations[i][0].effective_period_end,
                allocations[i][0].row,
            ),
        )
        last_row, last_share = allocations[newest]
        allocations[newest] = (last_row, last_share + remaining)
    return allocations


def _super_order(s: SuperRow) -> tuple:
    """A total order over super rows, so nothing the caller decided -- the
    order it happened to build its list in -- can reach the result.

    Row number leads, because that is the order a reader expects and the
    order the file was read in. Every other field follows as a tiebreak:
    row numbers are only unique within one file, and two rows identical in
    every field are interchangeable anyway. `date.min` stands in for a
    missing date purely to keep the tuple comparable; it is never treated
    as a real date."""
    return (
        s.row,
        s.employee_id or "",
        s.employee_name or "",
        s.period_start or date.min,
        s.period_end or date.min,
        s.paid_date or date.min,
        s.amount,
    )


def _why_orphaned(
    covered: list[PayrollRow], allocated_total: dict[int, Decimal]
) -> tuple[str, str]:
    """Classify an unused super payment, so a report can tell an accountant
    which of two opposite things happened.

    A payment whose period reaches no payday at all is data the tool could
    not place. A payment whose paydays were every one of them already
    settled by other payments is money the employer sent on top of what was
    owed -- a genuine overpayment that shows up nowhere else in the result,
    since no payroll row received any of it to carry an `over:` flag."""
    if not covered:
        return ORPHAN_NO_PAYDAY, "matched no payday"
    if all(r.sg_amount == 0 for r in covered):
        return (
            ORPHAN_NOTHING_OWED,
            "matched only paydays that owe no super guarantee",
        )
    if all(_unmet(r, allocated_total) == 0 for r in covered):
        return (
            ORPHAN_PAYDAYS_SETTLED,
            "matched only paydays that were already settled by other payments, so "
            "this payment is on top of what was owed",
        )
    # Only reachable for a payment carrying nothing to spread: a zero or
    # negative amount leaves `_allocate` with no share to hand out even
    # though the paydays it covers still have balances owing. Saying
    # "already settled" here would be a false claim about paydays that are
    # not settled at all.
    return ORPHAN_NO_AMOUNT, "matched paydays but carries no amount to allocate"


def join(
    payroll_rows: list[PayrollRow],
    super_rows: list[SuperRow],
    *,
    payroll_has_period_end: bool = True,
    super_has_period_start: bool = True,
    super_has_period_end: bool = True,
) -> JoinResult:
    """Match payroll rows to the super payments that settled them.

    Contributions are processed in a fixed date/row order and allocated to
    the oldest covered QE day with an unmet balance. This mirrors the legal
    sequence in LCR 2026/2, subject to the importer's explicit reconciliation
    gate: vendor exports contain employer payment dates and period labels,
    not the fund-receipt order or assessment facts that establish the
    canonical statutory allocation.

    A super row that contributed to nobody is an orphan. `orphan_reasons`
    says why, one entry per orphan in the same order: a payment that
    reached no payday is data the tool could not place, while a payment
    whose paydays were all settled by something else is a real
    overpayment, and no payroll row can carry an `over:` flag for it
    because none of it was allocated anywhere.

    `payroll_has_period_end`, `super_has_period_start` and
    `super_has_period_end` describe whether the *file*, not any one row,
    resolved that column at all (what `resolve_columns` found against the
    file's headers, not whether a particular cell happened to be blank).
    They exist only to decide whether a loud warning belongs in the result:
    a payroll file with no pay period end column, or a super file missing
    one or both of its two period columns, still joins -- the fallback
    (payday instead of period end; a single-day window instead of a range;
    "covers every payday for the employee" when both are missing) already
    happens on its own from `None` fields on the rows themselves -- but the
    caller has no way to tell "this file structurally lacks that column"
    from "this row's cell was blank" once the file has been read into
    `PayrollRow`/`SuperRow` objects, and the messages differ. All three
    default to True (column present) so existing callers that never pass
    them see no new warnings."""
    _check_reversed_periods(super_rows)

    warnings: list[str] = []
    both_have_ids = (
        bool(payroll_rows)
        and bool(super_rows)
        and all(r.employee_id for r in payroll_rows)
        and all(r.employee_id for r in super_rows)
    )
    key_mode = "id" if both_have_ids else "name"
    if key_mode == "name":
        warnings.append(
            "matched on employee name because one of the files has no id column. "
            "Two employees sharing a name would be merged."
        )
    if not payroll_has_period_end:
        warnings.append(
            "the payroll file has no pay period end column, so matching falls back "
            "to the payday. A super payment recorded against the pay period rather "
            "than the payday it was paid on could be missed."
        )
    if not (super_has_period_start and super_has_period_end):
        if super_has_period_start or super_has_period_end:
            warnings.append(
                "the super file has only one of the pay period start/end columns, so "
                "a payment's coverage collapses to a single day and could miss the "
                "payday it actually settled."
            )
        else:
            warnings.append(
                "the super file has no pay period columns at all, so a payment "
                "cannot be matched to a specific payday by its period and is treated "
                "as covering every payday for that employee, which can trigger the "
                "same-payment ambiguity check for an employee with more than one "
                "payday."
            )

    grouped: dict[str, list[PayrollRow]] = {}
    for row in payroll_rows:
        key = _key(row, key_mode)
        if not key:
            raise CsvError(f"row {row.row}: the employee column is empty")
        grouped.setdefault(key, []).append(row)

    # What each super row could have settled, computed once and reused
    # below so the ambiguity check and the allocation step can never
    # disagree about what "covers" means.
    coverage: dict[int, list[PayrollRow]] = {}
    for s in super_rows:
        candidates = grouped.get(_key(s, key_mode), [])
        coverage[id(s)] = _coverage(s, candidates)

    # contributions[id(payroll_row)] collects every (super_row, amount,
    # note) a payroll row receives. allocated_total[id(payroll_row)] is the
    # running sum backing `_unmet`, updated after each contribution so the
    # next one sees the true balance left by every earlier fund-order entry.
    contributions: dict[int, list[tuple[SuperRow, Decimal, str]]] = {}
    allocated_total: dict[int, Decimal] = {}
    used_super_ids: set[int] = set()

    def _credit(row: PayrollRow, s: SuperRow, share: Decimal, note: str) -> None:
        contributions.setdefault(id(row), []).append((s, share, note))
        allocated_total[id(row)] = allocated_total.get(id(row), Decimal("0")) + share

    for s in sorted(super_rows, key=lambda s: (s.paid_date or date.max, *_super_order(s))):
        covered = coverage[id(s)]
        competing = [r for r in covered if _unmet(r, allocated_total) > 0]
        _check_defensible(s, competing)
        allocations = _allocate(s, covered, allocated_total)
        # A super row reads as shared only if more than one payroll row still
        # had an unmet balance when it was processed.
        shared = len(competing) > 1
        paid_str = s.paid_date.isoformat() if s.paid_date is not None else "no date on record"
        # Whether a note is attached is decided by `competing` -- only a
        # payment more than one payday was actually still contesting reads
        # as shared. The COUNT in the note is the payment's structural
        # coverage (`_coverage`: the paydays its period reaches, or every
        # payday for the employee when it has no period at all), because
        # that is what the sentence claims. Counting `competing` there made
        # it false: a payment structurally covering three paydays, one of
        # them already settled elsewhere, said it covered two.
        for row, share in allocations:
            note = (
                f"{share} of {s.amount} allocated from super row {s.row} (paid "
                f"{paid_str}), one of {len(covered)} paydays that payment covered"
                if shared
                else ""
            )
            _credit(row, s, share, note)
        if allocations:
            used_super_ids.add(id(s))

    outcomes: list[MatchOutcome] = []
    for row in payroll_rows:
        if row.sg_amount == 0:
            outcomes.append(
                MatchOutcome(row, None, "no super guarantee owed for this payday", None)
            )
            continue

        entries = contributions.get(id(row), [])
        if not entries:
            outcomes.append(MatchOutcome(row, None, "no super payment found", None))
            continue

        total = sum((amount for _, amount, _ in entries), Decimal("0"))
        flag_parts: list[str] = []
        # `_classify_outcome`, below `join` in this module, reads the exact
        # literal text built here -- "no super payment found" above, and
        # the "partial: "/"over: " prefixes on the next two lines -- to
        # bucket an outcome for `ImportReport`. Reword any of the three and
        # that classification silently stops matching; a test would catch
        # the drift, but the coupling is otherwise invisible from here.
        # Compared TO THE CENT on both sides, because that is the figure
        # that leaves this module: `write_canonical` writes
        # `money(row.sg_amount)`, quantised to cents, and the checker reads
        # the file back at that precision. Comparing raw Decimals reported
        # 540.00 paid against 540.004 owed as a short payment, blanked the
        # remittance date, and turned a payday where every payable cent
        # arrived on time into a $540.00 shortfall with an SG-charge
        # estimate on top. Both sides now arrive here already cent-clean,
        # because `_amount` quantises as it reads (see its docstring, and
        # `_unmet`'s), so these two calls no longer change anything. They
        # stay because this is the comparison the verdict turns on, and it
        # should say to the cent on its own face rather than depend on an
        # invariant established three functions away. The flag text prints
        # the figures as read, which is now the same thing to the cent as
        # what the two files say.
        paid_to_cents = cents(total)
        owed_to_cents = cents(row.sg_amount)
        if paid_to_cents < owed_to_cents:
            flag_parts.append(f"partial: {total} of {row.sg_amount} matched")
        elif paid_to_cents > owed_to_cents:
            flag_parts.append(
                f"over: {total} against {row.sg_amount}, check for salary sacrifice "
                "in the contribution types"
            )
        # One note per contributing super row, never deduplicated by text:
        # two different shared payments can produce identical-looking
        # notes only by coincidence of amount/row/date, and even then they
        # are two separate payments that both belong in the flag.
        flag_parts.extend(note for _, _, note in entries if note)

        # The deadline tests receipt: a matched row without a paid date is
        # not evidence the fund got the money. This applies even when only
        # part of a split contribution is undated -- reporting the known
        # date of the other part as "remitted" would read as fully settled
        # while some of the money has no evidence of arriving at all. The
        # latest date that IS known is still worth keeping (last_known_paid_
        # date) and naming in the flag: someone chasing the fund needs it,
        # even though it cannot stand in for proof the whole amount arrived.
        dated = [s for s, _, _ in entries if s.paid_date is not None]
        undated = [s for s, _, _ in entries if s.paid_date is None]
        last_known_paid_date = max(s.paid_date for s in dated) if dated else None

        if undated:
            remitted = None
            if len(undated) == len(entries):
                flag_parts.append("matched super rows carry no payment date")
            else:
                undated_total = sum(
                    (amount for s, amount, _ in entries if s.paid_date is None),
                    Decimal("0"),
                )
                flag_parts.append(
                    f"{undated_total} of {total} matched has no payment date on "
                    f"record; latest known payment date {last_known_paid_date.isoformat()}"
                )
        else:
            remitted = last_known_paid_date

        outcomes.append(
            MatchOutcome(row, remitted, "; ".join(flag_parts), last_known_paid_date)
        )

    # Sorted, not left in the caller's list order: the orphan list is
    # reported to a user, so its order is part of the answer, and the same
    # two files must not produce two different-looking reports because one
    # caller sorted its rows before handing them over.
    orphans = sorted(
        (s for s in super_rows if id(s) not in used_super_ids), key=_super_order
    )
    orphan_reasons = [
        OrphanReason(s, *_why_orphaned(coverage[id(s)], allocated_total)) for s in orphans
    ]
    return JoinResult(outcomes, orphans, key_mode, warnings, orphan_reasons)


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


def _iso(value: date | None) -> str:
    return value.isoformat() if value else ""


# How one PAYROLL row's join outcome is classified, both for
# `ImportReport`'s counts and (see `write_canonical`) for deciding what is
# safe to write into the canonical CSV. Deliberately separate from the
# ORPHAN_* constants above: those classify an unused SUPER row, these
# classify a payroll row, and the two answer different questions for
# different readers. Plain strings, not an enum, to match ORPHAN_*'s own
# style and stay trivially printable.
OUTCOME_MATCHED = "matched"
OUTCOME_OWES_NOTHING = "owes nothing"
# "no remittance date", not "no fund-receipt evidence": fund_received_date
# is blank on EVERY row this module writes, so naming a fund receipt here
# described the one thing that is never true of one row and not another.
# What this bucket means is that the payday was matched in full and at
# least one super row behind the match carries no vendor payment date, so
# `join` blanked `remitted` and the checker will read the payday as
# unfunded.
OUTCOME_UNDATED = "matched, no remittance date"
OUTCOME_PARTIAL = "partial"
OUTCOME_OVER = "over"
OUTCOME_UNMATCHED = "unmatched"


def _classify_outcome(outcome: MatchOutcome) -> str:
    """Bucket one payroll row's join outcome.

    Order matters: more than one bucket can be literally true of the same
    outcome (a partial match can also be missing a remittance date on the
    portion that did arrive), and the more specific, more actionable
    classification must win. A short payment is reported as partial even
    though part of what it did receive has no receipt evidence either --
    "you are short" is the more urgent fact than "and also go find dates
    for the rest"."""
    row = outcome.payroll
    if row.sg_amount == 0:
        return OUTCOME_OWES_NOTHING
    if outcome.flag == "no super payment found":
        return OUTCOME_UNMATCHED
    if outcome.flag.startswith("partial: "):
        return OUTCOME_PARTIAL
    if outcome.flag.startswith("over: "):
        return OUTCOME_OVER
    if outcome.remitted is None:
        return OUTCOME_UNDATED
    return OUTCOME_MATCHED


def write_canonical(result: JoinResult, path: str | Path) -> None:
    """Write the canonical contributions CSV that
    `paydaysuper.csv_io.parse_rows` reads unmodified with its default
    mapping: `CANONICAL_HEADER` is exactly the set of values in
    `csv_io.DEFAULT_MAPPING`, in the same field order.

    `remitted_date` is left blank for an `OUTCOME_PARTIAL` row, even though
    `outcome.remitted` may carry a real date. `join` already applies this
    exact rule to a split contribution that is entirely undated -- it sets
    `remitted=None` "because reporting the known date of the other part as
    remitted would read as fully settled while some of the money has no
    evidence of arriving at all" (see `join`'s docstring above). A short
    payment is the identical case: the canonical CSV has one column for the
    whole payday's contribution, `sg_amount` is the full liability, and
    writing a real paid date next to the full liability tells the checker
    the payday was settled in full. It was not -- `join` already flagged it
    `partial: ...` -- so the date is withheld here rather than carried
    through. `sg_amount` itself is never touched: it is what was OWED, not
    what arrived, and shrinking it to the amount received would understate
    the liability instead of just hiding evidence of when part of it paid.
    The `partial: ...` flag and the row-level warning `import_files` builds
    from it are where the true received amount and date are still visible.

    A payday matched IN FULL comes out blank the same way whenever any
    super row that matched it carries no vendor date: `join` sets
    `remitted=None` for that case before this function sees it, so 1000.00
    owed and 1000.00 matched, 600.00 of it dated, is written with no
    remitted_date and read by the checker as a 1000.00 shortfall. The
    reported figure is the same for both cases and so is the remedy -- the
    row-level warning carries what actually arrived, and someone applies it
    by hand -- so the console output, the README and this docstring name
    both rather than only the partial, which is the one that gets noticed.

    The employee label is the key `join` matched on, not `employee_id or
    employee_name`: under name matching a file where only some rows carry
    an id would otherwise write the id for those rows and the name for the
    rest, splitting one person the join had already merged into two
    identities in the checker's own per-employee grouping. Every row
    sharing a key writes the same label, the first one seen for that key.

    `fund_received_date` and the four flag columns are always written
    blank. No payroll or clearing-house export this tool reads carries a
    fund receipt date or these flags (see the module docstring and
    `join`'s), and inventing any of them would silently move a deadline --
    the worst defect this feature could ship.

    Every field is passed through `csv_safe`, not only employee_id. Money
    and date fields built here cannot start with a formula-lead character
    today (amounts are never negative, dates are ISO, the flag columns are
    always blank), but running all of them through the one guard is one
    rule with no unstated exception, rather than a rule that only covers
    the field known to carry attacker-controlled text today."""
    labels: dict[str, str] = {}
    for outcome in result.outcomes:
        row = outcome.payroll
        preferred = (
            row.employee_id if result.key_mode == "id" else row.employee_name
        ) or row.employee_id or row.employee_name or ""
        labels.setdefault(_key(row, result.key_mode), preferred)

    with atomic_text_output(path, encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(CANONICAL_HEADER)
        for outcome in result.outcomes:
            row = outcome.payroll
            label = labels[_key(row, result.key_mode)]
            remitted = (
                "" if _classify_outcome(outcome) == OUTCOME_PARTIAL else _iso(outcome.remitted)
            )
            values = [
                label,
                _iso(row.payday),
                money(row.sg_amount),
                remitted,
                "",  # fund_received_date: no vendor export carries a receipt date
                "",  # first_contribution_to_fund
                "",  # out_of_cycle
                "",  # next_standard_payday
                "",  # defined_benefit
            ]
            writer.writerow(csv_safe(v) for v in values)


def _pre_regime_warnings(payroll_rows: list[PayrollRow]) -> list[str]:
    """Warn about paydays the checker will refuse the whole file over.

    A payroll export spanning 30 June -- the normal shape of a
    financial-year export -- imports without complaint, and the check then
    dies with "N row(s) have a QE day before 1 Jul 2026 ... Remove them and
    run again" and writes no report at all. The README promises two
    commands turn an export into a checked report, and this is where that
    promise dead-ends, so the first command says it rather than leaving the
    second to.

    A warning, not a refusal: the rows are real payroll data and the file
    written here is still the workpaper the user edits. Naming the rows is
    the point -- they are what has to come out."""
    early = [r for r in payroll_rows if r.payday < REGIME_START]
    if not early:
        return []
    shown = ", ".join(str(r.row) for r in early[:20])
    more = f" and {len(early) - 20} more" if len(early) > 20 else ""
    earliest = min(r.payday for r in early).isoformat()
    return [
        f"{len(early)} payroll row(s) have a payday before "
        f"{REGIME_START.isoformat()} (row(s) {shown}{more}; earliest {earliest}), and "
        "the check refuses any file containing one: those paydays are governed by the "
        "old quarterly SG law, which this tool does not model. They are written to the "
        "output anyway, because they are real payroll rows -- delete them from it, or "
        "re-export from the start of the financial year in which payday super applies, "
        "before running the check."
    ]


@dataclass
class ImportReport:
    """What did and did not join, from one `import_files` run.

    `outcome_counts` is keyed by the `OUTCOME_*` constants above, one entry
    per payroll row. `orphan_reasons` is `JoinResult.orphan_reasons`
    unchanged -- the full detail behind every unused super payment, one
    entry per orphan, in the same order as the orphans themselves -- so
    nothing here collapses the four `ORPHAN_*` codes to a bare count: an
    overpayment on already-settled paydays (`ORPHAN_PAYDAYS_SETTLED`) and a
    payment that matched no payday at all (`ORPHAN_NO_PAYDAY`) read as
    opposite findings to an accountant and must stay tellable apart."""

    payroll_profile: Profile
    super_profile: Profile
    outcome_counts: dict[str, int]
    orphan_reasons: list[OrphanReason]
    key_mode: str
    warnings: list[str]

    @property
    def matched(self) -> int:
        return self.outcome_counts.get(OUTCOME_MATCHED, 0)

    @property
    def partial(self) -> int:
        return self.outcome_counts.get(OUTCOME_PARTIAL, 0)

    @property
    def unmatched(self) -> int:
        return self.outcome_counts.get(OUTCOME_UNMATCHED, 0)

    @property
    def orphans(self) -> int:
        """Total orphaned super payments, across all four ORPHAN_* codes.
        See `orphan_reasons` for the breakdown this number alone loses."""
        return len(self.orphan_reasons)

    @property
    def orphan_counts(self) -> dict[str, int]:
        """`orphan_reasons` tallied by ORPHAN_* code."""
        counts: dict[str, int] = {}
        for reason in self.orphan_reasons:
            counts[reason.code] = counts.get(reason.code, 0) + 1
        return counts

    @property
    def clean(self) -> bool:
        unclean_outcomes = (
            OUTCOME_UNDATED,
            OUTCOME_PARTIAL,
            OUTCOME_OVER,
            OUTCOME_UNMATCHED,
        )
        return not (
            any(self.outcome_counts.get(bucket) for bucket in unclean_outcomes)
            or self.orphan_reasons
        )


def import_files(
    payroll_path: str | Path,
    super_path: str | Path,
    out_path: str | Path,
    vendor: str | None = None,
    *,
    statutory_allocation_confirmed: bool = False,
) -> ImportReport:
    """Read a payroll export and a super payments export, join them, write
    the canonical contributions CSV to `out_path`, and return a summary of
    what did and did not join.

    `payroll_has_period_end`/`super_has_period_start`/`super_has_period_end`
    are derived here, not left to `join`'s defaults, from whether
    `resolve_columns` found that field in EACH file's own headers -- a
    file-level fact `read_payroll`/`read_super` surface via their third
    return value, because it is gone once the rows are built into
    `PayrollRow`/`SuperRow` objects (a `None` field on a row is then
    indistinguishable from "this file never had the column at all").

    ``statutory_allocation_confirmed`` is false by default. Where an
    employee has more than one positive payday and at least one contribution,
    the exports cannot prove LCR 2026/2's fund-receipt ordering, earliest-
    shortfall allocation or whether an assessment changed the ordering. The
    caller must reconcile those facts before this function writes a canonical
    file."""
    out = Path(out_path).resolve()
    for source in (payroll_path, super_path):
        if Path(source).resolve() == out:
            raise CsvError(
                f"the output would overwrite {source}. Choose a different path with -o."
            )

    payroll_rows, payroll_profile, payroll_resolved = read_payroll(payroll_path, vendor)
    super_rows, super_profile, super_resolved = read_super(super_path, vendor)

    both_have_ids = (
        bool(payroll_rows)
        and bool(super_rows)
        and all(r.employee_id for r in payroll_rows)
        and all(r.employee_id for r in super_rows)
    )
    key_mode = "id" if both_have_ids else "name"
    super_keys = {_key(row, key_mode) for row in super_rows if row.amount > 0}
    grouped_paydays: dict[str, list[PayrollRow]] = {}
    for row in payroll_rows:
        if (
            row.sg_amount > 0
            and row.payday >= REGIME_START
            and _key(row, key_mode) in super_keys
        ):
            grouped_paydays.setdefault(_key(row, key_mode), []).append(row)
    allocation_groups = [
        rows
        for rows in grouped_paydays.values()
        if len({row.payday for row in rows}) > 1
    ]
    if allocation_groups and not statutory_allocation_confirmed:
        affected_rows = sorted(row.row for rows in allocation_groups for row in rows)
        shown = ", ".join(str(row) for row in affected_rows[:20])
        more = f" and {len(affected_rows) - 20} more" if len(affected_rows) > 20 else ""
        raise CsvError(
            f"{len(allocation_groups)} employee allocation group(s) contain more than "
            f"one positive payday (payroll rows {shown}{more}). LCR 2026/2 "
            "paragraphs 31-33 apply contributions in fund-receipt order to the "
            "earliest QE day with a base or final shortfall. These exports contain "
            "employer payment dates and vendor periods, not fund-receipt order or "
            "assessment facts, so they cannot establish the canonical allocation. "
            "Reconcile every relevant payday, contribution receipt and assessment, "
            "then rerun with --confirm-statutory-allocation; no output was written"
        )
    result = join(
        payroll_rows,
        super_rows,
        payroll_has_period_end="period_end" in payroll_resolved,
        super_has_period_start="period_start" in super_resolved,
        super_has_period_end="period_end" in super_resolved,
    )
    # Keep the original selected path for the writer: it must replace an
    # existing output symlink, not follow it to its target.  ``out`` above is
    # only the canonical path used for the input/output alias check.
    write_canonical(result, out_path)

    outcome_counts: dict[str, int] = {}
    for outcome in result.outcomes:
        bucket = _classify_outcome(outcome)
        outcome_counts[bucket] = outcome_counts.get(bucket, 0) + 1

    warnings = _pre_regime_warnings(payroll_rows) + list(result.warnings)
    if allocation_groups:
        warnings.insert(
            0,
            "operator confirmed the LCR 2026/2 statutory allocation: all relevant "
            "paydays, fund receipts and assessments were reconciled, and the export "
            "periods plus payment-date/row order reproduce the fund-receipt order and "
            "earliest-shortfall application",
        )
    warnings.extend(f"row {o.payroll.row}: {o.flag}" for o in result.outcomes if o.flag)
    warnings.extend(
        f"super row {r.super_row.row}: {r.message}" for r in result.orphan_reasons
    )
    # Why an affected payday reads "no payment date": the row HAS a date in
    # the export, and the status is the reason it was not used. Without this
    # line, someone opens the super file, sees the date, and reads the
    # blank remitted_date as this tool's mistake instead of Beam's ladder.
    warnings.extend(
        f"super row {s.row}: status {s.unpaid_status!r} means the money never "
        "left the employer, so its payment date is not evidence of remittance "
        "and was not used"
        for s in super_rows
        if s.unpaid_status is not None
    )

    return ImportReport(
        payroll_profile=payroll_profile,
        super_profile=super_profile,
        outcome_counts=outcome_counts,
        orphan_reasons=result.orphan_reasons,
        key_mode=result.key_mode,
        warnings=warnings,
    )
