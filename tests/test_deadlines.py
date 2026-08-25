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
    Deadline,
    PreRegimeError,
    annotate_calendar_risk,
    annotate_missing_flag,
    apply_item4,
    compute_due,
)


@pytest.fixture(scope="module")
def cal():
    return load_calendar()


def due_for(lines, cal):
    """compute_due plus the passes report.py runs after it. The missing-flag
    caveat is written against the FINAL deadline, so a test that calls
    compute_due alone sees the deadline before apply_item4 has had its say."""
    if isinstance(lines, ContribLine):
        lines = [lines]
    pairs = [(l, compute_due(l, cal)) for l in lines]
    apply_item4(pairs)
    annotate_missing_flag(pairs)
    return pairs


def test_contrib_line_keeps_the_pre_matched_amount_positional_signature():
    remitted = date(2026, 7, 14)
    received = date(2026, 7, 15)
    next_payday = date(2026, 7, 23)
    line = ContribLine(
        "E-POSITIONAL",
        date(2026, 7, 9),
        Decimal("100.00"),
        remitted,
        Decimal("60.00"),
        received,
        True,
        False,
        next_payday,
        False,
        7,
        "duplicate note",
    )
    assert line.remitted == remitted
    assert line.remitted_amount == Decimal("60.00")
    assert line.received == received
    assert line.first_to_fund is True
    assert line.next_standard_qe_day == next_payday
    assert line.row == 7
    assert line.duplicate_note == "duplicate note"
    assert line.matched_amount is None


