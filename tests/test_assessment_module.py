"""Characterisation for the assessment module's public ownership seam."""

from datetime import date
from decimal import Decimal
from importlib import import_module

import pytest

from paydaysuper.calendar import load_calendar
from paydaysuper.deadlines import USUAL_7BD, ContribLine, Deadline
from paydaysuper.rates import load_gic


AS_AT = date(2026, 9, 1)
assessment_module = import_module("paydaysuper.assess")
report_module = import_module("paydaysuper.report")


def test_report_route_preserves_the_representative_result_object() -> None:
    line = ContribLine(
        employee_id="E1",
        qe_day=date(2026, 8, 6),
        sg_amount=Decimal("100"),
        received=date(2026, 8, 10),
        row=7,
    )

    result = report_module.assess([line], load_calendar(), load_gic(), AS_AT)[0]

    assert result == assessment_module.Result(
        line=line,
        deadline=Deadline(due=date(2026, 8, 17), pathway=USUAL_7BD),
        verdict=assessment_module.ON_TIME,
        # The receipt falls on or before the as-at date, so this run could
        # use it. The remittance-only exit gate reads exactly this flag.
        receipt_established=True,
    )
    assert result.line is line
    assert result.notes == []
    assert result.caveats == []


def test_report_route_preserves_aggregate_validation_order() -> None:
    lines = [
        ContribLine(
            employee_id="E2",
            qe_day=date(2026, 8, 6),
            sg_amount=Decimal("-1"),
            remitted=date(2026, 8, 20),
            received=date(2026, 8, 15),
            row=2,
        ),
        ContribLine(
            employee_id="E3",
            qe_day=date(2026, 8, 7),
            sg_amount=Decimal("-2"),
            remitted=date(2026, 8, 22),
            received=date(2026, 8, 21),
            row=3,
        ),
    ]
    expected = (
        "row 2: sg_amount cannot be negative; "
        "row 2: fund receipt date 2026-08-15 is before the remittance date "
        "2026-08-20, which cannot happen; "
        "row 3: sg_amount cannot be negative; "
        "row 3: fund receipt date 2026-08-21 is before the remittance date "
        "2026-08-22, which cannot happen"
    )

    with pytest.raises(ValueError) as raised:
        report_module.assess(lines, load_calendar(), load_gic(), AS_AT)

    assert str(raised.value) == expected


def test_assessment_module_owns_the_historical_report_route() -> None:
    assert assessment_module.assess is report_module.assess
