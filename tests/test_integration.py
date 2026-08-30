import codecs
import csv
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from paydaysuper.calendar import load_calendar
from paydaysuper.assess import LATE, Result
from paydaysuper.cli import EXIT_ERROR, EXIT_LATE_FOUND, EXIT_OK, main as cli_main
from paydaysuper.csv_io import load_mapping, parse_rows
from paydaysuper.deadlines import ContribLine, Deadline
from paydaysuper.rates import load_gic, load_rates
from paydaysuper.report import assess as report_assess
from paydaysuper.report import console_summary, financial_year, needs_attention
from paydaysuper.sgc import notional_earnings

from conftest import SAMPLE as FIXTURE
AS_AT = date(2026, 8, 10)


def assess(*args, **kwargs):
    """Most integration cases isolate another rule using July fixtures whose
    old-quarter balances are synthetic and assumed reconciled. Production is
    fail-closed; the dedicated transition tests below call report_assess
    directly to exercise that default."""
    kwargs.setdefault("transition_allocation_confirmed", True)
    return report_assess(*args, **kwargs)


def main(argv):
    """Integration fixtures assume their synthetic old-quarter balances were
    reconciled. The dedicated fail-closed test calls cli_main directly."""
    args = list(argv)
    if args and args[0] != "import" and "--confirm-transition-allocation" not in args:
        args.append("--confirm-transition-allocation")
    return cli_main(args)


def run_fixture():
    lines = parse_rows(FIXTURE, *load_mapping(None))
    return assess(
        lines,
        load_calendar(),
        load_gic(),
        AS_AT,
        transition_allocation_confirmed=True,
    )


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


def test_console_refuses_exposed_result_without_exposure_figures():
    """A malformed result must fail closed rather than display zero exposure."""
    result = Result(
        line=ContribLine("E1", date(2026, 7, 9), Decimal("100.00"), row=2),
        deadline=Deadline(date(2026, 7, 20), "usual period"),
        verdict=LATE,
    )

    with pytest.raises(AssertionError, match="exposure figures"):
        console_summary([result], AS_AT, "report.csv", "2026-08-15", load_rates())


def test_partial_late_receipt_keeps_the_statutory_base_and_nec_running():
    lines = [
        ContribLine(
            employee_id="E1",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("1000.00"),
            remitted=date(2026, 7, 14),
            remitted_amount=Decimal("999.99"),
            received=date(2026, 8, 1),
            row=2,
        )
    ]
    results = assess(
        lines,
        load_calendar(),
        load_gic(),
        AS_AT,
        transition_allocation_confirmed=True,
    )
    r = results[0]
    assert r.verdict == "LATE"
    assert r.final_shortfall == Decimal("0.01")
    assert r.base_shortfall == Decimal("1000.00")
    assert r.nec == notional_earnings(
        Decimal("1000.00"), r.deadline.due, AS_AT, load_gic()
    )
    assert r.offset_s18d is True
    text = console_summary([r], AS_AT, "report.csv", "2026-08-15", load_rates())
    assert "partially reduced" in text
    assert "shortfall is nil" not in text


def test_near_full_and_full_late_receipts_keep_the_same_base_shortfall():
    def line(amount):
        return ContribLine(
            employee_id=f"E-{amount}",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("1000.00"),
            remitted=date(2026, 7, 14),
            remitted_amount=amount,
            received=date(2026, 8, 1),
            row=2,
        )

    partial, full = assess(
        [line(Decimal("999.99")), line(Decimal("1000.00"))],
        load_calendar(),
        load_gic(),
        AS_AT,
    )
    assert partial.base_shortfall == full.base_shortfall == Decimal("1000.00")
    assert partial.final_shortfall == Decimal("0.01")
    assert full.final_shortfall == Decimal("0")
    assert partial.nec == notional_earnings(
        Decimal("1000.00"), partial.deadline.due, AS_AT, load_gic()
    )
    assert full.nec == notional_earnings(
        Decimal("1000.00"), full.deadline.due, date(2026, 8, 1), load_gic()
    )


