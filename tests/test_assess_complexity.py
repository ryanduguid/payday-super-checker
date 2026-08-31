import ast
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from paydaysuper.assess import (
    LATE,
    UNKNOWN,
    Result,
    _apply_exposure,
    _AssessmentFacts,
    _assess_received,
    _assess_without_receipt,
)
from paydaysuper.calendar import load_calendar
from paydaysuper.deadlines import USUAL_7BD, ContribLine, Deadline
from paydaysuper.rates import load_gic


def test_assess_line_only_orchestrates_decision_phases() -> None:
    tree = ast.parse(Path("paydaysuper/assess.py").read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_assess_line"
    )
    decisions = sum(
        isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.BoolOp, ast.IfExp))
        for node in ast.walk(function)
    )

    assert function.end_lineno is not None
    assert function.end_lineno - function.lineno < 200
    assert decisions <= 20


def _line() -> ContribLine:
    return ContribLine("E1", date(2027, 7, 9), Decimal("300"), row=2)


def _facts(**changes: object) -> _AssessmentFacts:
    defaults = _AssessmentFacts(
        settled=date(2026, 7, 10),
        remitted=None,
        credit=Decimal("0"),
        operational_unremitted=Decimal("300"),
        fully_remitted=False,
        receipt_credit=Decimal("100"),
        receipt_covers_all=False,
        past_horizon=False,
        horizon_unknown="calendar unknown",
        horizon_figures="calendar figures",
        possible_item4_due=None,
        item4_uncertain=False,
        item4_unknown="item 4 unknown",
        item4_partial_unknown="item 4 partial",
        horizon_partial_unknown="calendar partial",
    )
    return replace(defaults, **changes)


def test_received_phase_keeps_partial_prepayment_boundaries() -> None:
    line = _line()
    future_due = Deadline(date(2027, 7, 20), USUAL_7BD)
    result = Result(line, future_due, UNKNOWN)

    credit, stale, finished = _assess_received(
        result, line, future_due, date(2027, 7, 12), _facts()
    )

    assert (credit, stale, finished) == (Decimal("100"), False, True)
    assert "deadline has not passed" in result.caveats[-1]

    past_due = Deadline(date(2027, 7, 10), USUAL_7BD)
    result = Result(line, past_due, UNKNOWN)
    credit, stale, finished = _assess_received(
        result,
        line,
        past_due,
        date(2027, 7, 12),
        _facts(
            past_horizon=True,
            possible_item4_due=date(2027, 7, 20),
            item4_uncertain=True,
        ),
    )

    assert (credit, stale, finished) == (Decimal("100"), False, True)
    assert "calendar's coverage" in result.caveats[-2]
    assert result.caveats[-1] == "item 4 unknown"

    result = Result(line, past_due, UNKNOWN)
    _assess_received(
        result,
        line,
        past_due,
        date(2027, 7, 12),
        _facts(
            settled=date(2026, 7, 1),
            possible_item4_due=date(2027, 7, 20),
            item4_uncertain=True,
        ),
    )
    assert result.caveats[-1] == "item 4 unknown"


def test_received_phase_keeps_stale_and_partial_receipt_outcomes() -> None:
    line = _line()
    past_due = Deadline(date(2027, 7, 10), USUAL_7BD)
    result = Result(line, past_due, UNKNOWN)

    credit, stale, finished = _assess_received(
        result,
        line,
        past_due,
        date(2027, 7, 12),
        _facts(
            settled=date(2026, 7, 1),
            past_horizon=True,
            possible_item4_due=date(2027, 7, 20),
            item4_uncertain=True,
        ),
    )

    assert (credit, stale, finished) == (Decimal("0"), True, True)
    assert "calendar's coverage" in result.caveats[-2]
    assert result.caveats[-1] == "item 4 unknown"

    line = ContribLine("E1", date(2027, 7, 9), Decimal("300"), row=2)
    due = Deadline(date(2027, 7, 20), USUAL_7BD)
    partial = _facts(settled=date(2027, 7, 15))
    overdue = Result(line, due, UNKNOWN)
    assert _assess_received(overdue, line, due, date(2027, 8, 1), partial)[2] is False
    assert overdue.verdict == "UNPAID"

    pending = Result(line, due, UNKNOWN)
    assert _assess_received(pending, line, due, date(2027, 7, 18), partial)[2] is True
    assert "deadline has not passed" in pending.caveats[-1]


def test_no_receipt_phase_keeps_item4_uncertainty() -> None:
    line = _line()
    due = Deadline(date(2027, 7, 10), USUAL_7BD)
    result = Result(line, due, UNKNOWN)
    facts = _facts(
        settled=None,
        remitted=date(2027, 7, 15),
        fully_remitted=True,
        possible_item4_due=date(2027, 7, 20),
        item4_uncertain=True,
    )

    assert _assess_without_receipt(result, line, due, date(2027, 7, 16), facts)
    assert result.horizon_verdicts == (LATE, "AT_RISK")
    assert result.caveats == ["item 4 unknown"]


def test_exposure_phase_keeps_horizon_and_new_starter_boundaries() -> None:
    line = _line()
    due = Deadline(date(2027, 7, 20), USUAL_7BD)
    result = Result(line, due, LATE)
    _apply_exposure(
        result,
        line,
        due,
        load_calendar(),
        load_gic(),
        date(2027, 8, 1),
        None,
        _facts(settled=None, receipt_credit=Decimal("0"), past_horizon=True),
        Decimal("0"),
        False,
    )
    assert result.days_late is None
    assert "calendar figures" in result.caveats

    late_receipt = date(2027, 8, 20)
    result = Result(line, due, LATE)
    _apply_exposure(
        result,
        line,
        due,
        load_calendar(),
        load_gic(),
        date(2027, 9, 1),
        None,
        _facts(
            settled=late_receipt,
            receipt_credit=Decimal("300"),
            receipt_covers_all=True,
        ),
        Decimal("0"),
        False,
    )
    assert not any("first_contribution_to_fund" in value for value in result.caveats)
