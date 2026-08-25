"""Deadline engine: SGAA 1992 s 18C pathways.

Pathways implemented:
- USUAL_7BD      s 6(1) "usual period": ends 7th business day after QE day
- EXTENDED_20BD  s 18C(2) item 1: first eligible contribution to a
                 particular fund (new/recommenced employee or fund switch)
- OUT_OF_CYCLE   s 18C(2) item 2 + F2026L00784: deadline is
                 the end of the usual period for the actual subsequent
                 non-out-of-cycle QE payment on the next schedule-consistent
                 day. A row without that payment is rejected
- ITEM4_ALIGNED  s 18C(2) item 4: a later QE day whose period would end
                 before an evidenced earlier eligible contribution's latest
                 due day inherits that later end
- SKIP_DB        defined-benefit interests: notional contribution treated
                 as received on the QE day (s 18A(3)); lateness testing
                 does not apply

Exceptional-circumstances determinations (s 18C(2) item 3) are not
modelled; if one covers the employer, results here are conservative.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from .calendar import BusinessCalendar

REGIME_START = date(2026, 7, 1)

USUAL_7BD = "USUAL_7BD"
EXTENDED_20BD = "EXTENDED_20BD"
OUT_OF_CYCLE = "OUT_OF_CYCLE"
ITEM4_ALIGNED = "ITEM4_ALIGNED"
SKIP_DB = "SKIP_DB"

# Plain-English name for each pathway, so a caveat can say which deadline the
# row actually got rather than assuming one.
PATHWAY_WORDS = {
    USUAL_7BD: "strict 7-business-day",
    EXTENDED_20BD: "20-business-day",
    OUT_OF_CYCLE: "out-of-cycle",
    ITEM4_ALIGNED: "item 4 aligned",
}


class PreRegimeError(ValueError):
    """QE day before 1 Jul 2026: old quarterly SG law applies, out of scope."""


@dataclass
class ContribLine:
    employee_id: str
    qe_day: date
    sg_amount: Decimal  # dollars
    remitted: date | None = None
    remitted_amount: Decimal | None = None
    received: date | None = None
    first_to_fund: bool = False
    out_of_cycle: bool = False
    next_standard_qe_day: date | None = None
    db_interest: bool = False
    row: int = 0
    duplicate_note: str = ""
    # Appended after every pre-existing field to preserve positional callers.
    # This is the amount associated with the payday whether or not the vendor
    # supplied a remittance date. Importers write it explicitly so an undated
    # partial cannot later look like a legacy full row when receipt is added.
    matched_amount: Decimal | None = None


def receipt_amount_cap(line: ContribLine) -> Decimal:
    """Maximum contribution amount a receipt date on this row can evidence.

    ``matched_amount`` is the preferred explicit association. Ten-column
    part-payment rows fall back to ``remitted_amount``. A legacy row with
    neither appended amount keeps its historical whole-liability meaning.
    Assessment validates the explicit amounts before this helper is used.
    """
    if line.matched_amount is not None:
        return line.matched_amount
    if line.remitted_amount is not None:
        return line.remitted_amount
    return line.sg_amount


@dataclass
class Deadline:
    due: date | None
    pathway: str
    notes: list[str] = field(default_factory=list)
    # Notes explain which rule applied; caveats mean the answer itself may
    # be wrong. Only caveats reach the console, so they stay readable.
    caveats: list[str] = field(default_factory=list)
    # The deadline this line earned on its own, kept only when apply_item4
    # overwrote `due` with an earlier contribution's later date. Re-deriving
    # it from qe_day cannot work: it would have to know which pathway won,
    # and the out-of-cycle period is not qe_day plus 7 or 20 business days.
    own_due: date | None = None
    # The item 2 deadline this row WOULD have had, held for annotate_missing_flag
    # to write about once apply_item4 has settled `due`. Set only where the row
    # supplies a usable next standard QE day without the out-of-cycle flag.
    item2_due: date | None = None
    # The latest deadline this row could inherit under item 4 when an
    # earlier positive row might, but does not yet prove, an eligible
    # contribution was received and applied on time. ``due`` remains the
    # latest deadline supported by the evidence supplied. Report assessment
    # uses this upper bound only to return an attention-driving UNKNOWN where
    # the two dates would change the verdict; it never presents the later
    # date as the deadline.
    possible_item4_due: date | None = None


def compute_due(line: ContribLine, cal: BusinessCalendar) -> Deadline:
    if line.qe_day < REGIME_START:
        raise PreRegimeError(
            f"row {line.row}: QE day {line.qe_day.isoformat()} is before 1 Jul 2026: "
            "the old quarterly SG law applies to it; this tool covers payday super only"
        )

    if line.db_interest:
        return Deadline(
            due=None,
            pathway=SKIP_DB,
            notes=[
                "defined-benefit interest: notional contribution is treated as received "
                "on the QE day (SGAA s 18A(3)); lateness testing skipped"
            ],
        )

    # Items 1 and 2 are separate rows of the same table and can both apply
    # (a new starter paid an off-cycle bonus before their first standard
    # payday). Where they do, the taxpayer gets the later period.
    notes: list[str] = []
    caveats: list[str] = []
    candidates: list[tuple[date, str, str]] = []
    item2: date | None = None

    if line.out_of_cycle:
        if line.next_standard_qe_day is None:
            # F2026L00784 s 5(3) makes a subsequent, non-out-of-cycle QE
            # payment on the next scheduled day part of the definition. A
            # termination/final payment therefore cannot be rescued by
            # silently falling back to its own usual period, and no item 2
            # deadline exists until this fact is supplied.
            raise ValueError(
                f"row {line.row}: out_of_cycle=yes requires next_standard_qe_day. "
                "F2026L00784 s 5 requires a subsequent non-out-of-cycle QE payment "
                "on the next day consistent with the established schedule; a final "
                "or termination payment does not qualify without that subsequent "
                "payment. Supply the next standard payday or set out_of_cycle=no"
            )
        if line.next_standard_qe_day <= line.qe_day:
            raise ValueError(
                f"row {line.row}: next_standard_qe_day must be after qe_day"
            )
        candidates.append(
            (
                cal.add_business_days(line.next_standard_qe_day, 7),
                OUT_OF_CYCLE,
                "out-of-cycle earnings: deadline is the usual period of the next "
                "schedule-consistent day on which the employer actually made a "
                "subsequent non-out-of-cycle QE payment, "
                f"{line.next_standard_qe_day.isoformat()} "
                "(s 18C(2) item 2; F2026L00784 s 5)",
            )
        )
    elif line.next_standard_qe_day is not None:
        # The next payday is only ever read inside the branch above, so a row
        # that supplies it but leaves the flag blank is silently given the
        # strict 7-business-day deadline. csv_io does not cross-validate the
        # two columns either, so the check belongs here.
        if line.next_standard_qe_day <= line.qe_day:
            caveats.append(
                f"next standard QE day {line.next_standard_qe_day.isoformat()} is not "
                f"after the QE day {line.qe_day.isoformat()} and the out-of-cycle flag "
                "is not set, so the column was ignored. Correct it or set "
                "out_of_cycle=yes"
            )
        else:
            # Held, not written, until the winning candidate is known. Item 1
            # can beat item 2 on the same row, and a caveat written here would
            # name the 7-business-day pathway the row did not take and a
            # deadline earlier than the one it actually got.
            item2 = cal.add_business_days(line.next_standard_qe_day, 7)

    if line.first_to_fund:
        candidates.append(
            (
                cal.add_business_days(line.qe_day, 20),
                EXTENDED_20BD,
                "first eligible contribution to this fund: extended usual period, "
                "20 business days (s 18C(2) item 1)",
            )
        )

    if not candidates:
        candidates.append((cal.add_business_days(line.qe_day, 7), USUAL_7BD, ""))

    due, pathway, note = max(candidates, key=lambda c: c[0])
    if note:
        notes.append(note)
    if line.out_of_cycle and line.first_to_fund and line.next_standard_qe_day is not None:
        notes.append(
            "both the out-of-cycle and first-contribution rules apply; using the "
            "later deadline"
        )

    # The missing-flag caveat is deferred to annotate_missing_flag for the
    # same reason the calendar caveats are: apply_item4 can still move `due`,
    # and a caveat written here would name the pathway and deadline the row
    # had before that move rather than the ones it ends up with.
    return Deadline(
        due=due, pathway=pathway, notes=notes, caveats=caveats, item2_due=item2
    )


def annotate_missing_flag(pairs: list[tuple[ContribLine, Deadline]]) -> None:
    """Caveat the rows that supply a next standard QE day without the
    out-of-cycle flag, written against the FINAL deadline.

    Run after apply_item4. It is worth saying only where setting the flag
    would move the deadline the row actually got; where item 1 or an item 4
    alignment already carried the row past the item 2 date, the flag changes
    nothing and a caveat urging it would send the operator after a deadline
    that does not move."""
    for line, dl in pairs:
        next_standard_qe_day = line.next_standard_qe_day
        if dl.item2_due is None or dl.due is None or next_standard_qe_day is None:
            continue
        pathway_words = PATHWAY_WORDS.get(dl.pathway, dl.pathway)
        if dl.item2_due > dl.due:
            dl.caveats.append(
                f"a next standard QE day {next_standard_qe_day.isoformat()} is "
                "supplied but the out-of-cycle flag is not set, so the "
                f"{pathway_words} deadline {dl.due.isoformat()} was used. If this payday "
                "is out of cycle, set out_of_cycle=yes and the deadline becomes "
                f"{dl.item2_due.isoformat()} (s 18C(2) item 2; F2026L00784)"
            )
        else:
            dl.caveats.append(
                f"a next standard QE day {next_standard_qe_day.isoformat()} is "
                f"supplied but the out-of-cycle flag is not set. The {pathway_words} "
                f"deadline {dl.due.isoformat()} was used, and setting out_of_cycle=yes "
                f"would not change it: the item 2 deadline is "
                f"{dl.item2_due.isoformat()}, which is no later "
                "(s 18C(2) items 1, 2 and 4)"
            )


def _twelve_months_before(d: date) -> date:
    """The same calendar date a year earlier, with 29 February falling back
    to 28 February."""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, month=2, day=28)


def earliest_prepayment_day(qe_day: date) -> date:
    """First day of the 12-month pre-payment window in s 18C(1)(c)(ii).

    The window ends the day before the QE day, so it opens the day after the
    same calendar date a year before that. Public because report.assess tests
    a pre-payment against the same window: one statutory rule, stated once,
    so the pre-payment verdict and the item 4 evidence test cannot drift
    apart."""
    return _twelve_months_before(qe_day - timedelta(days=1)) + timedelta(days=1)


def _item4_evidence(
    line: ContribLine,
    confirmed_due: date,
    possible_due: date,
    as_at: date | None,
) -> str:
    """Classify whether a row proves, might contain, or cannot contain the
    earlier eligible contribution item 4 requires.

    A canonical row associates its fund receipt with this QE day; that is the
    operator's allocation assertion. Only a receipt within the statutory
    pre-payment/on-time window proves the contribution. A remittance never
    does. Missing or future receipt facts remain possible unless a known
    receipt/remittance makes an eligible receipt impossible."""
    if (
        line.sg_amount <= 0
        or line.db_interest
        or receipt_amount_cap(line) <= 0
    ):
        return "impossible"

    receipt = line.received
    earliest_prepayment = earliest_prepayment_day(line.qe_day)
    if receipt is not None:
        if receipt < earliest_prepayment:
            return "impossible"
        if as_at is None or receipt <= as_at:
            if receipt < line.qe_day or receipt <= confirmed_due:
                return "confirmed"
            if receipt > possible_due:
                return "impossible"
            return "possible"
        # A future receipt is not evidence in an as-at report. It can still
        # establish the item later if it falls within the widest supported
        # period, so retain only that possibility.
        return "possible" if receipt <= possible_due else "impossible"

    # Fund receipt cannot precede remittance. A remittance after even the
    # widest possible deadline therefore disproves an on-time contribution;
    # an earlier remittance remains merely possible, never confirmed.
    if line.remitted is not None and line.remitted > possible_due:
        return "impossible"
    return "possible"


def apply_item4(
    pairs: list[tuple[ContribLine, Deadline]], as_at: date | None = None
) -> None:
    """Apply SGAA s 18C(2) item 4 without manufacturing its missing facts.

    Item 4 applies only where an earlier eligible contribution *was made*
    and *was applied* to the earlier QE day. A positive payroll amount or an
    employer remittance does not prove either fact. ``due`` is extended only
    by an on-time fund receipt associated with the earlier canonical row.
    Unevidenced rows propagate a separate possible upper bound so assessment
    can fail closed when that uncertainty would change the verdict.

    Mutates deadlines in place. Call after ``compute_due`` over all lines.
    ``as_at`` excludes future receipt facts from confirmed evidence."""
    by_employee: dict[str, list[tuple[ContribLine, Deadline]]] = {}
    for line, dl in pairs:
        if dl.due is None:
            continue
        by_employee.setdefault(line.employee_id, []).append((line, dl))

    # Ids are grouped exactly as given. Folding case here could only ever
    # extend a deadline and so hide a real liability, which is the wrong way
    # to be wrong; say so instead and let the operator decide. The caveat
    # names row numbers, never the ids themselves: caveats reach the console,
    # and redirected console output must not place a payroll identifier in a
    # process log. Each named row already carries its employee_id in its own
    # report CSV column, so nothing is lost there.
    by_casefold: dict[str, set[str]] = {}
    for employee_id in by_employee:
        by_casefold.setdefault(employee_id.casefold(), set()).add(employee_id)
    for variants in by_casefold.values():
        if len(variants) > 1:
            rows = sorted(
                line.row
                for employee_id in variants
                for line, _ in by_employee[employee_id]
            )
            listed = ", ".join(str(row) for row in rows)
            for employee_id in variants:
                for _, dl in by_employee[employee_id]:
                    dl.caveats.append(
                        f"the employee ids on rows {listed} differ only by "
                        "capitalisation and are treated as different people, so no "
                        "deadline is aligned between them (s 18C(2) item 4). If they "
                        "are one person, make the ids match"
                    )

    for items in by_employee.values():
        items.sort(key=lambda p: (p[0].qe_day, p[0].row))
        confirmed_latest: date | None = None
        possible_latest: date | None = None
        # Item 4 keys on a LATER QE day, so contributions sharing a QE day
        # are resolved as one group: none of them aligns to a sibling, and
        # the group's latest due day is what later QE days inherit. Without
        # the grouping, CSV row order would decide the verdict.
        index = 0
        while index < len(items):
            end = index
            while end < len(items) and items[end][0].qe_day == items[index][0].qe_day:
                end += 1
            group = items[index:end]

            group_confirmed = confirmed_latest
            group_possible = possible_latest
            for line, dl in group:
                if (
                    confirmed_latest is not None
                    and dl.due is not None
                    and dl.due < confirmed_latest
                ):
                    dl.notes.append(
                        "deadline aligned to an evidenced earlier eligible "
                        "contribution's latest due day "
                        f"{confirmed_latest.isoformat()} (s 18C(2) item 4)"
                    )
                    dl.own_due = dl.due
                    dl.due = confirmed_latest
                    dl.pathway = ITEM4_ALIGNED

                if dl.due is None:
                    continue
                widest_due = dl.due
                if possible_latest is not None and possible_latest > widest_due:
                    widest_due = possible_latest
                    dl.possible_item4_due = possible_latest

                evidence = _item4_evidence(line, dl.due, widest_due, as_at)
                if evidence == "confirmed":
                    group_confirmed = (
                        dl.due
                        if group_confirmed is None
                        else max(group_confirmed, dl.due)
                    )
                    group_possible = (
                        widest_due
                        if group_possible is None
                        else max(group_possible, widest_due)
                    )
                elif evidence == "possible":
                    group_possible = (
                        widest_due
                        if group_possible is None
                        else max(group_possible, widest_due)
                    )

            confirmed_latest = group_confirmed
            possible_latest = group_possible
            index = end


def annotate_calendar_risk(
    pairs: list[tuple[ContribLine, Deadline]], cal: BusinessCalendar
) -> None:
    """Attach calendar caveats to the FINAL due date.

    Run after apply_item4: a deadline it moves is the one the user acts on,
    so a caveat computed against the line's own period end could name a date
    the row no longer has."""
    for line, dl in pairs:
        if dl.due is None:
            continue
        horizon = cal.check_horizon(dl.due)
        if horizon:
            dl.caveats.append(horizon)
        provisional = cal.provisional_hits(line.qe_day, dl.due)
        if provisional:
            dl.caveats.append(
                "deadline window contains unconfirmed holiday dates that were not "
                "used to extend the deadline: " + "; ".join(provisional) + ". Confirm "
                "the date against an official whole-of-jurisdiction source and add it "
                "with --holidays-override if it applies"
            )