def test_partial_on_time_receipt_reduces_only_the_base_shortfall():
    line = ContribLine(
        employee_id="E-PART-ON-TIME",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("1000.00"),
        remitted=date(2026, 7, 14),
        remitted_amount=Decimal("600.00"),
        received=date(2026, 7, 15),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert r.verdict == "UNPAID"
    assert r.base_shortfall == Decimal("400.00")
    assert r.final_shortfall == Decimal("400.00")
    assert r.offset_s18d is False
    assert r.nec == notional_earnings(
        Decimal("400.00"), r.deadline.due, AS_AT, load_gic()
    )


def test_partial_stale_prepayment_receives_no_statutory_credit():
    line = ContribLine(
        employee_id="E-STALE-PART",
        qe_day=date(2027, 7, 9),
        sg_amount=Decimal("1000.00"),
        remitted=date(2026, 7, 1),
        remitted_amount=Decimal("999.99"),
        received=date(2026, 7, 1),
        row=2,
    )
    as_at = date(2027, 8, 1)
    r = assess([line], load_calendar(), load_gic(), as_at)[0]
    assert r.verdict == "LATE"
    assert r.base_shortfall == Decimal("1000.00")
    assert r.final_shortfall == Decimal("1000.00")
    assert r.offset_s18d is False
    assert r.nec == notional_earnings(
        Decimal("1000.00"), r.deadline.due, as_at, load_gic()
    )


def test_partial_late_receipt_after_assessment_does_not_reduce_shortfall():
    line = ContribLine(
        employee_id="E-PART-AFTER-ASSESSMENT",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("1000.00"),
        remitted=date(2026, 7, 14),
        remitted_amount=Decimal("600.00"),
        received=date(2026, 8, 1),
        row=2,
    )
    assessment_date = date(2026, 7, 25)
    r = assess(
        [line], load_calendar(), load_gic(), AS_AT,
        assessment_date=assessment_date,
    )[0]
    assert r.verdict == "LATE"
    assert r.base_shortfall == Decimal("1000.00")
    assert r.final_shortfall == Decimal("1000.00")
    assert r.offset_s18d is False
    assert r.nec == notional_earnings(
        Decimal("1000.00"), r.deadline.due,
        assessment_date - timedelta(days=1), load_gic()
    )


def test_partial_receipt_before_assessment_keeps_nec_running_to_assessment():
    line = ContribLine(
        employee_id="E-PART-BEFORE-ASSESSMENT",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("1000.00"),
        remitted=date(2026, 7, 14),
        remitted_amount=Decimal("600.00"),
        received=date(2026, 8, 1),
        row=2,
    )
    assessment_date = date(2026, 8, 5)
    r = assess(
        [line], load_calendar(), load_gic(), AS_AT,
        assessment_date=assessment_date,
    )[0]
    assert r.base_shortfall == Decimal("1000.00")
    assert r.final_shortfall == Decimal("400.00")
    assert r.offset_s18d is True
    assert r.nec == notional_earnings(
        Decimal("1000.00"), r.deadline.due,
        assessment_date - timedelta(days=1), load_gic()
    )


def test_explicit_remitted_amount_without_remittance_date_is_refused():
    line = ContribLine(
        employee_id="E-MALFORMED-PART",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("1000.00"),
        remitted_amount=Decimal("600.00"),
        received=date(2026, 8, 1),
        row=2,
    )
    with pytest.raises(ValueError, match="remitted_amount requires remitted_date"):
        assess([line], load_calendar(), load_gic(), AS_AT)


@pytest.mark.parametrize(
    ("sg_amount", "remitted_amount", "matched_amount", "message"),
    [
        (Decimal("-0.01"), None, None, "sg_amount cannot be negative"),
        (
            Decimal("1000.00"),
            Decimal("-0.01"),
            None,
            "remitted_amount must be between zero and sg_amount",
        ),
        (
            Decimal("1000.00"),
            Decimal("1000.01"),
            None,
            "remitted_amount must be between zero and sg_amount",
        ),
        (
            Decimal("1000.00"),
            None,
            Decimal("-0.01"),
            "matched_amount must be between zero and sg_amount",
        ),
        (
            Decimal("1000.00"),
            None,
            Decimal("1000.01"),
            "matched_amount must be between zero and sg_amount",
        ),
        (
            Decimal("1000.00"),
            Decimal("600.01"),
            Decimal("600.00"),
            "remitted_amount cannot exceed matched_amount",
        ),
    ],
)
def test_direct_assessment_refuses_invalid_amount_shapes(
    sg_amount, remitted_amount, matched_amount, message
):
    line = ContribLine(
        employee_id="E-BAD-AMOUNT",
        qe_day=date(2026, 7, 9),
        sg_amount=sg_amount,
        remitted=date(2026, 7, 14) if remitted_amount is not None else None,
        remitted_amount=remitted_amount,
        matched_amount=matched_amount,
        received=date(2026, 7, 15),
        first_to_fund=True,
        row=2,
    )
    with pytest.raises(ValueError, match=message):
        assess([line], load_calendar(), load_gic(), AS_AT)


@pytest.mark.parametrize("matched_amount", [Decimal("0"), Decimal("600")])
def test_direct_assessment_refuses_partial_match_with_unbounded_remittance(
    matched_amount,
):
    line = ContribLine(
        employee_id="E-AMBIGUOUS-REMITTANCE",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("1000.00"),
        remitted=date(2026, 7, 14),
        matched_amount=matched_amount,
        row=2,
    )
    with pytest.raises(
        ValueError, match="matched_amount below sg_amount requires remitted_amount"
    ):
        assess([line], load_calendar(), load_gic(), AS_AT)


def test_duplicate_warning_normalises_legacy_and_explicit_full_remittance():
    common = dict(
        employee_id="E-DUP",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("1000.00"),
        remitted=date(2026, 7, 14),
    )
    legacy = ContribLine(**common, row=2)
    explicit = ContribLine(
        **common, remitted_amount=Decimal("1000.00"), row=3
    )
    results = assess([legacy, explicit], load_calendar(), load_gic(), AS_AT)
    for result in results:
        assert any(
            "rows 2, 3 are identical" in caveat for caveat in result.caveats
        )


def test_assessment_before_receipt_keeps_the_shortfall():
    """The offset needs receipt to beat the assessment. Assess earlier and
    the whole SG amount stays in the charge."""
    lines = parse_rows(FIXTURE, *load_mapping(None))
    results = assess(
        lines,
        load_calendar(),
        load_gic(),
        AS_AT,
        assessment_date=date(2026, 7, 25),
        transition_allocation_confirmed=True,
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
    results = assess(
        lines,
        load_calendar(),
        load_gic(),
        AS_AT,
        transition_allocation_confirmed=True,
    )
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


def test_item4_without_an_evidenced_earlier_contribution_fails_closed():
    """Item 4 requires an earlier eligible contribution that was made and
    applied to the earlier QE day. A positive amount on an unfunded row is
    not that evidence and must not turn a later receipt from late to on time."""
    earlier = ContribLine(
        employee_id="ITEM4-EVIDENCE",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("100.00"),
        first_to_fund=True,
        row=2,
    )
    later = ContribLine(
        employee_id="ITEM4-EVIDENCE",
        qe_day=date(2026, 7, 23),
        sg_amount=Decimal("100.00"),
        received=date(2026, 8, 6),
        row=3,
    )

    result = assess(
        [earlier, later], load_calendar(), load_gic(), date(2026, 8, 6)
    )[1]

    assert result.deadline.due == date(2026, 8, 4)
    assert result.verdict == "UNKNOWN"
    assert result.horizon_verdicts == ("LATE", "ON_TIME")
    assert result.sgc_high is None
    assert needs_attention([result])
    assert any("item 4" in caveat.lower() for caveat in result.caveats)


@pytest.mark.parametrize(
    "donor_fields, expected_verdict, candidate_verdicts",
    [
        ({"remitted": date(2026, 7, 15)}, "UNKNOWN", ("LATE", "ON_TIME")),
        ({"received": date(2026, 8, 10)}, "LATE", None),
        ({"received": date(2026, 8, 8)}, "LATE", None),
    ],
)
def test_item4_remittance_or_late_receipt_is_not_eligible_evidence(
    donor_fields, expected_verdict, candidate_verdicts
):
    """Remittance is not fund receipt, and a receipt after the earlier
    contribution's own latest day cannot seed item 4."""
    earlier = ContribLine(
        employee_id="ITEM4-INELIGIBLE",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("100.00"),
        first_to_fund=True,
        row=2,
        **donor_fields,
    )
    later = ContribLine(
        employee_id="ITEM4-INELIGIBLE",
        qe_day=date(2026, 7, 23),
        sg_amount=Decimal("100.00"),
        received=date(2026, 8, 6),
        row=3,
    )

    result = assess(
        [earlier, later],
        load_calendar(),
        load_gic(),
        date(2026, 8, 10),
        transition_allocation_confirmed=True,
    )[1]

    assert result.deadline.due == date(2026, 8, 4)
    assert result.verdict == expected_verdict
    assert result.horizon_verdicts == candidate_verdicts
    assert needs_attention([result])


def test_item4_on_time_received_and_applied_contribution_is_evidence():
    earlier = ContribLine(
        employee_id="ITEM4-CONFIRMED",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("100.00"),
        first_to_fund=True,
        received=date(2026, 8, 7),
        row=2,
    )
    later = ContribLine(
        employee_id="ITEM4-CONFIRMED",
        qe_day=date(2026, 7, 23),
        sg_amount=Decimal("100.00"),
        received=date(2026, 8, 6),
        row=3,
    )

    result = assess(
        [earlier, later], load_calendar(), load_gic(), date(2026, 8, 7)
    )[1]

    assert result.deadline.due == date(2026, 8, 7)
    assert result.deadline.pathway == "ITEM4_ALIGNED"
    assert result.verdict == "ON_TIME"
    assert result.horizon_verdicts is None


def test_item4_indeterminate_result_is_explicit_in_console_and_csv(tmp_path, capsys):
    path = tmp_path / "item4.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "ITEM4-REPORT,2026-07-09,100.00,,,yes,no,,no\n"
        "ITEM4-REPORT,2026-07-23,100.00,,2026-08-06,no,no,,no\n",
        encoding="utf-8",
    )
    out = tmp_path / "report.csv"

    code = main([str(path), "-o", str(out), "--as-at", "2026-08-06"])

    assert code == EXIT_LATE_FOUND
    printed = capsys.readouterr().out
    assert "cannot be assessed from the supplied deadline facts" in printed
    assert "LATE or ON_TIME" in printed
    assert "Lines with exposure" not in printed
    with open(out, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    later = rows[1]
    assert later["due_date"] == "2026-08-04"
    assert later["verdict"] == "UNKNOWN"
    assert later["unassessable_between"] == "LATE or ON_TIME"
    assert later["final_shortfall"] == ""
    assert later["sgc_estimate_low"] == ""
    assert later["sgc_estimate_high"] == ""


def test_same_dates_without_the_extension_are_late():
    """EMP001's second payday mirrors EMP005's but has no extended window."""
    r = by_employee(run_fixture(), "EMP001", date(2026, 7, 23))
    assert r.deadline.due == date(2026, 8, 4)
    assert r.verdict == "LATE"


def test_transition_allocation_fails_closed_until_an_operator_reconciles_it(
    tmp_path, capsys
):
    """LCR 2026/1 was finalised after the original research date. The CSV
    cannot tell how much of an early contribution was consumed by the old
    June quarter, so the checker must not publish a verdict by default."""
    out = tmp_path / "report.csv"

    code = cli_main([str(FIXTURE), "-o", str(out), "--as-at", "2026-08-10"])

    assert code == EXIT_ERROR
    assert not out.exists()
    error = capsys.readouterr().err
    assert "LCR 2026/1" in error
    assert "rows 2, 4" in error
    assert "June-quarter shortfall" in error
    assert "--confirm-transition-allocation" in error
    # Process logs identify source rows, never payroll identifiers.
    assert "EMP001" not in error


def test_transition_confirmation_is_recorded_on_each_affected_result():
    results = run_fixture()
    affected = [result for result in results if result.line.row in {2, 4}]

    assert len(affected) == 2
    for result in affected:
        assert any("operator confirmed" in note for note in result.notes)
        assert any("LCR 2026/1 transition allocation" in note for note in result.notes)


def test_post_transition_contribution_needs_no_confirmation():
    line = ContribLine(
        employee_id="E1",
        qe_day=date(2026, 7, 31),
        sg_amount=Decimal("120.00"),
        received=date(2026, 8, 3),
        row=2,
    )

    result = assess([line], load_calendar(), load_gic(), AS_AT)[0]
    assert result.verdict == "ON_TIME"
    assert not any("transition allocation" in note for note in result.notes)


def test_pre_july_prepayment_also_needs_transition_confirmation():
    line = ContribLine(
        employee_id="E1",
        qe_day=date(2026, 7, 31),
        sg_amount=Decimal("120.00"),
        received=date(2026, 6, 30),
        row=2,
    )

    with pytest.raises(ValueError, match="unused excess"):
        report_assess([line], load_calendar(), load_gic(), AS_AT)


@pytest.mark.parametrize("bad_output", ["report.txt", "report", "report.csv.bak"])
def test_cli_rejects_a_non_csv_output_without_a_traceback(tmp_path, capsys, bad_output):
    """write_csv raises ValueError for these, and the write handler only ever
    covered OSError. The contract is 'error: <message>' and exit 1."""
    out = tmp_path / bad_output
    code = main([str(FIXTURE), "-o", str(out), "--as-at", "2026-08-10"])

    assert code == EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.err.startswith("error: ")
    assert ".csv" in captured.err
    assert not out.exists()


def test_cli_rejects_a_non_csv_output_before_it_reads_the_input(tmp_path, capsys):
    """The point of the up-front `csv_destination(args.output)` call is that
    the operator hears about a bad -o before the whole assessment runs. The
    write-time backstop in write_csv raises the same message and returns the
    same exit code, so no run that reaches write_csv can tell the two apart.
    An input file that does not exist can: only the up-front check can report
    the -o problem, because parse_rows never gets to open anything."""
    missing = tmp_path / "no-such-payrun.csv"

    code = main([str(missing), "-o", str(tmp_path / "report.txt"), "--as-at", "2026-08-10"])

    assert code == EXIT_ERROR
    err = capsys.readouterr().err
    assert "generated output must use a .csv filename" in err
    assert "file not found" not in err, (
        "the run reached parse_rows, so the -o check no longer fires up front"
    )


def test_cli_writes_report_and_flags_late(tmp_path, capsys):
    out = tmp_path / "report.csv"
    code = main(
        [
            str(FIXTURE),
            "-o",
            str(out),
            "--as-at",
            "2026-08-10",
            "--confirm-transition-allocation",
        ]
    )
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
    assert "2026-08-15" in note["notes"]
    assert "EXPERIMENTAL ESTIMATES" in note["notes"]
    assert "not advice" in note["notes"]
    assert "payday-super-checker 0.1.2" in note["notes"]
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
        "LCR 2026/1",
        "LCR 2026/D1 remains a draft",
        "EXPERIMENTAL ESTIMATES",
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


@pytest.mark.parametrize(
    "flag,contents",
    [
        ("--mapping-file", '{"qe_day": "payment_date"}\n'),
        (
            "--holidays-override",
            '{"verified_until": "2029-12-31", "add": [], "remove": []}\n',
        ),
    ],
)
def test_cli_refuses_to_overwrite_an_override_input(tmp_path, capsys, flag, contents):
    """The check command reads three files, not one. A --mapping-file or a
    --holidays-override aimed at by -o used to be overwritten with the report
    and the run still finished normally, returning EXIT_LATE_FOUND on this
    fixture with nothing on stderr, so a scheduled wrapper saw "late
    contributions found" rather than an error and the hand-written file was
    gone.

    The victim file is named .csv on purpose. Both flags normally take a JSON
    filename, and the generated-output suffix rule would then reject -o on its
    own and hide whether the alias guard fires at all. Renaming these to .json
    would leave the test green for the wrong reason."""
    source = tmp_path / "pay.csv"
    source.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    victim = tmp_path / "override.csv"
    victim.write_text(contents, encoding="utf-8")

    code = main(
        [str(source), flag, str(victim), "-o", str(victim), "--as-at", "2026-08-10"]
    )

    assert code == EXIT_ERROR
    err = capsys.readouterr().err
    assert "would overwrite" in err
    assert flag in err, "the message has to name which of the three inputs it means"
    assert victim.read_text(encoding="utf-8") == contents


def test_cli_replaces_an_output_symlink_without_touching_its_target(tmp_path):
    """A report must replace its chosen output link, never write through it."""
    output = tmp_path / "report.csv"
    protected_target = tmp_path / "protected.csv"
    protected_target.write_text("leave this file alone\n", encoding="utf-8")
    try:
        output.symlink_to(protected_target)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable in this test environment: {exc}")

    assert main(
        [
            str(FIXTURE),
            "-o",
            str(output),
            "--as-at",
            "2026-08-10",
            "--confirm-transition-allocation",
        ]
    ) == EXIT_LATE_FOUND

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


def test_stale_prepayment_before_the_deadline_is_not_yet_assessable():
    """A receipt outside the 12-month window cannot fund the payday, but a
    deadline that has not arrived cannot have been missed either. The line is
    unfunded and not yet due, so it must be as quiet as a payday with no dates
    recorded at all - not LATE with a full shortfall and an SG-charge estimate."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2027, 7, 9),
        sg_amount=Decimal("300.00"),
        received=date(2026, 7, 1),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), date(2027, 7, 12))[0]

    assert r.deadline.due >= date(2027, 7, 12)
    assert r.verdict == "UNKNOWN"
    assert r.sgc_high is None
    assert any("12-month pre-payment window" in caveat for caveat in r.caveats)
    assert any("the deadline has not passed" in caveat for caveat in r.caveats)


def test_a_stale_prepayment_is_still_quiet_on_the_deadline_date_itself():
    """The boundary of that gate, which the test above clears by eight days.
    `dl.due >= as_at` is the same line assess draws everywhere else: the
    nil-amount branch and the nothing-recorded branch both treat `dl.due <
    as_at` as "the deadline has passed", so a deadline falling ON the as-at
    date has not been missed. Move the boundary by one day and a payday that
    is still in time reports LATE with the whole contribution as a shortfall
    and an SG-charge estimate on top."""

    def stale_line():
        return ContribLine(
            employee_id="E9",
            qe_day=date(2027, 7, 9),
            sg_amount=Decimal("300.00"),
            received=date(2026, 7, 1),
            row=2,
        )

    on_the_day = assess(
        [stale_line()], load_calendar(), load_gic(), date(2027, 7, 20)
    )[0]
    assert on_the_day.deadline.due == date(2027, 7, 20)  # as-at IS the deadline
    assert on_the_day.verdict == "UNKNOWN"
    assert on_the_day.sgc_high is None
    assert any("the deadline has not passed" in c for c in on_the_day.caveats)

    day_after = assess([stale_line()], load_calendar(), load_gic(), date(2027, 7, 21))[0]
    assert day_after.verdict == "LATE"
    assert day_after.final_shortfall == Decimal("300.00")


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


def test_financial_year_rolls_over_on_1_july():
    """The 30 June / 1 July boundary itself. Every other test in this area
    uses July and September paydays, which land in the same financial year
    whether the rollover is tested at month 6 or month 7, so the boundary
    that decides which year's figures the console names was unguarded."""
    assert financial_year(date(2027, 6, 30)) == "2026-27"
    assert financial_year(date(2027, 7, 1)) == "2027-28"
    assert financial_year(date(2026, 12, 31)) == "2026-27"
    assert financial_year(date(2027, 1, 1)) == "2026-27"


def test_a_june_payday_names_the_financial_year_it_falls_in():
    """A June payday belongs to the financial year that started the previous
    July, so the console must quote that year's maximum contributions base.
    A rollover one month early sends it looking for a 2027-28 entry that
    rates.json does not hold, and the figure drops out of the workpaper in
    favour of the bare words "the annual cap"."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2027, 6, 8),
        sg_amount=Decimal("600.00"),
        received=date(2027, 6, 15),
        row=2,
    )
    results = assess([line], load_calendar(), load_gic(), date(2027, 7, 15))
    assert results[0].verdict == "ON_TIME"
    text = console_summary(
        results, date(2027, 7, 15), "report.csv", "2026-08-02", load_rates()
    )
    assert "$270,830 for 2026-27" in text
    assert "the annual cap" not in text


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
        received=date(2028, 12, 10),
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


def test_partial_receipt_before_a_past_horizon_deadline_leaves_due_date_unknown():
    line = _past_horizon_line(
        remitted=date(2029, 3, 1),
        remitted_amount=Decimal("50.00"),
        received=date(2029, 3, 2),
    )
    r = assess([line], load_calendar(), load_gic(), date(2029, 4, 1))[0]
    assert r.deadline.due == date(2029, 3, 12)
    assert r.verdict == "UNKNOWN"
    assert r.horizon_verdicts == ("UNPAID", "NOT_YET_DUE")
    assert r.base_shortfall is None
    assert r.final_shortfall is None


def test_partial_receipt_after_a_past_horizon_deadline_keeps_all_three_states_visible():
    line = _past_horizon_line(
        remitted=date(2029, 3, 13),
        remitted_amount=Decimal("50.00"),
        received=date(2029, 3, 14),
    )
    r = assess([line], load_calendar(), load_gic(), date(2029, 4, 1))[0]
    assert r.verdict == "UNKNOWN"
    assert r.horizon_verdicts == ("LATE", "NOT_YET_DUE")
    assert any("UNPAID" in caveat for caveat in r.caveats)
    assert r.base_shortfall is None
    assert r.final_shortfall is None


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


def test_a_deadline_on_the_last_covered_day_is_still_assessed():
    """The boundary of `dl.due > cal.coverage_until`.

    A deadline landing exactly on the last day the bundled calendar is
    complete to is covered: every holiday up to and including that day is in
    the table, so the date is settled and the verdict is owed."""
    cal = load_calendar()
    assert cal.coverage_until == date(2027, 8, 31)

    line = ContribLine(
        employee_id="E9",
        qe_day=date(2027, 8, 20),
        sg_amount=Decimal("500.00"),
        received=date(2027, 9, 6),
        row=2,
    )
    r = assess([line], cal, load_gic(), date(2027, 9, 15))[0]
    assert r.deadline.due == cal.coverage_until
    assert r.verdict == "LATE"
    assert r.horizon_verdicts is None
    assert r.days_late == 6
    assert r.final_shortfall is not None
    assert not any("beyond the calendar's coverage" in c for c in r.caveats)
    assert not any("runs past the calendar's coverage" in c for c in r.caveats)
    assert not any("left unassessed" in c for c in r.caveats)


def test_a_deadline_one_day_past_the_last_covered_day_is_not_assessed():
    """The other side of the same comparison, so the pair pins the operator
    rather than only the direction. The next payday's deadline sits past the
    coverage end, where the table can be missing a holiday that shifts it,
    and the verdict is no longer owed."""
    cal = load_calendar()
    assert cal.coverage_until == date(2027, 8, 31)

    line = ContribLine(
        employee_id="E9",
        qe_day=date(2027, 8, 23),
        sg_amount=Decimal("500.00"),
        received=date(2027, 9, 7),
        row=2,
    )
    r = assess([line], cal, load_gic(), date(2027, 9, 15))[0]
    assert r.deadline.due == date(2027, 9, 1)
    assert r.deadline.due > cal.coverage_until
    assert r.verdict == "UNKNOWN"
    assert r.horizon_verdicts == ("LATE", "ON_TIME")
    assert r.days_late is None


def test_a_deadline_inside_the_horizon_is_still_assessed():
    """The override only fires past verified_until, not before it."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2027, 8, 2),
        sg_amount=Decimal("500.00"),
        received=date(2027, 8, 20),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), date(2027, 9, 1))[0]
    assert r.verdict == "LATE"
    assert r.final_shortfall == Decimal("0")


