import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from paydaysuper.calendar import load_calendar
from paydaysuper.cli import EXIT_ERROR, EXIT_LATE_FOUND, main
from paydaysuper.csv_io import load_mapping, parse_rows
from paydaysuper.deadlines import ContribLine
from paydaysuper.rates import load_gic, load_rates
from paydaysuper.report import assess, console_summary
from paydaysuper.sgc import notional_earnings

FIXTURE = Path(__file__).parent / "fixtures" / "sample_payrun.csv"
AS_AT = date(2026, 8, 10)


def run_fixture():
    lines = parse_rows(FIXTURE, *load_mapping(None))
    return assess(lines, load_calendar(), load_gic(), AS_AT)


def by_employee(results, employee_id, qe_day):
    return next(
        r for r in results if r.line.employee_id == employee_id and r.line.qe_day == qe_day
    )


def test_verdicts_across_the_fixture():
    results = run_fixture()
    assert by_employee(results, "EMP001", date(2026, 7, 9)).verdict == "ON_TIME"
    assert by_employee(results, "EMP002", date(2026, 7, 9)).verdict == "LATE"
    assert by_employee(results, "EMP003", date(2026, 7, 9)).verdict == "AT_RISK"
    assert by_employee(results, "EMP004", date(2026, 7, 9)).verdict == "UNKNOWN"
    assert by_employee(results, "EMP005", date(2026, 7, 9)).verdict == "ON_TIME"
    assert by_employee(results, "EMP006", date(2026, 7, 15)).verdict == "ON_TIME"
    assert by_employee(results, "EMP007", date(2026, 7, 9)).verdict == "SKIPPED"


def test_at_risk_line_carries_the_receipt_caveat():
    r = by_employee(run_fixture(), "EMP003", date(2026, 7, 9))
    assert any("receipt by the fund" in w for w in r.warnings)


def test_late_but_received_line_has_no_shortfall():
    """s 18D: a late contribution received before any assessment clears the
    final shortfall, leaving notional earnings and the uplift on them."""
    r = by_employee(run_fixture(), "EMP002", date(2026, 7, 9))
    assert r.deadline.due == date(2026, 7, 20)
    assert r.days_late == 15
    assert r.final_shortfall == Decimal("0")
    assert r.base_shortfall == Decimal("540.00")
    assert r.nec > Decimal("0")
    assert r.sgc_low == r.nec                      # uplift 0%
    assert r.sgc_high == r.nec * Decimal("1.6")    # uplift 60%
    assert any("s 18D" in w for w in r.warnings)


def test_assessment_before_receipt_keeps_the_shortfall():
    """The offset needs receipt to beat the assessment. Assess earlier and
    the whole SG amount stays in the charge."""
    lines = parse_rows(FIXTURE, *load_mapping(None))
    results = assess(
        lines, load_calendar(), load_gic(), AS_AT, assessment_date=date(2026, 7, 25)
    )
    r = by_employee(results, "EMP002", date(2026, 7, 9))
    assert r.final_shortfall == Decimal("540.00")
    assert r.sgc_low == Decimal("540.00") + r.nec


def test_notional_earnings_run_to_the_receipt_date():
    """Accrual covers [due + 1 day, receipt] inclusive (s 19A)."""
    r = by_employee(run_fixture(), "EMP002", date(2026, 7, 9))
    expected = notional_earnings(
        Decimal("540.00"), date(2026, 7, 20), date(2026, 8, 4), load_gic()
    )
    assert r.nec == expected


def test_unpaid_line_keeps_the_full_shortfall():
    lines = parse_rows(FIXTURE, *load_mapping(None))
    late_unpaid = [
        line for line in lines if line.employee_id == "EMP002" and line.received
    ][0]
    late_unpaid.received = None
    late_unpaid.remitted = date(2026, 8, 4)
    results = assess(lines, load_calendar(), load_gic(), AS_AT)
    r = by_employee(results, "EMP002", date(2026, 7, 9))
    assert r.verdict == "LATE"
    assert r.final_shortfall == Decimal("540.00")
    assert any("still unpaid" in w for w in r.warnings)


def test_item4_extends_the_second_payday_for_a_new_starter():
    results = run_fixture()
    first = by_employee(results, "EMP005", date(2026, 7, 9))
    second = by_employee(results, "EMP005", date(2026, 7, 23))
    assert first.deadline.due == date(2026, 8, 7)
    assert second.deadline.due == date(2026, 8, 7)  # inherited, not 4 Aug
    assert second.verdict == "ON_TIME"


