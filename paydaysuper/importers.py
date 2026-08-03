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
    value = row.employee_id if mode == "id" else row.employee_name
    return normalise_header(value or "")


def _covers(s: SuperRow, target: date) -> bool:
    """Whether a super row's period includes a target date, inclusive of
    both ends.

    An exclusive start was tried (round 3) to stop one period's end being
    repeated as the next period's start from re-claiming the earlier
    payday. It broke the opposite, equally normal convention -- a period
    that starts ON the payday it settles, or a payday that lands on a
    period's own start date -- turning a clean match into a false orphan.
    Fixing the boundary belongs to the two-pass allocation in `join`, not
    to a stricter date comparison here: pass 1 lets an unambiguous single-
    coverage payment settle its payday before any period-overlap payment
    is even considered, so a shared boundary date that pass 1 already
    resolved has zero balance left to be fought over in pass 2. See
    `join`'s docstring.

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
    more, from an overpayment) has nothing left to be short of."""
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

    Order: a covered payroll row whose effective period end falls exactly
    on this payment's own period end is settled FIRST; every other covered
    row follows oldest payday first. A super payment's period end normally
    lands on the payday it covers (owner ruling), so when the money is
    short, the payday the period actually names is the one that reads as
    settled and an earlier payday carries the shortfall -- not the reverse,
    which reported the paid payday as unpaid and the unpaid one as
    part-paid, moving the exposure by a full pay cycle. The priority fires
    only for a covered payday sitting exactly on the period end, so a
    monthly or quarterly payment apportioned across paydays that never
    touch its period end is unaffected and stays oldest-first.

    Both sort keys are total orders over distinct payroll rows -- row
    numbers are unique within one file, so the sort never has to fall back
    on how `payroll_rows` happened to be ordered when it was passed to
    `join`. The same input, in any order, apportions the same way.

    Any amount left over once every covered row's balance is satisfied
    lands on the chronologically last row that received an allocation.
    That was `allocations[-1]` while the sort was purely oldest-first;
    naming it explicitly keeps the leftover on the newest payday now that
    the period-end priority can put a different row last in sort order.
    The priority decides who goes short when money runs out, and changes
    nothing about where an unattributable excess is reported."""
    period_end = s.period_end
    ordered = sorted(
        covered,
        key=lambda r: (
            0 if period_end is not None and r.effective_period_end == period_end else 1,
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

    Two passes decide what each super row contributes, run in this order
    for every employee together (not employee by employee, since the
    passes and the sort inside each are already scoped by coverage):

    Pass 1 -- every super row whose period covers exactly one payroll row
    settles that row first, for its full amount (an overpayment here still
    shows up as `over:` later; nothing here is capped). This is what
    resolves a shared period boundary cleanly: if one super row's period
    covers a payday on its own, it settles that payday before any wider,
    multi-payday super row is even considered, so by the time pass 2 looks
    at a payment whose period happens to also reach that same payday, the
    payday's balance is already at zero and there is nothing left to
    apportion to it.

    Pass 2 -- every super row whose period covers more than one payroll
    row apportions its amount across them, each capped at its UNMET
    balance (`sg_amount` minus everything already allocated to it, from any
    super row, in either pass -- not its full `sg_amount` regardless of
    what it already has). A covered payday sitting exactly on the
    payment's own period end is settled first; the rest follow oldest
    payday first (see `_allocate`). Pass-2 super rows are processed in a
    fixed order, sorted by paid date then row number, so which row's
    balance is already reduced by the time a later pass-2 payment is
    considered never depends on the order `super_rows` was passed in.

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
    # note) a payroll row received, whether from a plain pass-1 match or as
    # its share of a pass-2 apportioned payment, so the totalling below
    # (partial/over/remitted) never has to care which kind it was looking
    # at. allocated_total[id(payroll_row)] is the running sum backing
    # `_unmet`, updated as each pass completes so pass 2 always sees the
    # true balance left over from pass 1 and from every pass-2 super row
    # already processed before it.
    contributions: dict[int, list[tuple[SuperRow, Decimal, str]]] = {}
    allocated_total: dict[int, Decimal] = {}
    used_super_ids: set[int] = set()

    def _credit(row: PayrollRow, s: SuperRow, share: Decimal, note: str) -> None:
        contributions.setdefault(id(row), []).append((s, share, note))
        allocated_total[id(row)] = allocated_total.get(id(row), Decimal("0")) + share

    pass1 = [s for s in super_rows if len(coverage[id(s)]) == 1]
    for s in pass1:
        row = coverage[id(s)][0]
        if row.sg_amount == 0:
            # A super row whose period matches only a payroll row that
            # owes nothing has no defensible recipient at all; leaving it
            # unclaimed (an orphan) is more honest than crediting a row
            # that is about to be reported as owing zero regardless.
            continue
        _credit(row, s, s.amount, "")
        used_super_ids.add(id(s))

    pass2 = [s for s in super_rows if len(coverage[id(s)]) > 1]
    for s in sorted(pass2, key=lambda s: (s.paid_date or date.max, *_super_order(s))):
        covered = coverage[id(s)]
        competing = [r for r in covered if _unmet(r, allocated_total) > 0]
        _check_defensible(s, competing)
        allocations = _allocate(s, covered, allocated_total)
        # A super row only reads as a SHARED payment if more than one
        # payroll row was actually still contesting its money at the
        # moment it was processed. A row whose balance pass 1 (or an
        # earlier pass-2 super row) already zeroed out is not competing
        # for anything here, even if this payment's own period still
        # structurally reaches its payday -- see `join`'s docstring on the
        # shared-boundary case this resolves.
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
        if total < row.sg_amount:
            flag_parts.append(f"partial: {total} of {row.sg_amount} matched")
        elif total > row.sg_amount:
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