def test_prepayment_past_the_horizon_keeps_its_verdict():
    """s 18C(1)(c)(ii) compares the receipt with the QE day and a 12-month
    calendar window, never with the business-day deadline, so the horizon
    cannot make that verdict unknowable."""
    line = _past_horizon_line(received=date(2028, 12, 1))
    r = assess([line], load_calendar(), load_gic(), date(2029, 4, 1))[0]
    assert r.verdict == "ON_TIME"


def test_unfunded_payday_past_the_horizon_is_attention_driving_unknown():
    """Without the missing holiday facts, the real deadline may not have
    passed. An unfunded row therefore cannot carry an UNPAID exposure."""
    cal = load_calendar()
    line = ContribLine(
        employee_id="HORIZON-UNFUNDED",
        qe_day=date(2027, 9, 16),
        sg_amount=Decimal("1000.00"),
        row=2,
    )

    r = assess([line], cal, load_gic(), date(2027, 9, 28))[0]

    assert r.deadline.due > cal.coverage_until
    assert r.verdict == "UNKNOWN"
    assert r.horizon_verdicts == ("UNPAID", "NOT_YET_DUE")
    assert r.final_shortfall is None
    assert r.nec is None
    assert r.sgc_low is None and r.sgc_high is None
    assert needs_attention([r])