def test_same_dates_without_the_extension_are_late():
    """EMP001's second payday mirrors EMP005's but has no extended window."""
    r = by_employee(run_fixture(), "EMP001", date(2026, 7, 23))
    assert r.deadline.due == date(2026, 8, 4)
    assert r.verdict == "LATE"


def test_cli_writes_report_and_flags_late(tmp_path, capsys):
    out = tmp_path / "report.csv"
    code = main([str(FIXTURE), "-o", str(out), "--as-at", "2026-08-10"])
    assert code == EXIT_LATE_FOUND

    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    data = [r for r in rows if r["employee_id"] != "NOTE"]
    assert len(data) == 10
    assert {r["verdict"] for r in data} == {
        "ON_TIME",
        "LATE",
        "AT_RISK",
        "UNKNOWN",
        "SKIPPED",
    }

    # The trailing note keeps the table's width so parsers do not choke.
    note = rows[-1]
    assert note["employee_id"] == "NOTE"
    assert "2026-08-02" in note["warnings"]
    assert "not advice" in note["warnings"]

    late = next(r for r in data if r["employee_id"] == "EMP002")
    assert late["due_date"] == "2026-07-20"
    assert late["pathway"] == "USUAL_7BD"
    assert late["days_late"] == "15"
    assert late["sg_amount"] == "540.00"
    assert late["final_shortfall"] == "0.00"
    assert late["uplift_best_case"] == "0.00"
    assert Decimal(late["sgc_estimate_high"]) > Decimal(late["sgc_estimate_low"])

    skipped = next(r for r in data if r["employee_id"] == "EMP007")
    assert skipped["verdict"] == "SKIPPED"
    assert skipped["due_date"] == ""

    printed = capsys.readouterr().out
    assert "payday-super-checker" in printed
    assert "Educational tool" in printed
    assert "no liability" not in printed


def test_console_summary_carries_the_legal_caveats():
    text = console_summary(run_fixture(), AS_AT, "report.csv", "2026-08-02", load_rates())
    for phrase in (
        "Maximum contributions base ($270,830 for 2026-27",
        "Choice loading, the late payment penalty",
        "PCG 2026/1",
        "still drafts",
        "receipt by the fund",
        "s 18D",
        "Fund deeds, enterprise agreements",
    ):
        assert phrase in text, phrase
    assert "lowers ATO review risk" in text
    assert "no liability" not in text


def test_console_summary_ranks_by_exposure():
    """Largest estimated exposure first, as the heading claims."""
    text = console_summary(run_fixture(), AS_AT, "report.csv", "2026-08-02", load_rates())
    body = text.split("Late lines")[1]
    assert body.index("EMP002") < body.index("EMP001")


def test_cli_refuses_to_overwrite_the_input(tmp_path, capsys):
    target = tmp_path / "pay.csv"
    target.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    assert main([str(target), "-o", str(target)]) == EXIT_ERROR
    assert "overwrite the input" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8").startswith("employee_id,payment_date")


def test_cli_reports_missing_file(tmp_path, capsys):
    code = main([str(tmp_path / "nope.csv")])
    assert code == EXIT_ERROR
    assert "error:" in capsys.readouterr().err


def test_cli_rejects_pre_regime_paydays(tmp_path, capsys):
    path = tmp_path / "old.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "E1,2026-06-30,600.00,,,no,no,,no\n",
        encoding="utf-8",
    )
    assert main([str(path), "-o", str(tmp_path / "r.csv")]) == EXIT_ERROR
    assert "old quarterly SG law" in capsys.readouterr().err


def test_late_remittance_without_a_receipt_date_is_late():
    """The LATE branch of the remittance-only path: no receipt date, and
    the money left after the deadline."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("300.00"),
        remitted=date(2026, 8, 1),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.verdict == "LATE"
    assert r.days_late == 12                      # measured to the remittance date
    assert r.final_shortfall == Decimal("300.00")  # no receipt, so no s 18D offset
    assert any("still unpaid" in w for w in r.warnings)


def test_prepayment_inside_the_twelve_month_window_is_on_time():
    """s 18C(1)(c)(ii): received in the 12 months before the QE day."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("300.00"),
        received=date(2026, 5, 1),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.verdict == "ON_TIME"
    assert any("pre-payment" in w for w in r.warnings)