def line(**kwargs) -> ContribLine:
    base = dict(
        employee_id="E1",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("600.00"),
        # Deadline-only tests that expect item 4 alignment supply the legal
        # fact the rule needs: an eligible fund receipt associated with the
        # earlier QE day. Tests for missing evidence override this to None.
        received=date(2026, 7, 15),
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


def test_out_of_cycle_without_next_payday_is_rejected(cal):
    """F2026L00784 s 5 requires the subsequent standard QE payment; there
    is no lawful fallback item 2 period when it does not exist."""
    with pytest.raises(ValueError) as exc:
        compute_due(line(out_of_cycle=True), cal)

    message = str(exc.value)
    assert "F2026L00784 s 5" in message
    assert "subsequent non-out-of-cycle QE payment" in message
    assert "termination payment" in message


def test_next_payday_without_the_flag_names_the_item_2_deadline(cal):
    """A row that supplies the next payday but leaves out_of_cycle blank was
    given the strict 7-business-day deadline with nothing said about it."""
    _, dl = due_for(
        line(qe_day=date(2026, 7, 15), next_standard_qe_day=date(2026, 7, 23)), cal
    )[0]
    assert dl.pathway == USUAL_7BD
    assert dl.due == cal.add_business_days(date(2026, 7, 15), 7)
    caveat = [c for c in dl.caveats if "out_of_cycle=yes" in c]
    assert caveat, dl.caveats
    assert cal.add_business_days(date(2026, 7, 23), 7).isoformat() in caveat[0]


def test_missing_flag_does_not_invent_an_absent_next_qe_day():
    """An inconsistent caller cannot produce a caveat naming a made-up date."""
    contribution = line(next_standard_qe_day=None)
    deadline = Deadline(
        due=date(2026, 7, 20),
        pathway=USUAL_7BD,
        item2_due=date(2026, 7, 30),
    )

    annotate_missing_flag([(contribution, deadline)])

    assert deadline.caveats == []


def test_next_payday_caveat_names_the_deadline_the_row_actually_got(cal):
    """A first-to-fund row takes the 20-business-day period, so the caveat
    must not claim the strict 7-business-day deadline was used, and must not
    name an item 2 date four business days EARLIER than the row's own."""
    _, dl = due_for(
        line(
            qe_day=date(2026, 7, 10),
            first_to_fund=True,
            next_standard_qe_day=date(2026, 7, 23),
        ),
        cal,
    )[0]
    assert dl.pathway == EXTENDED_20BD
    assert dl.due == date(2026, 8, 10)
    caveat = [c for c in dl.caveats if "out_of_cycle=yes" in c]
    assert caveat, dl.caveats
    assert "20-business-day deadline 2026-08-10 was used" in caveat[0]
    assert "would not change it" in caveat[0]
    assert "strict 7-business-day" not in caveat[0]
    # The item 2 date is named as the thing that is NOT later, never as the
    # deadline the row would get.
    assert "the item 2 deadline is 2026-08-04, which is no later" in caveat[0]


def test_next_payday_caveat_still_fires_where_item_2_would_win(cal):
    """The other side of the same branch: item 2 beats the row's own period,
    so setting the flag really would move the deadline."""
    _, dl = due_for(
        line(qe_day=date(2026, 7, 10), next_standard_qe_day=date(2026, 7, 23)), cal
    )[0]
    assert dl.pathway == USUAL_7BD
    assert dl.due == date(2026, 7, 21)
    caveat = [c for c in dl.caveats if "out_of_cycle=yes" in c]
    assert caveat, dl.caveats
    assert "strict 7-business-day deadline 2026-07-21 was used" in caveat[0]
    assert "the deadline becomes 2026-08-04" in caveat[0]


def test_the_missing_flag_caveat_reads_the_deadline_item_4_left(cal):
    """Written inside compute_due, this caveat named the deadline the row had
    BEFORE apply_item4 moved it. An item-4-aligned row then carried a caveat
    naming a pathway it did not have, a deadline earlier than its own due_date
    column, and advice that moved nothing: setting out_of_cycle=yes on that
    row leaves it item 4 aligned at the same date."""
    first = line(
        employee_id="EMP300",
        qe_day=date(2026, 7, 9),
        remitted=date(2026, 8, 6),
        first_to_fund=True,
        row=2,
    )
    later = line(
        employee_id="EMP300",
        qe_day=date(2026, 7, 15),
        remitted=date(2026, 8, 6),
        next_standard_qe_day=date(2026, 7, 23),
        row=3,
    )
    _, dl = due_for([first, later], cal)[1]
    assert dl.pathway == ITEM4_ALIGNED
    caveat = [c for c in dl.caveats if "out_of_cycle=yes" in c]
    assert caveat, dl.caveats
    # The deadline named is the one the row ends up with, not its own period end.
    assert dl.due.isoformat() in caveat[0]
    assert dl.own_due is not None and dl.own_due.isoformat() not in caveat[0]
    assert "item 4 aligned" in caveat[0]
    # And the advice is honest: the flag would not move this deadline.
    assert "would not change it" in caveat[0]


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


def test_unconfirmed_dates_are_flagged_but_do_not_extend_the_deadline(cal):
    l = line(qe_day=date(2027, 9, 21))
    pairs = [(l, compute_due(l, cal))]
    annotate_calendar_risk(pairs, cal)
    assert pairs[0][1].due == date(2027, 9, 30)
    assert any("unconfirmed holiday" in n for n in pairs[0][1].caveats)
    assert any("not used to extend" in n for n in pairs[0][1].caveats)


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
    assert any("beyond the calendar's coverage" in n for n in pairs[0][1].caveats)


def test_a_nil_payday_does_not_seed_an_item_4_alignment(cal):
    """s 18C(2) item 4 aligns to an earlier ELIGIBLE CONTRIBUTION. A payday
    carrying 0.00 SG is not one, so its extended window must not stretch a
    later real payday's deadline."""
    nil = line(
        employee_id="EMP200",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("0.00"),
        remitted=date(2026, 7, 15),
        first_to_fund=True,
        row=2,
    )
    real = line(
        employee_id="EMP200",
        qe_day=date(2026, 7, 23),
        sg_amount=Decimal("1000.00"),
        remitted=date(2026, 8, 5),
        received=date(2026, 8, 6),
        row=3,
    )
    pairs = [(l, compute_due(l, cal)) for l in (nil, real)]
    assert pairs[0][1].due == date(2026, 8, 7)  # the nil row's own 20bd window
    apply_item4(pairs)
    assert pairs[1][1].due == date(2026, 8, 4)  # its own period, not inherited
    assert pairs[1][1].pathway == USUAL_7BD


def test_a_real_payday_still_seeds_an_item_4_alignment(cal):
    """The other side of the same guard: only the amount changes."""
    paid = line(
        employee_id="EMP200",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("0.01"),
        first_to_fund=True,
        row=2,
    )
    real = line(
        employee_id="EMP200", qe_day=date(2026, 7, 23), sg_amount=Decimal("1000.00"), row=3
    )
    pairs = [(l, compute_due(l, cal)) for l in (paid, real)]
    apply_item4(pairs)
    assert pairs[1][1].due == date(2026, 8, 7)
    assert pairs[1][1].pathway == ITEM4_ALIGNED


def test_item_1_does_not_hide_an_invalid_out_of_cycle_claim(cal):
    """A later item 1 deadline cannot manufacture the missing statutory
    fact needed to say item 2 applies."""
    with pytest.raises(ValueError, match="next_standard_qe_day"):
        compute_due(line(first_to_fund=True, out_of_cycle=True), cal)
