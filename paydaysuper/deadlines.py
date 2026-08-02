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


@dataclass
class Deadline:
    due: date | None
    pathway: str
    notes: list[str] = field(default_factory=list)


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
    candidates: list[tuple[date, str, str]] = []

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
            candidates.append(
                (
                    cal.add_business_days(line.qe_day, 7),
                    OUT_OF_CYCLE,
                    "out-of-cycle flag set but no next standard QE day supplied: "
                    "using the line's own 7-business-day period (conservative fallback)",
                )
            )

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
    if len(candidates) > 1:
        notes.append(
            "both the out-of-cycle and first-contribution rules apply; using the "
            "later deadline"
        )

    horizon = cal.check_horizon(due)
    if horizon:
        notes.append(horizon)
    provisional = cal.provisional_hits(line.qe_day, due)
    if provisional:
        notes.append(
            "deadline window contains provisional (not yet gazetted) holiday dates: "
            + "; ".join(provisional)
        )
    return Deadline(due=due, pathway=pathway, notes=notes)


def apply_item4(pairs: list[tuple[ContribLine, Deadline]]) -> None:
    """s 18C(2) item 4: for each employee, a later QE day's deadline is the
    max of its own period end and any earlier contribution's latest due day.
    Mutates deadlines in place. Call after compute_due over all lines."""
    by_employee: dict[str, list[tuple[ContribLine, Deadline]]] = {}
    for line, dl in pairs:
        if dl.due is None:
            continue
        by_employee.setdefault(line.employee_id, []).append((line, dl))

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
                    dl.due = running_latest
                    dl.pathway = ITEM4_ALIGNED
                if dl.due is not None:
                    group_latest = dl.due if group_latest is None else max(group_latest, dl.due)

            running_latest = group_latest
            index = end
