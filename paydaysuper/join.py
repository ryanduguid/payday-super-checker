"""Join a payroll export to a super-payments export.

Public types and join() are re-exported from importers so existing callers
and tests keep working.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from .csv_io import CsvError, cents
from .profiles import normalise_name

if TYPE_CHECKING:
    from .importers import PayrollRow, SuperRow

@dataclass
class MatchOutcome:
    payroll: PayrollRow
    remitted: date | None
    flag: str
    last_known_paid_date: date | None
    remitted_amount: Decimal | None = None
    matched_amount: Decimal | None = None


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
    if s.period_start is None:
        return s.period_end == target if s.period_end is not None else False
    if s.period_end is None:
        return s.period_start == target
    return s.period_start <= target <= s.period_end


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
                MatchOutcome(
                    row,
                    None,
                    "no super guarantee owed for this payday",
                    None,
                    matched_amount=Decimal("0"),
                )
            )
            continue

        entries = contributions.get(id(row), [])
        if not entries:
            outcomes.append(
                MatchOutcome(
                    row,
                    None,
                    "no super payment found",
                    None,
                    matched_amount=Decimal("0"),
                )
            )
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
        matched_amount = min(paid_to_cents, owed_to_cents)
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
        # part of a split contribution is undated. `remitted_amount` prevents
        # the known date from reading as full operational settlement, while
        # `matched_amount` preserves the total association independently and
        # caps any receipt date later supplied by the operator. Keep the latest
        # known date for the dated subtotal and expose the undated remainder.
        # This is conservative between several known instalment dates because
        # a single canonical row cannot represent each tranche.
        dated = [s for s, _, _ in entries if s.paid_date is not None]
        undated = [s for s, _, _ in entries if s.paid_date is None]
        last_known_paid_date = max(
            (s.paid_date for s in dated if s.paid_date is not None), default=None
        )
        dated_total = sum(
            (amount for s, amount, _ in entries if s.paid_date is not None),
            Decimal("0"),
        )
        remitted_amount = dated_total if dated_total else None

        if undated:
            remitted = last_known_paid_date
            if len(undated) == len(entries):
                flag_parts.append("matched super rows carry no payment date")
            else:
                assert last_known_paid_date is not None
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
            MatchOutcome(
                row,
                remitted,
                "; ".join(flag_parts),
                last_known_paid_date,
                remitted_amount,
                matched_amount,
            )
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