def test_stale_prepayment_past_the_horizon_has_no_exposure():
    """A stale pre-payment leaves the payday unfunded, but it still cannot
    prove a post-horizon deadline has passed."""
    cal = load_calendar()
    line = ContribLine(
        employee_id="HORIZON-STALE",
        qe_day=date(2027, 9, 16),
        sg_amount=Decimal("1000.00"),
        received=date(2026, 9, 1),
        row=2,
    )

    r = assess([line], cal, load_gic(), date(2027, 9, 28))[0]

    assert r.verdict == "UNKNOWN"
    assert r.horizon_verdicts == ("LATE", "NOT_YET_DUE")
    assert r.final_shortfall is None
    assert r.nec is None
    assert r.sgc_low is None and r.sgc_high is None
    assert needs_attention([r])


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
    assert "beyond the calendar's coverage (2027-08-31" in printed

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
    """An unfunded row stays attention-driving, but the tool cannot assert
    UNPAID until it knows the deadline has passed.

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
    assert "UNPAID: 0" in printed
    assert "UNKNOWN: 1" in printed
    assert "UNPAID or NOT_YET_DUE" in printed
    assert "the deadline passed on" not in printed
    assert "may not have passed" in printed


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
    later = results[1]
    assert later.deadline.due == date(2026, 8, 4)
    assert later.deadline.possible_item4_due == date(2026, 8, 7)
    assert later.verdict == "UNKNOWN"
    assert later.horizon_verdicts == ("LATE", "ON_TIME")
    assert needs_attention([later])
    assert any("does not evidence an eligible contribution" in c for c in later.caveats)


def test_partial_on_time_receipt_respects_an_unresolved_item4_deadline():
    rows = [
        ContribLine(
            employee_id="E-PART-ITEM4",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("100.00"),
            first_to_fund=True,
            row=2,
        ),
        ContribLine(
            employee_id="E-PART-ITEM4",
            qe_day=date(2026, 7, 23),
            sg_amount=Decimal("100.00"),
            remitted=date(2026, 8, 3),
            remitted_amount=Decimal("60.00"),
            received=date(2026, 8, 4),
            row=3,
        ),
    ]
    later = assess(
        rows, load_calendar(), load_gic(), date(2026, 8, 5)
    )[1]
    assert later.deadline.due == date(2026, 8, 4)
    assert later.deadline.possible_item4_due == date(2026, 8, 7)
    assert later.verdict == "UNKNOWN"
    assert later.horizon_verdicts == ("UNPAID", "NOT_YET_DUE")
    assert later.base_shortfall is None
    assert later.final_shortfall is None


def test_partial_receipt_inside_an_unresolved_item4_window_keeps_outer_bounds():
    rows = [
        ContribLine(
            employee_id="E-PART-ITEM4-LATE",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("100.00"),
            first_to_fund=True,
            row=2,
        ),
        ContribLine(
            employee_id="E-PART-ITEM4-LATE",
            qe_day=date(2026, 7, 23),
            sg_amount=Decimal("100.00"),
            remitted=date(2026, 8, 5),
            remitted_amount=Decimal("60.00"),
            received=date(2026, 8, 6),
            row=3,
        ),
    ]
    later = assess(
        rows, load_calendar(), load_gic(), date(2026, 8, 6)
    )[1]
    assert later.deadline.due == date(2026, 8, 4)
    assert later.deadline.possible_item4_due == date(2026, 8, 7)
    assert later.verdict == "UNKNOWN"
    assert later.horizon_verdicts == ("LATE", "NOT_YET_DUE")
    assert any("UNPAID" in caveat for caveat in later.caveats)


def test_partial_item4_receipt_after_the_upper_deadline_has_no_not_yet_due_state():
    rows = [
        ContribLine(
            employee_id="E-PART-ITEM4-PAST",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("100.00"),
            first_to_fund=True,
            row=2,
        ),
        ContribLine(
            employee_id="E-PART-ITEM4-PAST",
            qe_day=date(2026, 7, 23),
            sg_amount=Decimal("100.00"),
            remitted=date(2026, 8, 5),
            remitted_amount=Decimal("60.00"),
            received=date(2026, 8, 6),
            row=3,
        ),
    ]
    later = assess(rows, load_calendar(), load_gic(), date(2026, 8, 10))[1]
    assert later.deadline.due == date(2026, 8, 4)
    assert later.deadline.possible_item4_due == date(2026, 8, 7)
    assert later.verdict == "UNKNOWN"
    assert later.horizon_verdicts == ("LATE", "UNPAID")
    assert later.base_shortfall is None
    assert later.final_shortfall is None
    assert needs_attention([later])


def test_zero_amount_receipt_cannot_seed_item4_but_positive_partial_can(tmp_path):
    def later_result(amount: str):
        path = tmp_path / f"item4-{amount}.csv"
        path.write_text(
            "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
            "first_contribution_to_fund,out_of_cycle,next_standard_payday,"
            "defined_benefit,remitted_amount\n"
            f"E-ZERO-ITEM4,2026-07-09,100.00,2026-07-14,2026-07-15,yes,no,,no,{amount}\n"
            "E-ZERO-ITEM4,2026-07-23,100.00,2026-08-05,2026-08-06,no,no,,no,100.00\n",
            encoding="utf-8",
        )
        lines = parse_rows(path, *load_mapping(None))
        return assess(lines, load_calendar(), load_gic(), date(2026, 8, 10))[1]

    zero = later_result("0.00")
    assert zero.deadline.due == date(2026, 8, 4)
    assert zero.deadline.pathway == "USUAL_7BD"
    assert zero.verdict == "LATE"

    positive = later_result("1.00")
    assert positive.deadline.due == date(2026, 8, 7)
    assert positive.deadline.pathway == "ITEM4_ALIGNED"
    assert positive.verdict == "ON_TIME"


def test_item4_inherited_caveat_survives_a_post_as_at_donor_payment():
    """A known receipt after the earlier row's latest day cannot seed item
    4. An on-time fund receipt can."""
    cal = load_calendar()
    rows = [
        ContribLine(
            employee_id="E9",
            qe_day=date(2026, 7, 9),
            sg_amount=Decimal("100.00"),
            received=date(2026, 9, 1),
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
    assert results[1].deadline.due == date(2026, 8, 4)
    assert results[1].deadline.possible_item4_due is None
    assert results[1].verdict == "LATE"
    # An eligible receipt associated with the earlier QE day settles it.
    rows[0].received = date(2026, 8, 6)
    results = assess(rows, cal, load_gic(), AS_AT)
    assert results[1].deadline.due == date(2026, 8, 7)
    assert results[1].deadline.pathway == "ITEM4_ALIGNED"
    assert results[1].verdict == "ON_TIME"


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
    later = results[2]
    assert later.deadline.pathway == "USUAL_7BD"
    assert later.deadline.due == date(2026, 8, 4)
    assert later.deadline.possible_item4_due == date(2026, 8, 7)
    assert later.verdict == "UNKNOWN"
    assert later.horizon_verdicts == ("LATE", "ON_TIME")


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
    """An unfunded payday past the calendar's coverage needs attention, but
    carries no exposure until the deadline can be established."""
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2029, 3, 1),
        sg_amount=Decimal("500.00"),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), date(2029, 6, 1))[0]
    assert r.verdict == "UNKNOWN"
    assert r.horizon_verdicts == ("UNPAID", "NOT_YET_DUE")
    assert r.days_late is None
    assert r.nec is None
    assert r.sgc_low is None and r.sgc_high is None

    text = console_summary(
        [r], date(2029, 6, 1), "report.csv", "2026-08-02", load_rates()
    )
    assert "cannot be assessed" in text
    assert "UNPAID or NOT_YET_DUE" in text
    assert "Lines with exposure" not in text
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
    assert row["verdict"] == "UNKNOWN"
    assert row["days_late"] == ""
    assert row["final_shortfall"] == ""
    assert row["unassessable_between"] == "UNPAID or NOT_YET_DUE"


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
    assert "cannot produce ON_TIME" in text
    assert needs_attention(results)
    assert not needs_attention(results, remittance_only_confirmed=True)


def test_remittance_only_import_check_exits_nonzero_until_confirmed(tmp_path, capsys):
    """Vendor imports never write fund_received_date. A fully remitted file
    is all AT_RISK and used to exit 0, so a scheduled wrapper that alarms
    on exit 2 stayed quiet."""
    src = tmp_path / "contributions.csv"
    src.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "E1,2026-08-06,600.00,2026-08-07,,no,no,,no\n",
        encoding="utf-8",
    )
    out = tmp_path / "report.csv"
    code = main([str(src), "-o", str(out), "--as-at", "2026-08-20"])
    printed = capsys.readouterr().out
    assert code == EXIT_LATE_FOUND
    assert "cannot produce ON_TIME" in printed
    assert "AT_RISK: 1" in printed

    code = main(
        [
            str(src),
            "-o",
            str(tmp_path / "report2.csv"),
            "--as-at",
            "2026-08-20",
            "--confirm-remittance-only",
        ]
    )
    printed = capsys.readouterr().out
    assert code == EXIT_OK
    assert "Operator confirmed remittance-only review" in printed


def test_a_file_with_any_fund_receipt_is_not_remittance_only(tmp_path, capsys):
    src = tmp_path / "contributions.csv"
    src.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "E1,2026-08-06,600.00,2026-08-07,2026-08-10,no,no,,no\n"
        "E2,2026-08-06,318.00,2026-08-11,,no,no,,no\n",
        encoding="utf-8",
    )
    code = main([str(src), "-o", str(tmp_path / "report.csv"), "--as-at", "2026-08-20"])
    printed = capsys.readouterr().out
    assert code == EXIT_OK
    assert "cannot produce ON_TIME" not in printed
    assert "ON_TIME: 1" in printed
    assert "AT_RISK: 1" in printed


def test_receipts_after_the_as_at_date_are_still_remittance_only(tmp_path, capsys):
    """A receipt the run discards as future proves nothing about receipt by
    the fund, so it must not defeat the gate. Two files with identical usable
    evidence used to exit 2 and 0 purely because one had the column filled."""
    populated = tmp_path / "populated.csv"
    populated.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "E1,2026-08-06,600.00,2026-08-14,2026-08-17,no,no,,no\n"
        "E2,2026-08-06,318.00,2026-08-14,2026-08-17,no,no,,no\n",
        encoding="utf-8",
    )
    code = main([str(populated), "-o", str(tmp_path / "a.csv"), "--as-at", "2026-08-15"])
    printed = capsys.readouterr().out
    assert code == EXIT_LATE_FOUND
    assert "AT_RISK: 2" in printed
    assert "cannot produce ON_TIME" in printed

    blank = tmp_path / "blank.csv"
    blank.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "E1,2026-08-06,600.00,2026-08-14,,no,no,,no\n"
        "E2,2026-08-06,318.00,2026-08-14,,no,no,,no\n",
        encoding="utf-8",
    )
    blank_code = main([str(blank), "-o", str(tmp_path / "b.csv"), "--as-at", "2026-08-15"])
    capsys.readouterr()
    assert blank_code == code

    # The confirmation flag still gets the operator to exit 0, and the same
    # run reaching the receipt date decides it normally.
    assert (
        main(
            [
                str(populated),
                "-o",
                str(tmp_path / "c.csv"),
                "--as-at",
                "2026-08-15",
                "--confirm-remittance-only",
            ]
        )
        == EXIT_OK
    )
    assert (
        main([str(populated), "-o", str(tmp_path / "d.csv"), "--as-at", "2026-08-20"])
        == EXIT_OK
    )
    assert "ON_TIME: 2" in capsys.readouterr().out


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


def test_every_formula_lead_is_neutralised_after_whitespace():
    """Alphanumeric suffixes are not proof that a value is inert.

    Spreadsheet engines can reinterpret scientific notation, booleans, R1C1
    references and workbook-defined names. The output is the safe review
    artefact; the source payroll export retains the unmodified identifier.
    """
    from paydaysuper.report import csv_safe

    for value in (
        "-A1", "+B12", "@AA100", "-a1", "-ZZ1048576", "+1E3",
        "-R1C1", "+TRUE", "-FALSE", "+SUM", "-00123", "@home", "+GST",
        "-a_b",
    ):
        assert csv_safe(value) == "'" + value, f"{value!r} was left live"
    for value in (" =cmd|'/c calc'!A1", "\t+cmd|'/c calc'!A1", " -A1"):
        assert csv_safe(value) == "'" + value, f"{value!r} was left live"
    for value in ("E9", "00123", "home", "GST", "a_b", ""):
        assert csv_safe(value) == value, f"{value!r} was mangled"


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
    assert r.verdict == "UNKNOWN"
    assert r.horizon_verdicts == ("LATE", "NOT_YET_DUE")
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


@pytest.mark.parametrize(
    ("kwargs", "unfunded"),
    [
        # A partial fund receipt: only $400 of the $1000 is evidenced as
        # received, so the extended deadline leaves $600 exposed.
        (
            {
                "remitted": date(2026, 8, 14),
                "remitted_amount": Decimal("400.00"),
                "matched_amount": Decimal("400.00"),
                "received": date(2026, 8, 19),
            },
            "600.00",
        ),
        # A partial remittance with no receipt at all: remittance establishes
        # no statutory credit, so the whole liability stays unfunded and
        # AT_RISK (which requires a full remittance) is out of reach too.
        (
            {
                "remitted": date(2026, 8, 19),
                "remitted_amount": Decimal("400.00"),
            },
            "1000.00",
        ),
    ],
)
def test_new_starter_hint_promises_no_verdict_on_partial_evidence(kwargs, unfunded):
    """Setting the flag on a part-funded row moves the deadline and nothing
    else: ON_TIME needs a full fund receipt and AT_RISK needs a full
    remittance, so the hint must not claim either."""
    line = ContribLine(
        employee_id="EMP1",
        qe_day=date(2026, 8, 6),
        sg_amount=Decimal("1000.00"),
        row=2,
        **kwargs,
    )
    as_at = date(2026, 9, 25)
    r = assess([line], load_calendar(), load_gic(), as_at)[0]
    hint = [c for c in r.caveats if "first_contribution_to_fund" in c]
    assert hint
    assert "becomes on time" not in hint[0]
    assert "stays at risk" not in hint[0]
    assert f"${unfunded} of $1000.00 still has no evidenced fund receipt" in hint[0]

    # What the operator would actually get, so the caveat is checked against
    # the run it describes rather than against itself.
    flagged = ContribLine(
        employee_id="EMP1",
        qe_day=date(2026, 8, 6),
        sg_amount=Decimal("1000.00"),
        first_to_fund=True,
        row=2,
        **kwargs,
    )
    actual = assess([flagged], load_calendar(), load_gic(), as_at)[0]
    assert actual.deadline.due == date(2026, 9, 3)
    assert actual.verdict == "UNPAID"
    assert actual.final_shortfall == Decimal(unfunded)


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
    later = results[1]
    caveat = [c for c in later.caveats if "item 4" in c]
    assert later.deadline.due == date(2026, 8, 4)
    assert later.deadline.possible_item4_due == date(2026, 8, 7)
    assert caveat and "2026-08-07" in caveat[0]


def test_item4_caveat_keeps_an_out_of_cycle_lines_own_deadline():
    """The unresolved line keeps its evidenced item 2 deadline, rather than
    replacing it with an unevidenced item 4 extension."""
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
    later = results[1]
    assert later.deadline.pathway == "OUT_OF_CYCLE"
    assert later.deadline.due == date(2026, 8, 6)
    assert later.deadline.possible_item4_due == date(2026, 8, 7)
    assert later.verdict == "UNKNOWN"
    caveat = [c for c in later.caveats if "item 4" in c]
    assert caveat and "2026-08-07" in caveat[0]


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


def test_formula_leading_employee_ids_are_quoted_in_the_report(tmp_path):
    """The source export, rather than the review CSV, retains the raw id."""
    path = tmp_path / "pay.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "-00123,2026-07-09,100.00,,2026-07-15,no,no,,no\n",
        encoding="utf-8",
    )
    out = tmp_path / "r.csv"
    main([str(path), "-o", str(out), "--as-at", "2026-08-10"])
    assert ",'-00123," in out.read_text(encoding="utf-8")


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
    assert "2026-08-15" in note["notes"]
    assert note["unassessable_between"] == ""


def test_an_unpaid_row_does_not_claim_no_date_when_one_was_supplied():
    # ROUND 9. assess() filters out dates later than the as-at date and says so
    # in one caveat, then the UNPAID branch asserted flatly that no remittance
    # or fund-receipt date "is recorded" and told the reader to supply date
    # columns they had already supplied. The AT_RISK branch above already
    # varies its wording for exactly this case; these two did not.
    line = ContribLine(
        employee_id="E9",
        qe_day=date(2026, 7, 9),
        sg_amount=Decimal("300.00"),
        remitted=date(2026, 8, 18),
        received=date(2026, 8, 20),
        row=2,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]

    assert r.verdict == "UNPAID"
    assert any("ignored for this as-at report" in w for w in r.warnings)
    assert not any("no remittance or fund-receipt date is recorded" in w for w in r.warnings)
    assert any("is after the as-at date and is ignored here" in w for w in r.warnings)


def test_a_not_yet_due_row_does_not_claim_no_date_when_one_was_supplied():
    line = ContribLine(
        employee_id="E10",
        qe_day=AS_AT,
        sg_amount=Decimal("300.00"),
        received=AS_AT + timedelta(days=10),
        row=3,
    )
    r = assess([line], load_calendar(), load_gic(), AS_AT)[0]

    assert not any("no remittance or fund-receipt date supplied" in w for w in r.warnings)
    assert any("is after the as-at date and is ignored here" in w for w in r.warnings)


def test_check_reports_error_when_figures_outgrow_the_decimal_context(
    tmp_path, capsys, monkeypatch
):
    # decimal.InvalidOperation is an ArithmeticError, not a ValueError, so it
    # was invisible to both of main()'s handlers. This is the verified way to
    # raise one from accepted input: a hand-edited GIC rate of 15% a year
    # (well under the 100% ceiling), an sg_amount at the largest magnitude
    # _parse_amount accepts (adjusted() == 15), and an --as-at inside
    # LATEST_SANE_YEAR. Notional earnings compound daily on the shortfall for
    # 174 years, and quantising the result to cents in write_csv then needs
    # more than the default decimal context's 28 significant digits.
    import shutil

    from paydaysuper import rates as rates_module

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "gic_rates.json").write_text(
        json.dumps(
            {"quarters": [{"from": "2026-07-01", "to": "2026-09-30", "annual_pct": 15}]}
        ),
        encoding="utf-8",
    )
    shutil.copy(rates_module.DATA_DIR / "rates.json", data_dir / "rates.json")
    monkeypatch.setattr(rates_module, "DATA_DIR", data_dir)

    src = tmp_path / "contributions.csv"
    src.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date\n"
        "EMP001,2026-08-03,9999999999999999,,\n",
        encoding="utf-8",
    )
    out = tmp_path / "report.csv"
    code = main([str(src), "-o", str(out), "--as-at", "2200-12-31"])

    assert code == EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.err.startswith("error:")
    assert "Traceback" not in captured.err
    assert not out.exists()


def test_check_reports_error_when_totals_outgrow_the_decimal_context(
    tmp_path, capsys, monkeypatch
):
    # The multi-row variant of the test above, pinning the summary stage.
    # Twenty rows at sg_amount 99999999999999 each grow figures that STILL
    # quantise to cents inside write_csv (the per-row magnitudes stay within
    # the default context's 28 significant digits), so the report is written
    # in full -- and then console_summary sums them and money() quantises a
    # TOTAL that no longer fits. Without the summary block's own backstop,
    # that raised a raw decimal.InvalidOperation after the CSV was already
    # on disk: the crash moved one stage later instead of being caught.
    import shutil

    from paydaysuper import rates as rates_module

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "gic_rates.json").write_text(
        json.dumps(
            {"quarters": [{"from": "2026-07-01", "to": "2026-09-30", "annual_pct": 15}]}
        ),
        encoding="utf-8",
    )
    shutil.copy(rates_module.DATA_DIR / "rates.json", data_dir / "rates.json")
    monkeypatch.setattr(rates_module, "DATA_DIR", data_dir)

    src = tmp_path / "contributions.csv"
    src.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date\n"
        + "".join(f"EMP{n:03d},2026-08-03,99999999999999,,\n" for n in range(1, 21)),
        encoding="utf-8",
    )
    out = tmp_path / "report.csv"
    code = main([str(src), "-o", str(out), "--as-at", "2200-12-31"])

    assert code == EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.err.startswith("error:")
    assert "Traceback" not in captured.err
    # Unlike the single-row case, the report survives: write_csv finished
    # before the summary failed, and the message says so.
    assert out.exists()
    assert str(out) in captured.err


def test_check_catches_arithmetic_error_from_assessment(tmp_path, capsys, monkeypatch):
    # The same backstop, for the assessment block: mirrors test_importers.
    # test_import_catches_arithmetic_error_from_import_files by forcing the
    # case directly, so the guard holds even if every real route to it is
    # closed one day.
    from decimal import InvalidOperation

    import paydaysuper.cli as cli_module

    def _boom(*args, **kwargs):
        raise InvalidOperation("synthetic failure for the CLI's own guard")

    monkeypatch.setattr(cli_module, "assess", _boom)

    code = main([str(FIXTURE), "-o", str(tmp_path / "out.csv"), "--as-at", "2026-08-10"])

    assert code == EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.err.startswith("error:")
    assert "Traceback" not in captured.err


def test_defaulted_as_at_is_named_in_a_notice(tmp_path, capsys):
    # A defaulted as-at comes from the host clock, and the host clock's
    # calendar day is not necessarily the Australian date: a UTC server in
    # the hours around midnight AEST is a day behind, and a deadline
    # verdict turns on exactly that day. The reader already refuses
    # UTC-marked datetime inputs for this reason, so the one date this
    # tool assumes on its own must at least be named, not silently used.
    path = tmp_path / "contributions.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "E1,2026-08-06,600.00,2026-08-07,2026-08-10,no,no,,no\n",
        encoding="utf-8",
    )
    out = tmp_path / "report.csv"

    code = main([str(path), "-o", str(out)])

    assert code in (EXIT_OK, EXIT_LATE_FOUND)
    err = capsys.readouterr().err
    assert "note: --as-at not supplied; assuming" in err
    assert date.today().isoformat() in err
    assert "machine's clock" in err


def test_an_explicit_as_at_prints_no_default_notice(tmp_path, capsys):
    # Teeth for the test above: the notice belongs to the DEFAULT only. An
    # operator who supplied the date already owns the assumption, and a
    # notice on every run would train everyone to ignore it.
    path = tmp_path / "contributions.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        "E1,2026-08-06,600.00,2026-08-07,2026-08-10,no,no,,no\n",
        encoding="utf-8",
    )
    out = tmp_path / "report.csv"

    code = main([str(path), "-o", str(out), "--as-at", "2026-09-10"])

    assert code in (EXIT_OK, EXIT_LATE_FOUND)
    err = capsys.readouterr().err
    assert "--as-at not supplied" not in err
