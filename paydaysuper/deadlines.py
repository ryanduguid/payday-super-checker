"""Deadline engine: SGAA 1992 s 18C pathways.

Pathways implemented:
- USUAL_7BD      s 6(1) "usual period": ends 7th business day after QE day
- EXTENDED_20BD  s 18C(2) item 1: first eligible contribution to a
                 particular fund (new/recommenced employee or fund switch)
- OUT_OF_CYCLE   s 18C(2) item 2 + LI 2026/20: deadline is the end of the
                 usual period for the first LATER standard QE day; falls
                 back to the line's own 7-business-day period when no later
                 standard QE day exists
- ITEM4_ALIGNED  s 18C(2) item 4: a later QE day whose period would end
                 before an earlier contribution's latest due day inherits
                 that later end
- SKIP_DB        defined-benefit interests: notional contribution treated
                 as received on the QE day (s 18A(3)); lateness testing
                 does not apply

Exceptional-circumstances determinations (s 18C(2) item 3) are not
modelled; if one covers the employer, results here are conservative.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
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
    received: date | None = None
    first_to_fund: bool = False
    out_of_cycle: bool = False
    next_standard_qe_day: date | None = None
    db_interest: bool = False
    row: int = 0
    duplicate_note: str = ""


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
        if line.next_standard_qe_day is not None:
            if line.next_standard_qe_day <= line.qe_day:
                raise ValueError(
                    f"row {line.row}: next_standard_qe_day must be after qe_day"
                )
            candidates.append(
                (
                    cal.add_business_days(line.next_standard_qe_day, 7),
                    OUT_OF_CYCLE,
                    "out-of-cycle earnings: deadline is the usual period of the next "
                    f"standard QE day {line.next_standard_qe_day.isoformat()} "
                    "(s 18C(2) item 2, LI 2026/20)",
                )
            )
        else:
            # A data-quality problem, not a pathway note: it must survive even
            # when another candidate wins, because the real item 2 deadline
            # could be later than anything computed here.
            caveats.append(
                "out-of-cycle flag set but no next standard QE day supplied, so the "
                "item 2 deadline cannot be calculated. Supply the next regular payday: "
                "the real deadline may be later than the one shown"
            )
            candidates.append(
                (cal.add_business_days(line.qe_day, 7), OUT_OF_CYCLE, "")
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
        if dl.item2_due is None or dl.due is None:
            continue
        pathway_words = PATHWAY_WORDS.get(dl.pathway, dl.pathway)
        if dl.item2_due > dl.due:
            dl.caveats.append(
                f"a next standard QE day {line.next_standard_qe_day.isoformat()} is "
                "supplied but the out-of-cycle flag is not set, so the "
                f"{pathway_words} deadline {dl.due.isoformat()} was used. If this payday "
                "is out of cycle, set out_of_cycle=yes and the deadline becomes "
                f"{dl.item2_due.isoformat()} (s 18C(2) item 2, LI 2026/20)"
            )
        else:
            dl.caveats.append(
                f"a next standard QE day {line.next_standard_qe_day.isoformat()} is "
                f"supplied but the out-of-cycle flag is not set. The {pathway_words} "
                f"deadline {dl.due.isoformat()} was used, and setting out_of_cycle=yes "
                f"would not change it: the item 2 deadline is "
                f"{dl.item2_due.isoformat()}, which is no later "
                "(s 18C(2) items 1, 2 and 4)"
            )


def apply_item4(pairs: list[tuple[ContribLine, Deadline]]) -> None:
    """s 18C(2) item 4: for each employee, a later QE day's deadline is the
    max of its own period end and any earlier contribution's latest due day.
    Mutates deadlines in place. Call after compute_due over all lines."""
    by_employee: dict[str, list[tuple[ContribLine, Deadline]]] = {}
    for line, dl in pairs:
        if dl.due is None:
            continue
        by_employee.setdefault(line.employee_id, []).append((line, dl))

    # Ids are grouped exactly as given. Folding case here could only ever
    # extend a deadline and so hide a real liability, which is the wrong way
    # to be wrong; say so instead and let the operator decide.
    by_casefold: dict[str, set[str]] = {}
    for employee_id in by_employee:
        by_casefold.setdefault(employee_id.casefold(), set()).add(employee_id)
    for variants in by_casefold.values():
        if len(variants) > 1:
            listed = ", ".join(sorted(variants))
            for employee_id in variants:
                for _, dl in by_employee[employee_id]:
                    dl.caveats.append(
                        f"employee ids {listed} differ only by capitalisation and are "
                        "treated as different people, so no deadline is aligned between "
                        "them (s 18C(2) item 4). If they are one person, make the ids match"
                    )

    for items in by_employee.values():
        items.sort(key=lambda p: (p[0].qe_day, p[0].row))
        running_latest: date | None = None
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

            group_latest = running_latest
            for line, dl in group:
                if (
                    running_latest is not None
                    and dl.due is not None
                    and dl.due < running_latest
                ):
                    dl.notes.append(
                        "deadline aligned to an earlier contribution's latest due day "
                        f"{running_latest.isoformat()} (s 18C(2) item 4)"
                    )
                    dl.own_due = dl.due
                    dl.due = running_latest
                    dl.pathway = ITEM4_ALIGNED
                # Item 4 aligns to an earlier ELIGIBLE CONTRIBUTION. A payday
                # carrying no SG is not one, so it cannot seed the window a
                # later real payday inherits: letting it through extended a
                # genuine deadline and turned a late line on time. A nil line
                # can still receive an alignment; it has nothing to assess
                # either way.
                if dl.due is not None and line.sg_amount > 0:
                    group_latest = dl.due if group_latest is None else max(group_latest, dl.due)

            running_latest = group_latest
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
                "deadline window contains provisional (not yet gazetted) holiday dates: "
                + "; ".join(provisional)
            )
