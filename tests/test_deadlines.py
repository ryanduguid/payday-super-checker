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
    assert any("fallback" in n for n in dl.notes)


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


def test_provisional_dates_are_flagged_in_notes(cal):
    dl = compute_due(line(qe_day=date(2026, 9, 21)), cal)
    assert any("provisional" in n for n in dl.notes)