def test_payment_older_than_twelve_months_cannot_offset():
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2027, 7, 9),
        sg_amount=Decimal("300.00"),
        received=date(2026, 7, 1),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), date(2027, 8, 1))[0]
    assert r.verdict == "LATE"
    assert any("more than 12 months" in w for w in r.warnings)


def test_receipt_before_remittance_is_rejected():
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("300.00"),
        remitted=date(2026, 7, 20),
        received=date(2026, 7, 15),
        row=2,
    )
    with pytest.raises(ValueError, match="cannot happen"):
        assess([line], load_calendar(), load_gic(), AS_AT)


def test_receipt_after_the_as_at_date_still_accrues_to_receipt():
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("300.00"),
        received=date(2026, 8, 20),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    expected = notional_earnings(
        Decimal("300.00"), date(2026, 7, 20), date(2026, 8, 20), load_gic()
    )
    assert r.nec == expected
    assert any("after the as-at date" in w for w in r.warnings)


def test_stale_prepayment_keeps_the_full_shortfall():
    """s 18D offsets a payment made in the late period. A receipt from
    before the deadline is not one, so the shortfall stands."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2027, 7, 9),
        sg_amount=Decimal("300.00"),
        received=date(2026, 7, 1),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), date(2027, 8, 1))[0]
    assert r.verdict == "LATE"
    assert r.final_shortfall == Decimal("300.00")
    assert r.offset_s18d is False
    assert r.days_late == 0
    assert r.sgc_low >= Decimal("300.00")
    assert not any("s 18D" in w for w in r.warnings)


def test_notional_earnings_stop_before_an_assessment():
    """Once assessed, interest on the charge is GIC on the assessment, which
    this tool does not model, so accrual stops the day before."""
    lines = parse_rows(FIXTURE, *load_mapping(None))
    results = assess(
        lines, load_calendar(), load_gic(), AS_AT, assessment_date=date(2026, 7, 25)
    )
    r = by_employee(results, "EMP002", date(2026, 7, 9))
    expected = notional_earnings(
        Decimal("540.00"), date(2026, 7, 20), date(2026, 7, 24), load_gic()
    )
    assert r.nec == expected
    assert any("day before the assessment" in w for w in r.warnings)


def test_zero_amount_late_line_does_not_claim_a_receipt():
    line = ContribLine(
        employee_id="E0",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("0.00"),
        remitted=date(2026, 8, 1),
        row=2,
    )
    results = assess([line], load_calendar(), load_gic(), AS_AT)
    text = console_summary(results, AS_AT, "report.csv", "2026-08-02", load_rates())
    assert "shortfall $0.00" in text
    assert "received, so the shortfall is nil" not in text


def test_report_records_the_assessment_assumption(tmp_path):
    out = tmp_path / "report.csv"
    main([str(FIXTURE), "-o", str(out), "--as-at", "2026-08-10",
          "--assessment-date", "2026-08-05"])
    text = out.read_text(encoding="utf-8")
    assert "Assessment date 2026-08-05" in text

    out2 = tmp_path / "report2.csv"
    main([str(FIXTURE), "-o", str(out2), "--as-at", "2026-08-10"])
    assert "No assessment date given" in out2.read_text(encoding="utf-8")


def test_mcb_caveat_follows_the_as_at_financial_year():
    rates = {
        "financial_years": {
            "2026-27": {"max_contributions_base": "270830"},
            "2027-28": {"max_contributions_base": "280000"},
        }
    }
    results = run_fixture()
    text = console_summary(results, date(2027, 9, 1), "report.csv", "2026-08-02", rates)
    assert "$280,000 for 2027-28" in text
    text_2026 = console_summary(results, AS_AT, "report.csv", "2026-08-02", rates)
    assert "$270,830 for 2026-27" in text_2026


def test_all_date_problems_are_reported_at_once():
    bad = [
        ContribLine(
            employee_id=f"E{n}",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("100.00"),
            remitted=date(2026, 7, 20),
            received=date(2026, 7, 15),
            row=n,
        )
        for n in (2, 3)
    ]
    with pytest.raises(ValueError) as exc:
        assess(bad, load_calendar(), load_gic(), AS_AT)
    assert "row 2" in str(exc.value) and "row 3" in str(exc.value)
