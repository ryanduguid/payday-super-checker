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
from paydaysuper.report import _rounded_figures, assess, console_summary
from paydaysuper.sgc import notional_earnings

from conftest import SAMPLE as FIXTURE
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
    assert by_employee(results, "EMP004", date(2026, 7, 9)).verdict == "UNPAID"
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
        "UNPAID",
        "SKIPPED",
    }

    # The trailing note keeps the table's width so parsers do not choke.
    note = rows[-1]
    assert note["employee_id"] == "NOTE"
    assert "2026-08-02" in note["notes"]
    assert "not advice" in note["notes"]
    assert "payday-super-checker 0.1.0" in note["notes"]
    assert "sample_payrun.csv" in note["notes"]
    assert "GIC table covers" in note["notes"]

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
    body = text.split("Lines with exposure")[1]
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
    # Lateness and interest are both measured to the as-at date, because no
    # fund receipt is known and the statutory test is receipt.
    assert r.days_late == (AS_AT - r.deadline.due).days
    assert r.lateness_basis.startswith("as-at date")
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
    assert any("12-month pre-payment window" in w for w in r.warnings)


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
    # The payday is unfunded, so interest runs to the as-at date rather than
    # stopping at a receipt that cannot be applied to it.
    assert r.nec > Decimal("0")
    assert r.days_late == (date(2027, 8, 1) - r.deadline.due).days
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
    # The caveat follows the paydays in the file, not the day of the run.
    text = console_summary(results, date(2027, 9, 1), "report.csv", "2026-08-02", rates)
    assert "$270,830 for 2026-27" in text
    later = ContribLine(
        employee_id="E9",
        qe_day=date(2027, 9, 1),
        sg_amount=Decimal("100.00"),
        row=2,
    )
    later_results = assess([later], load_calendar(), load_gic(), date(2027, 10, 1))
    text_2027 = console_summary(
        later_results, date(2027, 10, 1), "report.csv", "2026-08-02", rates
    )
    assert "$280,000 for 2027-28" in text_2027


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


def test_unpaid_overdue_line_reports_exposure_and_exit_code(tmp_path, capsys):
    """The largest exposure the tool can see is a payday with nothing
    recorded and the deadline already passed. It must not be silent."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("800.00"),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.verdict == "UNPAID"
    assert r.final_shortfall == Decimal("800.00")
    assert r.nec > Decimal("0")
    assert r.sgc_high > Decimal("800.00")
    assert any("deadline passed" in w for w in r.caveats)

    path = tmp_path / "pay.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "E9,2026-07-09,800.00,,,no,no,,no\n",
        encoding="utf-8",
    )
    assert main([str(path), "-o", str(tmp_path / "r.csv"), "--as-at", "2026-08-10"]) == 2


def test_not_yet_due_line_with_no_dates_stays_unknown():
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 8, 6),
        sg_amount=Decimal("800.00"),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.verdict == "UNKNOWN"
    assert r.sgc_high is None


def test_calendar_caveats_describe_the_aligned_deadline():
    """A deadline moved by item 4 is the one the user acts on, so the
    horizon caveat must describe that date, not the line's own period end."""
    cal = load_calendar()
    inside = ContribLine(
        employee_id="E9",
        qe_day=date(2028, 12, 8),
        sg_amount=Decimal("100.00"),
        first_to_fund=True,
        row=2,
    )
    later = ContribLine(
        employee_id="E9",
        qe_day=date(2028, 12, 11),
        sg_amount=Decimal("100.00"),
        row=3,
    )
    results = assess([inside, later], cal, load_gic(), date(2029, 3, 1))
    aligned = results[1]
    assert aligned.deadline.pathway == "ITEM4_ALIGNED"
    horizon = [c for c in aligned.caveats if "verified horizon" in c]
    assert horizon and aligned.deadline.due.isoformat() in horizon[0]


def test_case_variant_employee_ids_are_flagged_not_merged():
    cal = load_calendar()
    rows = [
        ContribLine(
            employee_id="EMP001",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("100.00"),
            first_to_fund=True,
            row=2,
        ),
        ContribLine(
            employee_id="emp001",
            qe_day=date(2026, 7, 23),
            sg_amount=Decimal("100.00"),
            received=date(2026, 8, 6),
            row=3,
        ),
    ]
    results = assess(rows, cal, load_gic(), AS_AT)
    assert results[1].deadline.due == date(2026, 8, 4)  # not aligned
    assert any("capitalisation" in c for c in results[1].caveats)


def test_item4_inherited_from_an_unrecorded_payday_is_flagged():
    cal = load_calendar()
    rows = [
        ContribLine(
            employee_id="E9",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("100.00"),
            first_to_fund=True,
            row=2,
        ),
        ContribLine(
            employee_id="E9",
            qe_day=date(2026, 7, 23),
            sg_amount=Decimal("100.00"),
            received=date(2026, 8, 6),
            row=3,
        ),
    ]
    results = assess(rows, cal, load_gic(), AS_AT)
    assert results[1].verdict == "ON_TIME"
    assert any("no payment is recorded" in c for c in results[1].caveats)


def test_missed_new_starter_flag_is_suggested_on_late_lines():
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("100.00"),
        received=date(2026, 8, 5),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.verdict == "LATE"
    assert any("first_contribution_to_fund=yes" in c for c in r.caveats)


def test_prepayment_window_is_leap_safe():
    """s 18C(1)(c)(ii) runs 12 calendar months, not 365 days, so a receipt
    on the first day of the window counts even across a leap year."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2029, 3, 1),
        sg_amount=Decimal("100.00"),
        received=date(2028, 2, 29),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), date(2029, 4, 1))[0]
    assert r.verdict == "ON_TIME"


def test_identical_rows_are_flagged_as_duplicates():
    rows = [
        ContribLine(
            employee_id="E9",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("100.00"),
            received=date(2026, 7, 15),
            row=n,
        )
        for n in (2, 3)
    ]
    results = assess(rows, load_calendar(), load_gic(), AS_AT)
    assert all(any("counted 2 times" in c for c in r.caveats) for r in results)


def test_console_shows_totals_and_caveats():
    text = console_summary(run_fixture(), AS_AT, "report.csv", "2026-08-02", load_rates())
    assert "Total across" in text
    assert "estimated SG charge $" in text
    assert "note: " in text  # caveats reach the console, not just the CSV


def test_report_columns_add_up():
    """Each figure is rounded once, so a row's parts sum to its totals."""
    for r in run_fixture():
        if r.verdict not in ("LATE", "UNPAID"):
            continue
        figures = _rounded_figures(r)
        assert figures["shortfall"] + figures["nec"] + figures["up_low"] == figures["low"]
        assert figures["shortfall"] + figures["nec"] + figures["up_high"] == figures["high"]


def test_employee_id_that_looks_like_a_formula_is_neutralised(tmp_path):
    path = tmp_path / "pay.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        '"=cmd|\'/c calc\'!A1",2026-07-09,100.00,,,no,no,,no\n',
        encoding="utf-8",
    )
    out = tmp_path / "r.csv"
    main([str(path), "-o", str(out), "--as-at", "2026-08-10"])
    written = out.read_text(encoding="utf-8")
    assert "'=cmd" in written
    assert ",=cmd" not in written


def test_sentinel_high_date_is_refused_cleanly(tmp_path, capsys):
    path = tmp_path / "pay.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "E9,2026-07-09,100.00,,9999-12-31,no,no,,no\n",
        encoding="utf-8",
    )
    assert main([str(path), "-o", str(tmp_path / "r.csv")]) == EXIT_ERROR
    assert "not a real date" in capsys.readouterr().err
