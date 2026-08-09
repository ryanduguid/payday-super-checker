import codecs
import csv
import json
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
    assert body.index("row 3") < body.index("row 9")


def test_console_summary_does_not_disclose_employee_identifiers():
    """Payroll identifiers belong in the private CSV report, not process logs."""
    results = run_fixture()
    exposed = next(
        result for result in results if result.verdict in {"LATE", "UNPAID"}
    )
    exposed.line.employee_id = "ava.lawson@example.test"

    text = console_summary(results, AS_AT, "report.csv", "2026-08-02", load_rates())

    assert "ava.lawson@example.test" not in text
    assert all(result.line.employee_id not in text for result in results)
    assert "row 3" in text

    # The case-variant caveat prints on exposed rows too, so it must carry
    # rows, not the ids it is about: an id that only ever differs from its
    # sibling by capitalisation is still a payroll identifier.
    variant_rows = [
        ContribLine(
            employee_id="Ava.Lawson@example.test",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("100.00"),
            row=2,
        ),
        ContribLine(
            employee_id="ava.lawson@example.test",
            qe_day=date(2026, 7, 23),
            sg_amount=Decimal("100.00"),
            received=date(2026, 8, 4),
            row=3,
        ),
    ]
    variant_results = assess(variant_rows, load_calendar(), load_gic(), AS_AT)
    assert variant_results[0].verdict == "UNPAID"  # its caveats are printed
    text = console_summary(
        variant_results, AS_AT, "report.csv", "2026-08-02", load_rates()
    )
    assert "capitalisation" in text
    assert "rows 2, 3" in text
    assert "ava.lawson" not in text.casefold()


def test_cli_refuses_to_overwrite_the_input(tmp_path, capsys):
    target = tmp_path / "pay.csv"
    target.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    assert main([str(target), "-o", str(target)]) == EXIT_ERROR
    assert "overwrite the input" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8").startswith("employee_id,payment_date")


def test_cli_replaces_an_output_symlink_without_touching_its_target(tmp_path):
    """A report must replace its chosen output link, never write through it."""
    output = tmp_path / "report.csv"
    protected_target = tmp_path / "protected.csv"
    protected_target.write_text("leave this file alone\n", encoding="utf-8")
    try:
        output.symlink_to(protected_target)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable in this test environment: {exc}")

    assert main([str(FIXTURE), "-o", str(output), "--as-at", "2026-08-10"]) == EXIT_LATE_FOUND

    assert not output.is_symlink()
    assert protected_target.read_text(encoding="utf-8") == "leave this file alone\n"
    assert "employee_id" in output.read_text(encoding="utf-8-sig")


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


