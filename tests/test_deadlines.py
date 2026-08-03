from datetime import date
from decimal import Decimal

import pytest

from paydaysuper.calendar import load_calendar
from paydaysuper.deadlines import (
    EXTENDED_20BD,
    ITEM4_ALIGNED,
    OUT_OF_CYCLE,
    SKIP_DB,
    USUAL_7BD,
    ContribLine,
    PreRegimeError,
    annotate_calendar_risk,
    apply_item4,
    compute_due,
)


@pytest.fixture(scope="module")
def cal():
    return load_calendar()


def line(**kwargs) -> ContribLine:
    base = dict(
        employee_id="E1",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("600.00"),
        row=2,
    )
    base.update(kwargs)
    return ContribLine(**base)


def test_usual_period_is_seven_business_days(cal):
    dl = compute_due(line(), cal)
    assert dl.pathway == USUAL_7BD
    assert dl.due == date(2026, 7, 20)


def test_first_contribution_to_fund_gets_twenty_business_days(cal):
    dl = compute_due(line(first_to_fund=True), cal)
    assert dl.pathway == EXTENDED_20BD
    assert dl.due == date(2026, 8, 7)  # ATO worked example
    assert any("s 18C(2) item 1" in n for n in dl.notes)


def test_out_of_cycle_rides_the_next_standard_payday(cal):
    dl = compute_due(
        line(qe_day=date(2026, 7, 15), out_of_cycle=True, next_standard_qe_day=date(2026, 7, 23)),
        cal,
    )
    assert dl.pathway == OUT_OF_CYCLE
    assert dl.due == cal.add_business_days(date(2026, 7, 23), 7)


def test_out_of_cycle_without_next_payday_falls_back(cal):
    dl = compute_due(line(out_of_cycle=True), cal)
    assert dl.pathway == OUT_OF_CYCLE
    assert dl.due == date(2026, 7, 20)
    assert any("cannot be calculated" in n for n in dl.caveats)


def test_next_payday_without_the_flag_names_the_item_2_deadline(cal):
    """A row that supplies the next payday but leaves out_of_cycle blank was
    given the strict 7-business-day deadline with nothing said about it."""
    dl = compute_due(
        line(qe_day=date(2026, 7, 15), next_standard_qe_day=date(2026, 7, 23)), cal
    )
    assert dl.pathway == USUAL_7BD
    assert dl.due == cal.add_business_days(date(2026, 7, 15), 7)
    caveat = [c for c in dl.caveats if "out_of_cycle=yes" in c]
    assert caveat, dl.caveats
    assert cal.add_business_days(date(2026, 7, 23), 7).isoformat() in caveat[0]


def test_next_payday_without_the_flag_is_flagged_when_it_is_not_later(cal):
    dl = compute_due(
        line(qe_day=date(2026, 7, 15), next_standard_qe_day=date(2026, 7, 1)), cal
    )
    assert dl.due == cal.add_business_days(date(2026, 7, 15), 7)
    assert any("is not after the QE day" in c for c in dl.caveats)


def test_out_of_cycle_row_gets_no_missing_flag_caveat(cal):
    dl = compute_due(
        line(qe_day=date(2026, 7, 15), out_of_cycle=True, next_standard_qe_day=date(2026, 7, 23)),
        cal,
    )
    assert not any("out_of_cycle=yes" in c for c in dl.caveats)


def test_out_of_cycle_next_payday_must_be_later(cal):
    with pytest.raises(ValueError):
        compute_due(
            line(out_of_cycle=True, next_standard_qe_day=date(2026, 7, 1)),
            cal,
        )


def test_defined_benefit_lines_are_skipped(cal):
    dl = compute_due(line(db_interest=True), cal)
    assert dl.pathway == SKIP_DB
    assert dl.due is None


def test_pre_regime_qe_day_is_rejected(cal):
    with pytest.raises(PreRegimeError):
        compute_due(line(qe_day=date(2026, 6, 30)), cal)


def test_regime_starts_on_first_july_2026(cal):
    dl = compute_due(line(qe_day=date(2026, 7, 1)), cal)
    assert dl.due == cal.add_business_days(date(2026, 7, 1), 7)


def test_item4_aligns_a_later_payday_inside_an_extended_window(cal):
    first = line(qe_day=date(2026, 7, 9), first_to_fund=True, row=2)
    second = line(qe_day=date(2026, 7, 23), row=3)
    pairs = [(l, compute_due(l, cal)) for l in (first, second)]
    own_due = pairs[1][1].due
    apply_item4(pairs)
    assert own_due == date(2026, 8, 4)
    assert pairs[1][1].due == date(2026, 8, 7)  # inherits the extended end
    assert pairs[1][1].pathway == ITEM4_ALIGNED


def test_item4_does_not_shorten_a_later_deadline(cal):
    first = line(qe_day=date(2026, 7, 9), row=2)
    second = line(qe_day=date(2026, 8, 20), row=3)
    pairs = [(l, compute_due(l, cal)) for l in (first, second)]
    later_due = pairs[1][1].due
    apply_item4(pairs)
    assert pairs[1][1].due == later_due
    assert pairs[1][1].pathway == USUAL_7BD


