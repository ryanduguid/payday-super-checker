import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from paydaysuper.calendar import load_calendar
from paydaysuper.cli import EXIT_ERROR, EXIT_LATE_FOUND, main
from paydaysuper.csv_io import load_mapping, parse_rows
from paydaysuper.rates import load_gic
from paydaysuper.report import assess

FIXTURE = Path(__file__).parent / "fixtures" / "sample_payrun.csv"
AS_AT = date(2026, 8, 10)


def run_fixture():
    lines = parse_rows(FIXTURE, load_mapping(None))
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


def test_late_line_has_exposure_figures():
    r = by_employee(run_fixture(), "EMP002", date(2026, 7, 9))
    assert r.deadline.due == date(2026, 7, 20)
    assert r.days_late == 15
    assert r.nec > Decimal("0")
    assert r.sgc_low == r.line.sg_amount + r.nec
    assert r.sgc_high > r.sgc_low


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
    assert len(rows) == 10
    assert {r["verdict"] for r in rows} == {
        "ON_TIME",
        "LATE",
        "AT_RISK",
        "UNKNOWN",
        "SKIPPED",
    }

    printed = capsys.readouterr().out
    assert "payday-super-checker" in printed
    assert "Educational tool" in printed
    assert "no liability" not in printed


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