def test_receipt_on_the_due_date_is_on_time():
    """s 18C(1) is satisfied by receipt BY the end of the period, so the due
    date itself is inside it. Both comparisons in the verdict ladder could be
    tightened to < with nothing in the suite noticing."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("300.00"),
        remitted=date(2026, 7, 17),
        received=date(2026, 7, 20),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.deadline.due == date(2026, 7, 20)
    assert r.verdict == "ON_TIME"
    assert r.days_late is None
    assert r.final_shortfall is None
    assert r.sgc_high is None


def test_remittance_on_the_due_date_with_no_receipt_is_at_risk():
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("300.00"),
        remitted=date(2026, 7, 20),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.deadline.due == date(2026, 7, 20)
    assert r.verdict == "AT_RISK"
    assert r.final_shortfall is None


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


def test_receipt_after_the_as_at_date_is_not_used_to_settle_the_report():
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("300.00"),
        received=date(2026, 8, 20),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    expected = notional_earnings(
        Decimal("300.00"), date(2026, 7, 20), AS_AT, load_gic()
    )
    assert r.verdict == "UNPAID"
    assert r.days_late == (AS_AT - r.deadline.due).days
    assert r.final_shortfall == Decimal("300.00")
    assert r.nec == expected
    assert any("ignored for this as-at report" in w for w in r.warnings)


def test_remittance_after_the_as_at_date_is_not_used_to_settle_the_report():
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("300.00"),
        remitted=date(2026, 8, 20),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]

    assert r.verdict == "UNPAID"
    assert r.days_late == (AS_AT - r.deadline.due).days
    assert r.final_shortfall == Decimal("300.00")
    assert r.nec == notional_earnings(
        Decimal("300.00"), date(2026, 7, 20), AS_AT, load_gic()
    )
    assert any(
        "remittance date 2026-08-20 is after the as-at date" in warning
        for warning in r.warnings
    )


def test_a_post_as_at_receipt_does_not_claim_no_receipt_was_supplied():
    """A row remitted in time whose only receipt date post-dates the as-at
    date used to carry both 'fund receipt date ... is ignored' and 'no
    fund-receipt date supplied', which contradict each other. The variant
    caveat says what is actually true as at the report date."""
    from paydaysuper.report import NO_RECEIPT_CAVEAT

    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("300.00"),
        remitted=date(2026, 7, 15),
        received=date(2026, 8, 20),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.verdict == "AT_RISK"
    assert NO_RECEIPT_CAVEAT not in r.caveats
    assert not any("no fund-receipt date supplied" in c for c in r.caveats)
    assert any(
        "the only fund-receipt date on record (2026-08-20) is after the as-at date"
        in c
        for c in r.caveats
    )
    # The variant is row-specific, so the console's at-risk block lists it
    # rather than filtering it out with the universal caveat.
    text = console_summary([r], AS_AT, "report.csv", "2026-08-02", load_rates())
    assert "the only fund-receipt date on record (2026-08-20)" in text


def test_a_plain_remitted_only_row_still_carries_the_named_constant():
    """The console's at-risk filter matches NO_RECEIPT_CAVEAT by exact text,
    so the append site must use the constant, not a re-typed literal."""
    from paydaysuper.report import NO_RECEIPT_CAVEAT

    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("300.00"),
        remitted=date(2026, 7, 15),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.verdict == "AT_RISK"
    assert NO_RECEIPT_CAVEAT in r.caveats


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


def test_zero_amount_late_line_does_not_claim_a_receipt(tmp_path, capsys):
    """A nil row has no exposure behind it whatever its dates say, so a late
    remittance date cannot make it LATE or drive the exit code."""
    line = ContribLine(
        employee_id="E0",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("0.00"),
        remitted=date(2026, 8, 1),
        row=2,
    )
    results = assess([line], load_calendar(), load_gic(), AS_AT)
    assert results[0].verdict == "UNKNOWN"
    assert results[0].final_shortfall is None
    assert any("records no SG amount" in c for c in results[0].caveats)

    text = console_summary(results, AS_AT, "report.csv", "2026-08-02", load_rates())
    assert "Lines with exposure" not in text
    assert "received, so the shortfall is nil" not in text

    path = tmp_path / "pay.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "E0,2026-07-09,0.00,2026-08-01,,no,no,,no\n",
        encoding="utf-8",
    )
    assert main([str(path), "-o", str(tmp_path / "r.csv"), "--as-at", "2026-08-10"]) == 0


def test_zero_amount_line_with_a_late_receipt_is_not_late():
    """The receipt branch of the ladder is guarded by the same one test."""
    line = ContribLine(
        employee_id="E0",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("0.00"),
        received=date(2026, 8, 1),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.verdict == "UNKNOWN"
    assert r.sgc_high is None


def test_overdue_nil_row_is_not_told_the_deadline_has_not_passed():
    """A nil row whose deadline has gone used to fall through to the
    not-yet-due branch and be told in writing that it had not."""
    line = ContribLine(
        employee_id="E0", qe_day=date(2026, 7, 9), sg_amount=Decimal("0.00"), row=2
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.verdict == "UNKNOWN"
    assert any("the deadline passed on 2026-07-20" in c for c in r.caveats)
    assert not any("the deadline has not" in c for c in r.caveats)


def test_nil_row_before_its_deadline_still_says_so():
    line = ContribLine(
        employee_id="E0", qe_day=date(2026, 8, 6), sg_amount=Decimal("0.00"), row=2
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.verdict == "UNKNOWN"
    assert any("records no SG amount" in c for c in r.caveats)
    assert not any("the deadline passed" in c for c in r.caveats)


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
    horizon = [c for c in aligned.caveats if "beyond the calendar's coverage" in c]
    assert horizon and aligned.deadline.due.isoformat() in horizon[0]


def _past_horizon_line(**kwargs) -> ContribLine:
    """A QE day whose 7-business-day deadline lands past 31 Dec 2028, where
    the bundled calendar records no holidays at all."""
    return ContribLine(
        employee_id="E9",
        qe_day=date(2029, 3, 1),
        sg_amount=Decimal("500.00"),
        row=2,
        **kwargs,
    )


def test_receipt_past_the_calendar_horizon_is_not_called_late():
    """The only genuinely unknowable side. The receipt is after the deadline
    this calendar computes, and a holiday the calendar does not hold could
    move that deadline past it."""
    cal = load_calendar()
    line = _past_horizon_line(received=date(2029, 3, 13))
    r = assess([line], cal, load_gic(), date(2029, 4, 1))[0]
    assert r.deadline.due == date(2029, 3, 12)
    assert r.deadline.due > cal.coverage_until
    assert r.verdict == "UNKNOWN"
    assert r.horizon_verdicts == ("LATE", "ON_TIME")
    assert r.final_shortfall is None
    assert r.sgc_high is None
    assert any("left unassessed" in c for c in r.caveats)


def test_receipt_before_a_past_horizon_deadline_is_on_time():
    """A missing holiday can only push the real deadline LATER, so a receipt
    on or before the computed deadline is on time under every possible
    holiday set. Forcing UNKNOWN there hid a provable answer."""
    line = _past_horizon_line(received=date(2029, 3, 2))
    r = assess([line], load_calendar(), load_gic(), date(2029, 4, 1))[0]
    assert r.verdict == "ON_TIME"
    assert r.horizon_verdicts is None


def test_remittance_before_a_past_horizon_deadline_is_at_risk():
    line = _past_horizon_line(remitted=date(2029, 3, 2))
    r = assess([line], load_calendar(), load_gic(), date(2029, 4, 1))[0]
    assert r.verdict == "AT_RISK"
    assert r.horizon_verdicts is None


def test_receipt_on_a_past_horizon_deadline_is_on_time():
    """The boundary itself. The deadline is 2029-03-12, so a receipt that
    day is on time however many holidays the calendar is missing."""
    line = _past_horizon_line(received=date(2029, 3, 12))
    r = assess([line], load_calendar(), load_gic(), date(2029, 4, 1))[0]
    assert r.deadline.due == date(2029, 3, 12)
    assert r.verdict == "ON_TIME"


def test_remittance_past_a_past_horizon_deadline_is_unassessable():
    line = _past_horizon_line(remitted=date(2029, 3, 13))
    r = assess([line], load_calendar(), load_gic(), date(2029, 4, 1))[0]
    assert r.verdict == "UNKNOWN"
    assert r.horizon_verdicts == ("LATE", "AT_RISK")
    assert any("left unassessed" in c for c in r.caveats)


def test_an_unassessable_line_gets_its_own_block_and_a_non_zero_exit(tmp_path, capsys):
    """A 9,000 payday whose receipt is 41 days past the deadline used to be
    summarised as one line of "other line(s) carry data-quality notes" behind
    exit 0, which README documents as nothing exposed."""
    path = tmp_path / "pay.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "VERYLATE29,2029-03-01,9000.00,2029-04-20,2029-04-22,no,no,,no\n",
        encoding="utf-8",
    )
    code = main([str(path), "-o", str(tmp_path / "r.csv"), "--as-at", "2029-06-01"])
    out = capsys.readouterr().out
    assert code == 2
    assert "cannot be assessed" in out
    assert "row 2  QE day 2029-03-01  due 2029-03-12" in out
    assert "VERYLATE29" not in out
    assert "super $9000.00" in out
    assert "LATE or ON_TIME" in out
    # It must no longer be swept into the silent data-quality bucket.
    assert "other line(s) carry data-quality notes" not in out


def test_an_unassessable_line_is_not_counted_as_a_plain_data_quality_note():
    line = _past_horizon_line(received=date(2029, 3, 13))
    results = assess([line], load_calendar(), load_gic(), date(2029, 4, 1))
    text = console_summary(results, date(2029, 4, 1), "report.csv", "2026-08-02", load_rates())
    assert "cannot be assessed" in text
    assert "other line(s) carry data-quality notes" not in text


def test_a_deadline_inside_the_horizon_is_still_assessed():
    """The override only fires past verified_until, not before it."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2028, 12, 1),
        sg_amount=Decimal("500.00"),
        received=date(2028, 12, 29),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), date(2029, 1, 5))[0]
    assert r.verdict == "LATE"
    assert r.final_shortfall == Decimal("0")