def test_item4_is_per_employee(cal):
    a = line(employee_id="A", qe_day=date(2026, 7, 9), first_to_fund=True, row=2)
    b = line(employee_id="B", qe_day=date(2026, 7, 23), row=3)
    pairs = [(l, compute_due(l, cal)) for l in (a, b)]
    apply_item4(pairs)
    assert pairs[1][1].due == date(2026, 8, 4)  # unaffected by A's window


def test_provisional_dates_are_flagged(cal):
    l = line(qe_day=date(2026, 9, 21))
    pairs = [(l, compute_due(l, cal))]
    annotate_calendar_risk(pairs, cal)
    assert any("provisional" in n for n in pairs[0][1].caveats)


def test_item4_does_not_align_contributions_sharing_a_qe_day(cal):
    """Item 4 keys on a LATER QE day. Two contributions on the same payday
    must not inherit each other's deadline, or CSV row order would decide
    the verdict."""
    extended = line(qe_day=date(2026, 7, 9), first_to_fund=True, row=2)
    ordinary = line(qe_day=date(2026, 7, 9), row=3)
    pairs = [(l, compute_due(l, cal)) for l in (extended, ordinary)]
    apply_item4(pairs)
    assert pairs[1][1].due == date(2026, 7, 20)
    assert pairs[1][1].pathway == USUAL_7BD


def test_item4_result_is_independent_of_row_order(cal):
    """Same facts, rows swapped. Row numbers follow file position, as they
    do in a real CSV, so this fails if row order can change a verdict."""
    def run(order):
        rows = [
            line(qe_day=date(2026, 7, 9), first_to_fund=flag, row=i)
            for i, flag in enumerate(order, start=2)
        ]
        pairs = [(l, compute_due(l, cal)) for l in rows]
        apply_item4(pairs)
        return {l.first_to_fund: (d.due, d.pathway) for l, d in pairs}

    assert run([True, False]) == run([False, True])


def test_item4_aligns_paydays_given_out_of_date_order(cal):
    """Every row in the test above shares one QE day, so apply_item4's
    chronological sort key is never exercised and can be deleted with the
    suite green. Here the later payday comes first in the file."""
    def run(qe_days):
        rows = [
            line(qe_day=day, first_to_fund=(day == date(2026, 7, 9)), row=i)
            for i, day in enumerate(qe_days, start=2)
        ]
        pairs = [(l, compute_due(l, cal)) for l in rows]
        apply_item4(pairs)
        return {l.qe_day: (d.due, d.pathway) for l, d in pairs}

    early, late = date(2026, 7, 9), date(2026, 7, 23)
    in_order = run([early, late])
    out_of_order = run([late, early])
    assert in_order[late] == (date(2026, 8, 7), ITEM4_ALIGNED)
    assert out_of_order == in_order


def test_later_qe_day_inherits_the_longest_window_from_a_group(cal):
    """A later payday inherits the latest due day of everything before it,
    not just the last row of the previous group."""
    rows = [
        line(qe_day=date(2026, 7, 9), first_to_fund=True, row=2),
        line(qe_day=date(2026, 7, 9), row=3),
        line(qe_day=date(2026, 7, 23), row=4),
    ]
    pairs = [(l, compute_due(l, cal)) for l in rows]
    apply_item4(pairs)
    assert pairs[2][1].due == date(2026, 8, 7)
    assert pairs[2][1].pathway == ITEM4_ALIGNED


def test_both_item_1_and_item_2_apply_taking_the_later_deadline(cal):
    """A new starter paid an off-cycle bonus gets whichever period ends
    later, not whichever branch the code tests first."""
    dl = compute_due(
        line(
            qe_day=date(2026, 7, 9),
            first_to_fund=True,
            out_of_cycle=True,
            next_standard_qe_day=date(2026, 7, 15),
        ),
        cal,
    )
    assert dl.due == date(2026, 8, 7)  # the 20-business-day period wins
    assert any("both the out-of-cycle and first-contribution" in n for n in dl.notes)


def test_out_of_cycle_wins_when_its_window_ends_later(cal):
    dl = compute_due(
        line(
            qe_day=date(2026, 7, 9),
            first_to_fund=True,
            out_of_cycle=True,
            next_standard_qe_day=date(2026, 9, 1),
        ),
        cal,
    )
    assert dl.pathway == OUT_OF_CYCLE
    assert dl.due == cal.add_business_days(date(2026, 9, 1), 7)


def test_deadline_past_the_calendar_horizon_warns(cal):
    from datetime import timedelta

    qe = cal.verified_until - timedelta(days=3)
    l = line(qe_day=qe)
    pairs = [(l, compute_due(l, cal))]
    annotate_calendar_risk(pairs, cal)
    assert any("verified horizon" in n for n in pairs[0][1].caveats)


def test_out_of_cycle_without_next_payday_keeps_its_warning_when_item_1_wins(cal):
    """The missing-data warning must survive even when the 20-business-day
    period is the later deadline, because the real item 2 deadline could be
    later still."""
    dl = compute_due(line(first_to_fund=True, out_of_cycle=True), cal)
    assert dl.due == date(2026, 8, 7)
    assert any("cannot be calculated" in n for n in dl.caveats)
    assert not any("both the out-of-cycle" in n for n in dl.notes)