def test_prepayment_past_the_horizon_keeps_its_verdict():
    """s 18C(1)(c)(ii) compares the receipt with the QE day and a 12-month
    calendar window, never with the business-day deadline, so the horizon
    cannot make that verdict unknowable."""
    line = _past_horizon_line(received=date(2028, 12, 1))
    r = assess([line], load_calendar(), load_gic(), date(2029, 4, 1))[0]
    assert r.verdict == "ON_TIME"


def test_horizon_caveat_says_the_table_may_be_missing_holidays():
    """The caveat used to claim the table "holds no holidays at all" past the
    horizon, which stopped being true once coverage became a declared span:
    a partial override can hold a 2029 holiday while 2029 stays uncovered.
    It now claims only what is true either way - a missing holiday can push
    the real deadline later, never earlier."""
    cal = load_calendar()
    text = cal.check_horizon(date(2029, 1, 1))
    assert "the last day the holiday table is complete to" in text
    assert "may be missing" in text
    assert "can only be later than the one shown" in text
    assert "holds no holidays at all" not in text


def test_an_unrelated_added_holiday_does_not_silence_the_horizon(tmp_path, capsys):
    """End to end for the coverage regression, on the CLI the README tells you
    to schedule. An override adding only Christmas 2029 used to jump the
    coverage end nine months forward, so an EARLIER 2029 payday lost its
    horizon caveat entirely and was reported LATE with an SG charge attached -
    while the holidays actually missing from that window (Good Friday, Easter
    Monday) would have moved the deadline and made it on time."""
    src = tmp_path / "east.csv"
    src.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "EAST29,2029-03-27,5000.00,2029-04-05,2029-04-06,no,no,,no\n",
        encoding="utf-8",
    )
    sparse = tmp_path / "sparse.json"
    sparse.write_text(
        json.dumps(
            {"add": [{"date": "2029-12-25", "name": "Christmas Day",
                      "jurisdictions": ["ALL"]}]}
        ),
        encoding="utf-8",
    )
    code = main([
        str(src), "-o", str(tmp_path / "out.csv"), "--as-at", "2029-05-01",
        "--holidays-override", str(sparse),
    ])
    printed = capsys.readouterr().out
    assert code == EXIT_LATE_FOUND
    assert "LATE: 0" in printed
    assert "UNKNOWN: 1" in printed
    assert "beyond the calendar's coverage (2028-12-31" in printed

    # Declaring the year is what earns a verdict, and it is the RIGHT verdict:
    # with Easter in the table the receipt on 6 Apr beat a 9 Apr deadline.
    declared = tmp_path / "declared.json"
    declared.write_text(
        json.dumps(
            {
                "verified_until": "2029-12-31",
                "add": [
                    {"date": "2029-03-30", "name": "Good Friday", "jurisdictions": ["ALL"]},
                    {"date": "2029-04-02", "name": "Easter Monday", "jurisdictions": ["ALL"]},
                    {"date": "2029-04-25", "name": "Anzac Day", "jurisdictions": ["ALL"]},
                    {"date": "2029-12-25", "name": "Christmas Day", "jurisdictions": ["ALL"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    code = main([
        str(src), "-o", str(tmp_path / "out2.csv"), "--as-at", "2029-05-01",
        "--holidays-override", str(declared),
    ])
    printed = capsys.readouterr().out
    assert code == 0
    assert "ON_TIME: 1" in printed


def test_an_unpaid_row_past_the_horizon_does_not_claim_the_deadline_passed(tmp_path, capsys):
    """The UNPAID verdict stays - an unrecorded contribution is money owed
    whatever the calendar knows - but past the coverage end the sentence
    "the deadline passed on X" contradicted the row's own horizon caveat.

    Canberra Day 2029 falls on 12 Mar and is an ACT-wide public holiday, so
    the deadline this row is told passed on 12 Mar is really 13 Mar."""
    src = tmp_path / "edge.csv"
    src.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "EDGE29,2029-03-01,4000.00,,,no,no,,no\n",
        encoding="utf-8",
    )
    code = main([str(src), "-o", str(tmp_path / "out.csv"), "--as-at", "2029-03-13"])
    printed = capsys.readouterr().out
    assert code == EXIT_LATE_FOUND
    assert "UNPAID: 1" in printed          # exposure stays visible
    assert "the deadline passed on" not in printed
    assert "may not have passed yet" in printed


def test_a_rates_file_whose_years_are_not_a_map_is_an_error_not_a_traceback(
    tmp_path, monkeypatch
):
    """Guarding only the top level left the field the code dereferences
    unchecked: console_summary does fy.get(label) then entry.get(...), and
    cli.py calls it outside every try block, so either shape reached the user
    as a raw AttributeError."""
    from paydaysuper import rates as rates_module

    for doc in ({"financial_years": []}, {"financial_years": {"2026-27": "12"}}):
        (tmp_path / "rates.json").write_text(json.dumps(doc), encoding="utf-8")
        monkeypatch.setattr(rates_module, "DATA_DIR", tmp_path)
        with pytest.raises(rates_module.RatesError, match="financial.year"):
            rates_module.load_rates()


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
    flagged = [c for c in results[1].caveats if "capitalisation" in c]
    assert flagged
    # The caveat reaches the console, so it names rows, never the ids: each
    # row's report CSV line already carries its employee_id in its own column.
    assert all("rows 2, 3" in c for c in flagged)
    assert all("EMP001" not in c and "emp001" not in c for c in flagged)


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
    assert any(
        "no payment on or before the as-at date 2026-08-10 is recorded" in c
        for c in results[1].caveats
    )


def test_item4_inherited_caveat_survives_a_post_as_at_donor_payment():
    """A donor payment dated after the as-at date must not settle this
    caveat: the as-at rule says future facts cannot settle a historical
    report, and at the as-at date no payment seeding the inherited window
    was on record."""
    cal = load_calendar()
    rows = [
        ContribLine(
            employee_id="E9",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("100.00"),
            received=date(2026, 9, 1),  # after AS_AT
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
    assert results[1].deadline.due == date(2026, 8, 7)  # inherited
    assert any(
        "no payment on or before the as-at date 2026-08-10 is recorded" in c
        for c in results[1].caveats
    )
    # And a donor payment on or before the as-at date still settles it.
    rows[0].received = date(2026, 8, 6)
    results = assess(rows, cal, load_gic(), AS_AT)
    assert not any("inherited from the QE day" in c for c in results[1].caveats)


def test_a_nil_payday_does_not_extend_a_later_real_paydays_verdict():
    """End to end for the item 4 seed: a 0.00 payday flagged first-to-fund
    stretched the next real payday's deadline from 4 Aug to 7 Aug and turned
    a 1,000 late contribution on time."""
    rows = [
        ContribLine(
            employee_id="EMP200",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("0.00"),
            remitted=date(2026, 7, 15),
            first_to_fund=True,
            row=2,
        ),
        ContribLine(
            employee_id="EMP200",
            qe_day=date(2026, 7, 23),
            sg_amount=Decimal("1000.00"),
            remitted=date(2026, 8, 5),
            received=date(2026, 8, 6),
            row=3,
        ),
    ]
    results = assess(rows, load_calendar(), load_gic(), AS_AT)
    real = results[1]
    assert real.deadline.due == date(2026, 8, 4)
    assert real.verdict == "LATE"
    assert real.days_late == 2


def test_a_nil_donor_does_not_suppress_the_unrecorded_item_4_caveat():
    """The donor test read dates only, so a nil donor carrying a remittance
    date made the whole donor set look recorded and the caveat vanished."""
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
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("0.00"),
            remitted=date(2026, 7, 15),
            first_to_fund=True,
            row=3,
        ),
        ContribLine(
            employee_id="E9",
            qe_day=date(2026, 7, 23),
            sg_amount=Decimal("100.00"),
            received=date(2026, 8, 6),
            row=4,
        ),
    ]
    results = assess(rows, load_calendar(), load_gic(), AS_AT)
    aligned = results[2]
    assert aligned.deadline.pathway == "ITEM4_ALIGNED"
    assert any(
        "no payment on or before the as-at date 2026-08-10 is recorded" in c
        for c in aligned.caveats
    )


def test_a_supplied_2029_calendar_produces_a_real_verdict(tmp_path):
    """--holidays-override is the remedy the horizon caveat recommends, so a
    user who takes it must get a verdict, not the same caveat back."""
    override = tmp_path / "holidays.json"
    override.write_text(
        json.dumps(
            {
                "verified_until": "2029-04-25",
                "add": [
                    {"date": "2029-03-30", "name": "Good Friday", "jurisdictions": ["ALL"]},
                    {"date": "2029-04-02", "name": "Easter Monday", "jurisdictions": ["ALL"]},
                    {"date": "2029-04-25", "name": "Anzac Day", "jurisdictions": ["ALL"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    def row(received):
        return ContribLine(
            employee_id="E9",
            qe_day=date(2029, 3, 27),
            sg_amount=Decimal("500.00"),
            received=received,
            row=2,
        )

    patched = load_calendar(override)
    on_time = assess([row(date(2029, 4, 6))], patched, load_gic(), date(2029, 5, 1))[0]
    assert on_time.deadline.due == date(2029, 4, 9)
    assert on_time.verdict == "ON_TIME"
    assert not any("beyond the calendar's coverage" in c for c in on_time.caveats)

    # The late side is the half that needs report.py to read the coverage end
    # rather than verified_until: a receipt past the deadline is unassessable
    # while the calendar cannot see 2029, and a settled verdict once it can.
    late = assess([row(date(2029, 4, 12))], patched, load_gic(), date(2029, 5, 1))[0]
    assert late.verdict == "LATE"
    assert late.days_late == 3
    assert late.final_shortfall == Decimal("0")  # received before any assessment
    assert not any("beyond the calendar's coverage" in c for c in late.caveats)

    # Without the override the same rows sit on a four-day-earlier deadline
    # that the calendar cannot vouch for, which is why the caveat exists.
    bare_cal = load_calendar()
    bare = assess([row(date(2029, 4, 12))], bare_cal, load_gic(), date(2029, 5, 1))[0]
    assert bare.deadline.due == date(2029, 4, 5)
    assert bare.verdict == "UNKNOWN"
    assert bare.horizon_verdicts == ("LATE", "ON_TIME")
    assert any("beyond the calendar's coverage" in c for c in bare.caveats)


def test_exposure_past_the_horizon_leaves_days_late_blank_and_labels_a_maximum():
    """An unpaid payday past the calendar's coverage is still exposure, but
    the deadline it is measured from can only move later, so a definite whole
    number of days late and a settled dollar figure claim too much."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2029, 3, 1),
        sg_amount=Decimal("500.00"),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), date(2029, 6, 1))[0]
    assert r.verdict == "UNPAID"
    assert r.days_late is None
    assert r.nec > Decimal("0")
    assert any("are a maximum" in c for c in r.caveats)

    text = console_summary(
        [r], date(2029, 6, 1), "report.csv", "2026-08-02", load_rates()
    )
    assert "days late not pinned down" in text
    assert "notional earnings at most $" in text
    assert "SG charge estimate at most $" in text
    assert "None days late" not in text


def test_days_late_inside_the_horizon_is_still_a_definite_number():
    """The other side: nothing about the carve-out leaks into an ordinary
    row, whose deadline the calendar does pin down."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("500.00"),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.verdict == "UNPAID"
    assert r.days_late == 21
    assert not any("are a maximum" in c for c in r.caveats)
    text = console_summary([r], AS_AT, "report.csv", "2026-08-02", load_rates())
    assert "21 days late" in text
    assert "at most $" not in text


def test_days_late_blank_reaches_the_report_csv(tmp_path):
    path = tmp_path / "pay.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "E9,2029-03-01,500.00,,,no,no,,no\n",
        encoding="utf-8",
    )
    out = tmp_path / "r.csv"
    assert main([str(path), "-o", str(out), "--as-at", "2029-06-01"]) == 2
    with open(out, newline="", encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
    assert row["verdict"] == "UNPAID"
    assert row["days_late"] == ""
    assert Decimal(row["final_shortfall"]) == Decimal("500.00")


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


def test_at_risk_caveats_reach_the_console():
    """An at-risk line is in neither the exposure listing nor the unflagged
    count, so its caveats used to go nowhere but the CSV."""
    rows = [
        ContribLine(
            employee_id="E9",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("100.00"),
            remitted=date(2026, 7, 15),
            row=n,
        )
        for n in (2, 3)
    ]
    results = assess(rows, load_calendar(), load_gic(), AS_AT)
    assert all(r.verdict == "AT_RISK" for r in results)
    text = console_summary(results, AS_AT, "report.csv", "2026-08-02", load_rates())
    assert "counted 2 times" in text
    assert "receipt by the fund" in text


def test_the_universal_at_risk_caveat_does_not_fill_the_listing():
    """Every AT_RISK row carries the no-fund-receipt caveat by construction,
    so listing it made ten rows whose only note repeated the block header, and
    the duplicate-payday warning on rows 12 and 13 was truncated away."""
    plain = [
        ContribLine(
            employee_id=f"E{n:02d}",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("100.00"),
            remitted=date(2026, 7, 15),
            row=n + 1,
        )
        for n in range(1, 11)
    ]
    pair = [
        ContribLine(
            employee_id="DUPE",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("100.00"),
            remitted=date(2026, 7, 15),
            row=row,
        )
        for row in (12, 13)
    ]
    results = assess(plain + pair, load_calendar(), load_gic(), AS_AT)
    assert all(r.verdict == "AT_RISK" for r in results)
    text = console_summary(results, AS_AT, "report.csv", "2026-08-02", load_rates())

    assert "12 line(s) remitted by the deadline" in text
    assert "counted 2 times" in text
    assert "row 12  QE day 2026-07-09  due 2026-07-20" in text
    assert "row 13  QE day 2026-07-09  due 2026-07-20" in text
    assert "DUPE" not in text
    # The ten rows with nothing of their own to say are not listed, and no
    # truncation notice is owed because only two rows carry a real note.
    assert "row 2  E01" not in text
    assert "more at-risk line(s) with notes" not in text
    assert "statutory test is receipt by the fund" not in text


def _at_risk_result(n: int, caveats: list[str]):
    """An AT_RISK Result built straight, so the console block can be driven
    with exactly the caveats under test."""
    from paydaysuper.deadlines import USUAL_7BD, Deadline
    from paydaysuper.report import NO_RECEIPT_CAVEAT, AT_RISK, Result

    line = ContribLine(
        employee_id=f"ARK{n:02d}",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("100.00"),
        remitted=date(2026, 7, 15),
        row=n + 1,
    )
    deadline = Deadline(due=date(2026, 7, 20), pathway=USUAL_7BD)
    return Result(line, deadline, AT_RISK, caveats=[NO_RECEIPT_CAVEAT] + caveats)


def test_the_at_risk_block_names_every_row_and_every_caveat_it_prints():
    """Four separate mutations of this block used to leave the suite green:
    dropping the row-identifying line, printing only the first caveat per
    row, printing only the first flagged row, and never emitting the
    truncation notice. None of the markers below appear anywhere else."""
    results = [
        _at_risk_result(n, [f"alpha marker {n}", f"beta marker {n}"])
        for n in range(1, 13)
    ]
    text = console_summary(results, AS_AT, "report.csv", "2026-08-02", load_rates())

    # Every one of the ten printed rows is named by its row number, QE day and
    # due date. Employee identifiers stay in the private CSV, not stdout.
    for n in range(1, 11):
        assert (
            f"  row {n + 1}  QE day 2026-07-09  due 2026-07-20" in text
        ), n
        assert f"ARK{n:02d}" not in text, n
        assert f"      note: alpha marker {n}" in text, n
        assert f"      note: beta marker {n}" in text, n

    # The cap stops at ten, and the two beyond it are counted, not printed.
    for n in (11, 12):
        assert f"ARK{n}" not in text
        assert f"alpha marker {n}" not in text
        assert f"beta marker {n}" not in text
    assert "... and 2 more at-risk line(s) with notes" in text

    # Twenty notes for ten rows: exactly two per row, no more and no fewer.
    assert text.count("      note: ") == 20
    assert text.count("QE day 2026-07-09  due 2026-07-20") == 10


def test_the_at_risk_truncation_notice_counts_only_flagged_rows():
    """Eleven rows carry a note and ten more carry nothing but the universal
    caveat, so the overflow is one, not eleven."""
    results = [_at_risk_result(n, [f"alpha marker {n}"]) for n in range(1, 12)]
    results += [_at_risk_result(n, []) for n in range(20, 30)]
    text = console_summary(results, AS_AT, "report.csv", "2026-08-02", load_rates())
    assert "21 line(s) remitted by the deadline" in text
    assert "... and 1 more at-risk line(s) with notes" in text


def test_report_columns_add_up(tmp_path):
    """Each figure is rounded once, so a row's parts sum to its totals.

    Read back off disk, not recomputed: comparing _rounded_figures against
    the expression that defines it is a tautology, and the property that
    matters is the one a reader sees in the file."""
    out = tmp_path / "report.csv"
    main([str(FIXTURE), "-o", str(out), "--as-at", "2026-08-10"])
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    checked = 0
    for r in rows:
        if r["verdict"] not in ("LATE", "UNPAID"):
            continue
        checked += 1
        shortfall = Decimal(r["final_shortfall"])
        nec = Decimal(r["notional_earnings"])
        assert shortfall + nec + Decimal(r["uplift_best_case"]) == Decimal(
            r["sgc_estimate_low"]
        ), r
        assert shortfall + nec + Decimal(r["uplift_worst_case"]) == Decimal(
            r["sgc_estimate_high"]
        ), r
    assert checked >= 3


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


def test_days_late_is_not_truncated_by_the_assessment_date():
    """An assessment stops interest accruing; it does not shorten how long
    the money was outstanding."""
    lines = parse_rows(FIXTURE, *load_mapping(None))
    results = assess(
        lines, load_calendar(), load_gic(), AS_AT, assessment_date=date(2026, 8, 5)
    )
    r = by_employee(results, "EMP001", date(2026, 7, 23))
    assert r.verdict == "LATE"
    assert r.final_shortfall == Decimal("612.00")  # receipt postdates assessment
    assert r.days_late == 2                        # due 4 Aug, received 6 Aug
    assert any("day before the assessment" in c for c in r.caveats)


def test_stale_prepayment_gets_no_new_starter_hint():
    """Flipping the flag cannot rescue a receipt outside the 12-month
    window, so the tool must not suggest it."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2027, 9, 15),
        sg_amount=Decimal("1000.00"),
        received=date(2026, 8, 1),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), date(2027, 10, 30))[0]
    assert r.verdict == "LATE"
    assert not any("first_contribution_to_fund" in c for c in r.caveats)


def test_new_starter_hint_wording_matches_the_verdict_it_would_produce():
    """With only a remittance date the line becomes AT_RISK, not on time."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("100.00"),
        remitted=date(2026, 8, 5),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    hint = [c for c in r.caveats if "first_contribution_to_fund" in c]
    assert hint and "stays at risk" in hint[0]


def test_zero_amount_line_with_late_payment_dates_is_not_exposure(tmp_path):
    line = ContribLine(
        employee_id="E0",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("0.00"),
        remitted=date(2026, 7, 15),
        received=date(2026, 7, 25),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.verdict == "UNKNOWN"
    assert r.sgc_high is None
    assert any("nothing to assess" in caveat for caveat in r.caveats)

    path = tmp_path / "pay.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "E0,2026-07-09,0.00,2026-07-15,2026-07-25,no,no,,no\n",
        encoding="utf-8",
    )
    assert main([str(path), "-o", str(tmp_path / "r.csv"), "--as-at", "2026-08-10"]) == 0


def test_item4_caveat_only_fires_on_an_aligned_line():
    """Two paydays can share a due date by plain calendar arithmetic without
    item 4 applying at all."""
    rows = [
        ContribLine(
            employee_id="E9", qe_day=date(2026, 7, 10), sg_amount=Decimal("100.00"), row=2
        ),
        ContribLine(
            employee_id="E9", qe_day=date(2026, 7, 11), sg_amount=Decimal("100.00"), row=3
        ),
    ]
    results = assess(rows, load_calendar(), load_gic(), AS_AT)
    assert results[0].deadline.due == results[1].deadline.due  # same due date
    assert results[1].deadline.pathway == "USUAL_7BD"
    assert not any("inherited" in c for c in results[1].caveats)


def test_item4_caveat_names_the_deadline_without_the_alignment():
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
    results = assess(rows, load_calendar(), load_gic(), AS_AT)
    caveat = [c for c in results[1].caveats if "inherited" in c]
    assert caveat and "2026-08-04" in caveat[0]  # its own period end


def test_item4_caveat_keeps_an_out_of_cycle_lines_own_deadline():
    """The aligned line rides its next standard payday, so its own deadline
    is 6 Aug, not the 4 Aug that qe_day plus 7 business days would give."""
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
            out_of_cycle=True,
            next_standard_qe_day=date(2026, 7, 27),
            received=date(2026, 8, 7),
            row=3,
        ),
    ]
    results = assess(rows, load_calendar(), load_gic(), AS_AT)
    aligned = results[1]
    assert aligned.deadline.pathway == "ITEM4_ALIGNED"
    assert aligned.deadline.due == date(2026, 8, 7)
    caveat = [c for c in aligned.caveats if "inherited" in c]
    assert caveat, aligned.caveats
    assert "2026-08-06" in caveat[0]
    assert "2026-08-04" not in caveat[0]


def test_report_csv_carries_a_bom_and_round_trips_a_non_ascii_id(tmp_path):
    """Excel on a cp1252 box mis-decodes a BOM-less UTF-8 CSV, so a
    non-ASCII employee id stops joining back to payroll. The reader takes
    utf-8-sig either way, so a report fed back in still parses."""
    # Capital N with tilde, built from its code point so this file stays ASCII.
    employee = "EMP" + chr(0x00D1) + "001"
    path = tmp_path / "pay.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        f"{employee},2026-07-09,100.00,,2026-07-15,no,no,,no\n",
        encoding="utf-8",
    )
    out = tmp_path / "r.csv"
    main([str(path), "-o", str(out), "--as-at", "2026-08-10"])

    assert out.read_bytes().startswith(codecs.BOM_UTF8)
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["row"] == "2"  # the BOM is not glued to the first heading
    assert rows[0]["employee_id"] == employee

    # Feeding the report back through the tool's own reader: it strips the
    # BOM, so the id survives the round trip byte for byte.
    reparsed = tmp_path / "again.csv"
    reparsed.write_bytes(
        codecs.BOM_UTF8
        + (
            "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
            "first_contribution_to_fund,out_of_cycle,next_standard_payday,"
            "defined_benefit\n"
            f"{rows[0]['employee_id']},{rows[0]['qe_day']},{rows[0]['sg_amount']},,,"
            "no,no,,no\n"
        ).encode("utf-8")
    )
    lines = parse_rows(reparsed, *load_mapping(None))
    assert lines[0].employee_id == employee
    assert lines[0].qe_day == date(2026, 7, 9)


def test_ordinary_employee_ids_are_not_rewritten(tmp_path):
    """A code starting with a hyphen must still join back to payroll."""
    path = tmp_path / "pay.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "-00123,2026-07-09,100.00,,2026-07-15,no,no,,no\n",
        encoding="utf-8",
    )
    out = tmp_path / "r.csv"
    main([str(path), "-o", str(out), "--as-at", "2026-08-10"])
    assert ",-00123," in out.read_text(encoding="utf-8")


def test_cli_rejects_an_absurd_as_at_date(tmp_path, capsys):
    assert main([str(FIXTURE), "-o", str(tmp_path / "r.csv"), "--as-at", "9999-01-01"]) == 1
    assert "not a real date" in capsys.readouterr().err


def test_the_csv_marks_an_unassessable_row_apart_from_a_nil_one(tmp_path):
    """Console and exit code covered this; the CSV did not.

    Both rows below carry verdict UNKNOWN with a blank shortfall. One is a
    9,000 contribution nobody can assess because the deadline runs past the
    calendar's coverage; the other is a nil payday with nothing to assess.
    Anyone parsing the file rather than watching the console could not tell
    real exposure from nothing at all.
    """
    src = tmp_path / "mixed.csv"
    src.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "VERYLATE29,2029-03-01,9000.00,2029-03-20,2029-03-20,no,no,,no\n"
        "NIL29,2026-07-09,0.00,,,no,no,,no\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.csv"
    main([str(src), "-o", str(out), "--as-at", "2029-06-01"])
    with open(out, newline="", encoding="utf-8") as f:
        rows = {r["employee_id"]: r for r in csv.DictReader(f)}

    exposed, nil = rows["VERYLATE29"], rows["NIL29"]
    assert exposed["verdict"] == nil["verdict"] == "UNKNOWN"
    assert exposed["final_shortfall"] == nil["final_shortfall"] == ""
    # The column that tells them apart.
    assert exposed["unassessable_between"] == "LATE or ON_TIME"
    assert nil["unassessable_between"] == ""

    # And the trailing note still lands in "notes", not in the new last column.
    note = rows["NOTE"]
    assert "2026-08-02" in note["notes"]
    assert note["unassessable_between"] == ""
