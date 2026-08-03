import csv as _csv
import itertools
import random
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from paydaysuper.cli import EXIT_LATE_FOUND, EXIT_OK
from paydaysuper.cli import main as cli_main
from paydaysuper.csv_io import CsvError, DEFAULT_MAPPING, parse_rows
from paydaysuper.importers import (
    CANONICAL_HEADER,
    ORPHAN_NO_AMOUNT,
    ORPHAN_NO_PAYDAY,
    ORPHAN_NOTHING_OWED,
    ORPHAN_PAYDAYS_SETTLED,
    OUTCOME_MATCHED,
    OUTCOME_OVER,
    OUTCOME_OWES_NOTHING,
    OUTCOME_PARTIAL,
    OUTCOME_UNDATED,
    OUTCOME_UNMATCHED,
    ImportReport,
    PayrollRow,
    SuperRow,
    import_files,
    join,
    read_payroll,
    read_super,
    write_canonical,
)

FIXTURES = Path(__file__).parent / "fixtures" / "importers"


def test_read_super_keeps_only_super_guarantee():
    rows, profile, _ = read_super(FIXTURES / "myob_super.csv")
    assert profile.key == "myob-ar-super"
    assert len(rows) == 2, "salary sacrifice row was not excluded"
    assert {r.amount for r in rows} == {Decimal("612.00"), Decimal("540.00")}


def test_read_super_reads_australian_day_first_dates():
    rows, _, _ = read_super(FIXTURES / "myob_super.csv")
    assert rows[0].paid_date == date(2026, 7, 14)
    assert rows[0].period_end == date(2026, 7, 9)


def test_read_super_surfaces_the_resolved_columns_for_this_file():
    # import_files derives join()'s payroll_has_period_end/
    # super_has_period_start/super_has_period_end from exactly this: which
    # canonical fields resolve_columns found headings for in THIS file, not
    # a per-row fact. The myob-ar-super fixture has both period columns.
    _, _, resolved = read_super(FIXTURES / "myob_super.csv")
    assert resolved["period_start"] == "Period From"
    assert resolved["period_end"] == "Period To"


def test_read_payroll_reads_payday_and_amount():
    rows, profile, _ = read_payroll(FIXTURES / "myob_payroll.csv")
    assert profile.key == "myob-ar-payroll"
    assert rows[0].payday == date(2026, 7, 9)
    assert rows[0].sg_amount == Decimal("612.00")


def test_read_payroll_surfaces_the_resolved_columns_for_this_file():
    _, _, resolved = read_payroll(FIXTURES / "myob_payroll.csv")
    assert resolved["period_end"] == "Pay Period End"


def test_read_payroll_resolved_columns_omit_an_absent_period_end(tmp_path):
    # A payroll file with no pay period end column at all must not resolve
    # one: import_files reads its absence from here to warn through join's
    # payroll_has_period_end, and a false positive would silence that
    # warning on a file that actually needs it.
    path = tmp_path / "no_period_end.csv"
    path.write_text(
        "Employee Name,Date,Superannuation Guarantee\n"
        "Test Employee One,09/07/2026,612.00\n",
        encoding="utf-8",
    )
    _, _, resolved = read_payroll(path, vendor="myob-ar-payroll")
    assert "period_end" not in resolved


def test_super_file_without_a_contribution_type_column_is_refused(tmp_path):
    # Summing every contribution type would fold salary sacrifice into the SG
    # figure and understate the shortfall.
    path = tmp_path / "no_type.csv"
    path.write_text(
        "Employee Name,Period From,Period To,Paid Date,Amount\n"
        "Test Employee One,01/07/2026,09/07/2026,14/07/2026,612.00\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError) as exc:
        read_super(path, vendor="myob-ar-super")
    message = str(exc.value).lower()
    assert "contribution type" in message
    # The no-SG-rows fallback message also contains "contribution type" as a
    # substring of "contribution types", so that alone would pass even with
    # the missing-column guard deleted (the row's blank contribution-type
    # cell fails the SG filter and rows ends up empty either way). Pin the
    # guard's own wording so this test actually exercises the guard.
    assert "no contribution type column" in message


def test_mis_grouped_amount_is_refused(tmp_path):
    path = tmp_path / "bad_amount.csv"
    path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "Test Employee One,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,\"612,00\"\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError):
        read_super(path, vendor="myob-ar-super")


def test_misaligned_row_is_refused_not_silently_shifted():
    # Reproduces a real MYOB export shape: an unescaped comma inside an
    # employee name shifts every later column one place left. Without a
    # guard, the true amount (612.00) lands in the discarded surplus
    # bucket, the contribution-type cell reads "Employee One" instead of
    # "Superannuation Guarantee", the SG filter drops the row as not-SG,
    # and read_super silently returns one row and $100.00 instead of two
    # rows and $712.00 -- an understated shortfall with no exception at
    # all. This must be refused outright instead.
    with pytest.raises(CsvError) as exc:
        read_super(FIXTURES / "myob_super_misaligned.csv", vendor="myob-ar-super")
    message = str(exc.value)
    assert "row 3" in message
    assert "612.00" in message  # the shifted amount, named as a surplus value


def test_truncated_row_is_refused_not_read_as_blank(tmp_path):
    # A row that stops early (fewer fields than the header) is not the
    # same as a row whose trailing cell is genuinely blank: without a
    # guard, csv.DictReader's default restval silently reads the missing
    # Amount as None, and downstream code cannot tell "blank" from "the
    # export was cut off here".
    path = tmp_path / "truncated.csv"
    path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "Test Employee One,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError) as exc:
        read_super(path, vendor="myob-ar-super")
    message = str(exc.value)
    assert "row 2" in message
    assert "Amount" in message


def test_duplicate_header_refused_even_when_profile_never_maps_it(tmp_path):
    # test_duplicate_normalised_headers_are_refused collides on a heading
    # the profile does map ("Superannuation Guarantee"), so it would pass
    # just as well if the guard only checked resolved/mapped fields. Two
    # "Notes" columns that no MYOB profile maps at all prove the check runs
    # over the whole header row, not only the fields resolve_columns cares
    # about.
    path = tmp_path / "dup_unmapped.csv"
    path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount,Notes,Notes\n"
        "Test Employee One,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,612.00,foo,bar\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError) as exc:
        read_super(path, vendor="myob-ar-super")
    assert "notes" in str(exc.value).lower()


def test_duplicate_normalised_headers_are_refused(tmp_path):
    # "Superannuation Guarantee" and "Superannuation  Guarantee" (extra
    # space) are different literal strings, so csv_io.py's exact-match
    # duplicate check would let them both through, and resolve_columns
    # (via profiles._index) would silently keep whichever came first. That
    # means the 612.00 read here could just as easily have been the 999.00
    # in the other column, with nothing to say which one happened. Two
    # columns colliding under normalise_header must be refused outright,
    # not resolved by picking one.
    path = tmp_path / "dup_headers.csv"
    path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee,Superannuation  Guarantee\n"
        "Test Employee One,09/07/2026,09/07/2026,612.00,999.00\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError) as exc:
        read_payroll(path, vendor="myob-ar-payroll")
    assert "superannuation guarantee" in str(exc.value).lower()


def payroll(name, payday, amount, period_end=None, row=2):
    return PayrollRow(None, name, date.fromisoformat(payday),
                      date.fromisoformat(period_end) if period_end else None,
                      Decimal(amount), row)


def super_row(name, start, end, paid, amount, row=2):
    return SuperRow(None, name, date.fromisoformat(start), date.fromisoformat(end),
                    date.fromisoformat(paid) if paid else None, Decimal(amount), row)


def test_exact_match_sets_the_remittance_date():
    result = join([payroll("A", "2026-07-09", "612.00")],
                  [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00")])
    assert result.outcomes[0].remitted == date(2026, 7, 14)
    assert result.outcomes[0].flag == ""
    assert result.orphans == []


def test_split_payment_takes_the_later_date():
    # The obligation is not met until the whole amount reaches the fund.
    # Listed with the later paid date FIRST: a "last in the list" mutation
    # of the max() selection would pick 07-14 here, not 07-21, so the
    # ordering has to be adversarial to the mutation, not just the fixture
    # happening to already be in ascending order.
    result = join([payroll("A", "2026-07-09", "612.00")],
                  [super_row("A", "2026-07-01", "2026-07-09", "2026-07-21", "312.00", row=2),
                   super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "300.00", row=3)])
    assert result.outcomes[0].remitted == date(2026, 7, 21)
    assert result.outcomes[0].flag == ""


def test_short_payment_is_flagged_partial():
    result = join([payroll("A", "2026-07-09", "612.00")],
                  [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "500.00")])
    assert "partial" in result.outcomes[0].flag
    assert "500.00" in result.outcomes[0].flag and "612.00" in result.outcomes[0].flag


def test_overpayment_is_flagged():
    result = join([payroll("A", "2026-07-09", "612.00")],
                  [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "812.00")])
    assert "over" in result.outcomes[0].flag


def test_payday_with_no_super_payment_is_flagged_and_left_blank():
    result = join([payroll("A", "2026-07-09", "612.00")], [])
    assert result.outcomes[0].remitted is None
    assert result.outcomes[0].flag == "no super payment found"


def test_super_payment_matching_nothing_becomes_an_orphan():
    result = join([payroll("A", "2026-07-09", "612.00")],
                  [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00"),
                   super_row("B", "2026-07-01", "2026-07-09", "2026-07-14", "99.00", row=3)])
    assert [o.row for o in result.orphans] == [3]


def test_two_identical_paydays_refuse_rather_than_guess():
    # Assigning the payment to the wrong one moves the exposure to a
    # different deadline.
    with pytest.raises(CsvError) as exc:
        join([payroll("A", "2026-07-09", "612.00", row=2),
              payroll("A", "2026-07-09", "612.00", row=3)],
             [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00")])
    assert "rows 2, 3" in str(exc.value)


def test_name_matching_warns():
    result = join([payroll("A", "2026-07-09", "612.00")],
                  [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00")])
    assert result.key_mode == "name"
    assert any("name" in w for w in result.warnings)


def _by_row(result):
    return {o.payroll.row: o for o in result.outcomes}


def test_a_super_row_bracketing_two_paydays_apportions_oldest_first():
    # Round-2's ruling was "refuse rather than guess" here. The owner
    # changed that ruling: this shape is the ordinary monthly/quarterly
    # remittance an employer who pays fortnightly produces routinely, and a
    # checker that aborts on the single most common cadence in Australian
    # payroll tells that employer nothing. Reworked reproduction A: super
    # 300.00 covering paydays 2026-07-09 (sg 612.00) and 2026-07-23
    # (sg 540.00). Oldest-first apportionment gives the whole 300.00 to the
    # 9 July row (a partial, since 300.00 < 612.00) and nothing is left for
    # 23 July, which is flagged unpaid rather than silently dropped. This
    # must hold identically regardless of which order the two payroll rows
    # are passed to join in -- the ordering that decides the outcome is the
    # sort inside join, never the caller's list order.
    for payroll_rows in (
        [payroll("A", "2026-07-09", "612.00", row=2), payroll("A", "2026-07-23", "540.00", row=3)],
        [payroll("A", "2026-07-23", "540.00", row=3), payroll("A", "2026-07-09", "612.00", row=2)],
    ):
        result = join(
            payroll_rows,
            [super_row("A", "2026-07-01", "2026-07-31", "2026-08-28", "300.00", row=2)],
        )
        outcomes = _by_row(result)
        assert outcomes[2].remitted == date(2026, 8, 28)
        assert "partial: 300.00 of 612.00 matched" in outcomes[2].flag
        # The note names the specific super row, its own amount, and its
        # paid date -- not just a bare count -- and says how many paydays
        # were actually competing for it (2: both rows had a balance when
        # this payment was processed, even though only one got paid).
        assert "300.00 of 300.00 allocated from super row 2" in outcomes[2].flag
        assert "paid 2026-08-28" in outcomes[2].flag
        assert "one of 2 paydays" in outcomes[2].flag
        assert outcomes[3].remitted is None
        assert outcomes[3].flag == "no super payment found"
        assert result.orphans == []


def test_ambiguous_coverage_apportions_deterministically_regardless_of_amount():
    # Reworked reproduction B: rows 612.00 (row 2) and 500.00 (row 3) share
    # a payday and period end, one 612.00 super payment covers both.
    # Matching never looks at amount, so the tie between them is broken by
    # row number (the payroll row's position in its own file, not by
    # whichever order the two rows happen to be passed to join in) -- row 2
    # always wins the payment in full, row 3 is always left unpaid, and
    # neither list order ever manufactures a false "over:" flag.
    for payroll_rows in (
        [payroll("A", "2026-07-09", "612.00", row=2), payroll("A", "2026-07-09", "500.00", row=3)],
        [payroll("A", "2026-07-09", "500.00", row=3), payroll("A", "2026-07-09", "612.00", row=2)],
    ):
        result = join(
            payroll_rows,
            [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00")],
        )
        outcomes = _by_row(result)
        # Exact equality, not a substring check, pins the flag content --
        # a false "over:" would fail these assertions outright rather than
        # slip past a check that also happens to match "over" inside
        # "covering".
        assert outcomes[2].remitted == date(2026, 7, 14)
        assert outcomes[2].flag == (
            "612.00 of 612.00 allocated from super row 2 (paid 2026-07-14), "
            "one of 2 paydays that payment covered"
        )
        assert outcomes[3].remitted is None
        assert outcomes[3].flag == "no super payment found"


def test_one_payment_covering_three_fortnightly_paydays_is_apportioned_not_aborted():
    # The exact shape the owner's ruling exists to fix: a single monthly
    # remittance settling three fortnightly paydays for one employee. This
    # must not raise -- it must allocate to all three and flag each one
    # with how many paydays the payment covered.
    result = join(
        [payroll("A", "2026-07-09", "600.00", row=2),
         payroll("A", "2026-07-23", "600.00", row=3),
         payroll("A", "2026-08-06", "600.00", row=4)],
        [super_row("A", "2026-07-01", "2026-08-11", "2026-08-15", "1800.00", row=2)],
    )
    outcomes = _by_row(result)
    # Exact equality (not a substring check -- "over" is a substring of
    # both "covering" and "covered") pins the flag content: no partial, no
    # over, just the shared-payment note naming this one payment.
    for row_number in (2, 3, 4):
        assert outcomes[row_number].remitted == date(2026, 8, 15)
        assert outcomes[row_number].flag == (
            "600.00 of 1800.00 allocated from super row 2 (paid 2026-08-15), "
            "one of 3 paydays that payment covered"
        )
    assert result.orphans == []


def test_touching_period_boundaries_pair_cleanly_one_to_one():
    # A normal export convention: one period's end date is repeated as the
    # next period's start date (a fortnight ending 3 July, immediately
    # followed by one starting 3 July). Under inclusive-both-ends coverage,
    # the second super row's period structurally reaches 3 July too, but
    # pass 1 already settles 3 July from the first (single-coverage) super
    # row before pass 2 ever looks at the second one, so 3 July has zero
    # balance left to be fought over and the second payment flows entirely
    # to 10 July. Both rows end up plainly matched, no shared-payment note
    # on either -- only one row was ever actually competing for the second
    # payment's money.
    result = join(
        [payroll("A", "2026-07-03", "612.00", row=2),
         payroll("A", "2026-07-10", "540.00", row=3)],
        [super_row("A", "2026-06-27", "2026-07-03", "2026-07-08", "612.00", row=2),
         super_row("A", "2026-07-03", "2026-07-10", "2026-07-15", "540.00", row=3)],
    )
    outcomes = _by_row(result)
    assert outcomes[2].remitted == date(2026, 7, 8)
    assert outcomes[2].flag == ""
    assert outcomes[3].remitted == date(2026, 7, 15)
    assert outcomes[3].flag == ""
    assert result.orphans == []


def test_two_identical_paydays_without_a_covering_super_payment_are_not_refused():
    # Sharing a payday is not itself ambiguous. Only a single super payment
    # that could actually settle either of them is. With no super row at
    # all here, there is nothing to disambiguate, and refusing anyway would
    # be a false alarm on an unremarkable file.
    result = join([payroll("A", "2026-07-09", "612.00", row=2),
                   payroll("A", "2026-07-09", "612.00", row=3)], [])
    assert result.outcomes[0].flag == "no super payment found"
    assert result.outcomes[1].flag == "no super payment found"


def test_reversed_super_period_is_refused():
    # period_start after period_end is a malformed export, not a real
    # period. Left unchecked, _covers's start <= target <= end check is
    # false for every target, so the payment would silently become an
    # invisible orphan and the payday it actually settled would be flagged
    # as unpaid -- a real payment made to look like a missing one.
    with pytest.raises(CsvError) as exc:
        join([payroll("A", "2026-07-09", "612.00")],
             [super_row("A", "2026-07-09", "2026-07-01", "2026-07-14", "612.00")])
    assert "row 2" in str(exc.value)


def test_split_payment_with_one_undated_row_does_not_report_a_false_settlement():
    # Only part of a split contribution carries a paid date. Reporting the
    # known date as "remitted" would read as fully compliant while part of
    # the money has no evidence of ever reaching the fund -- the deadline
    # tests receipt, and an undated row is not evidence of receipt.
    result = join(
        [payroll("A", "2026-07-09", "612.00")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "300.00", row=2),
         super_row("A", "2026-07-01", "2026-07-09", None, "312.00", row=3)],
    )
    assert result.outcomes[0].remitted is None
    assert "312.00" in result.outcomes[0].flag
    assert "612.00" in result.outcomes[0].flag


def test_all_matched_rows_undated_notes_it_and_leaves_remitted_blank():
    result = join(
        [payroll("A", "2026-07-09", "612.00")],
        [super_row("A", "2026-07-01", "2026-07-09", None, "612.00")],
    )
    assert result.outcomes[0].remitted is None
    assert result.outcomes[0].flag == "matched super rows carry no payment date"


def test_id_matching_is_used_when_every_row_has_an_id():
    p = PayrollRow("E1", "Alice", date(2026, 7, 9), None, Decimal("612.00"), 2)
    s = SuperRow(
        "E1", "Alice", date(2026, 7, 1), date(2026, 7, 9), date(2026, 7, 14),
        Decimal("612.00"), 2,
    )
    result = join([p], [s])
    assert result.key_mode == "id"
    assert result.warnings == []


def test_a_single_blank_id_falls_back_to_name_matching():
    # One employee on either side carries no id at all: matching the whole
    # file on id would be only partly true, so the fallback is all-or-none.
    p1 = PayrollRow("E1", "Alice", date(2026, 7, 9), None, Decimal("612.00"), 2)
    p2 = PayrollRow(None, "Bob", date(2026, 7, 9), None, Decimal("500.00"), 3)
    s1 = SuperRow(
        "E1", "Alice", date(2026, 7, 1), date(2026, 7, 9), date(2026, 7, 14),
        Decimal("612.00"), 2,
    )
    s2 = SuperRow(
        None, "Bob", date(2026, 7, 1), date(2026, 7, 9), date(2026, 7, 14),
        Decimal("500.00"), 3,
    )
    result = join([p1, p2], [s1, s2])
    assert result.key_mode == "name"
    assert any("name" in w for w in result.warnings)


def test_no_super_rows_does_not_vacuously_claim_id_matching():
    # all([]) is True in Python, so without a non-empty guard an empty super
    # list would let id-carrying payroll rows claim key_mode == "id" on no
    # evidence at all from the other file.
    p = PayrollRow("E1", "Alice", date(2026, 7, 9), None, Decimal("612.00"), 2)
    result = join([p], [])
    assert result.key_mode == "name"
    assert any("name" in w for w in result.warnings)


def test_decimal_precision_is_exact_not_float():
    # 0.10 + 0.10 + 0.10 == 0.30 exactly under Decimal. Float arithmetic
    # rounds this to 0.30000000000000004 and would misfire an "over" flag
    # against a payroll amount of 0.30 to the cent.
    result = join(
        [payroll("A", "2026-07-09", "0.30")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "0.10", row=2),
         super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "0.10", row=3),
         super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "0.10", row=4)],
    )
    assert result.outcomes[0].flag == ""


def test_no_payroll_period_end_column_warns():
    # A payroll file with no period_end column at all still joins -- it
    # falls back to the payday -- but the user needs to know a contribution
    # recorded against the pay period rather than the payday could be
    # missed, loudly, not as an unexplained gap.
    result = join(
        [payroll("A", "2026-07-09", "612.00")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00")],
        payroll_has_period_end=False,
    )
    assert any("period" in w and "payday" in w for w in result.warnings)


def test_super_missing_one_period_column_warns():
    result = join(
        [payroll("A", "2026-07-09", "612.00")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00")],
        super_has_period_start=False,
    )
    assert any("single day" in w for w in result.warnings)


def test_super_missing_both_period_columns_warns():
    # An XOR on super_has_period_start != super_has_period_end fires for
    # "only one missing" but stays silent for "both missing" -- passing
    # False for both must still warn, with wording that fits the shape
    # (no period at all, not "collapses to a single day").
    result = join(
        [payroll("A", "2026-07-09", "612.00")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00")],
        super_has_period_start=False,
        super_has_period_end=False,
    )
    assert any("no pay period columns" in w for w in result.warnings)


def test_pay_in_arrears_without_a_period_end_column_misses_silently_unless_warned():
    # A perfectly valid arrears-paid file: the payday lands after the pay
    # period it covers. Without a period_end column the join has only the
    # payday to go on, so a super payment stamped against the earlier pay
    # period is missed -- not a bug in the join, but the user has to be
    # told why, loudly, rather than shown an unexplained gap and an
    # unexplained orphan on a file that has nothing wrong with it.
    result = join(
        [payroll("A", "2026-07-16", "612.00")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00")],
        payroll_has_period_end=False,
    )
    assert result.outcomes[0].flag == "no super payment found"
    assert [o.row for o in result.orphans] == [2]
    assert any("period" in w and "payday" in w for w in result.warnings)


def test_claimed_tracks_object_identity_not_row_number():
    # Two distinct SuperRow objects that happen to carry the same .row
    # value (row numbers are only unique within a single file) must not be
    # conflated: claiming one must not make the other vanish from matching
    # or from orphans.
    s1 = super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "300.00", row=2)
    s2 = super_row("B", "2026-07-01", "2026-07-09", "2026-07-14", "99.00", row=2)
    result = join([payroll("A", "2026-07-09", "300.00")], [s1, s2])
    assert result.outcomes[0].remitted == date(2026, 7, 14)
    assert result.outcomes[0].flag == ""
    assert [o.row for o in result.orphans] == [2]


def test_period_less_super_row_refusal_names_the_super_file_as_the_cause():
    # A period-less super row covering two genuinely-identical payroll rows
    # is refused (same rule as any other indistinguishable pair), but the
    # message must name the super file's missing pay period column(s) as
    # the cause -- it is the reason this row was treated as covering both
    # paydays in the first place -- not tell the user to fix the payroll
    # file, which did nothing wrong.
    s = SuperRow(None, "A", None, None, date(2026, 7, 14), Decimal("612.00"), 2)
    with pytest.raises(CsvError) as exc:
        join(
            [payroll("A", "2026-07-09", "612.00", row=2),
             payroll("A", "2026-07-09", "612.00", row=3)],
            [s],
        )
    message = str(exc.value)
    assert "super file is missing its pay period column" in message
    assert "rows 2, 3" in message


def test_last_known_paid_date_is_kept_when_remitted_is_blanked():
    # Blanking remitted on a partly-undated group is correct, but it must
    # not discard the one date the user does have: MatchOutcome carries it
    # separately, and the flag names it so someone chasing the fund has
    # somewhere to start.
    result = join(
        [payroll("A", "2026-07-09", "612.00")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "300.00", row=2),
         super_row("A", "2026-07-01", "2026-07-09", None, "312.00", row=3)],
    )
    outcome = result.outcomes[0]
    assert outcome.remitted is None
    assert outcome.last_known_paid_date == date(2026, 7, 14)
    assert "2026-07-14" in outcome.flag


def test_last_known_paid_date_is_none_when_nothing_is_dated():
    result = join(
        [payroll("A", "2026-07-09", "612.00")],
        [super_row("A", "2026-07-01", "2026-07-09", None, "612.00")],
    )
    assert result.outcomes[0].last_known_paid_date is None


def test_covers_defends_itself_against_a_period_less_row():
    # _coverage guards the only real call site, so this never fires in
    # practice today, but _covers must not raise TypeError for a future
    # direct caller that hands it a period-less row.
    from paydaysuper.importers import _covers

    s = SuperRow(None, "A", None, None, date(2026, 7, 14), Decimal("612.00"), 2)
    assert _covers(s, date(2026, 7, 9)) is False


def test_global_cap_prevents_a_settled_row_from_starving_another():
    # The review's own reproduction: payroll rows 2 (payday 2026-07-09,
    # sg 600.00) and 3 (payday 2026-07-23, sg 600.00). Super row 2 pays
    # 600.00 covering row 2 only, paid 2026-07-14. Super row 3 pays 600.00
    # covering both, paid 2026-08-28. The employer paid 1200.00 against
    # 1200.00 owed and is fully compliant. A cap local to super row 3 alone
    # (its own sg_amount) would let row 2 -- already settled by super row
    # 2 -- absorb a share of super row 3's money too, manufacturing an
    # over: on row 2 and starving row 3 into a false shortfall. The cap
    # must be against row 2's GLOBAL balance across every super row, which
    # is already zero by the time super row 3 is considered.
    result = join(
        [payroll("A", "2026-07-09", "600.00", row=2),
         payroll("A", "2026-07-23", "600.00", row=3)],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "600.00", row=2),
         super_row("A", "2026-07-01", "2026-07-31", "2026-08-28", "600.00", row=3)],
    )
    outcomes = _by_row(result)
    assert outcomes[2].remitted == date(2026, 7, 14)
    assert outcomes[2].flag == ""
    assert outcomes[3].remitted == date(2026, 8, 28)
    assert outcomes[3].flag == ""


def test_three_period_less_payments_settle_three_fortnightly_paydays_in_full():
    # The worst instance from the review: a super file with no period
    # columns at all, so every payment nominally covers every payday.
    # Three period-less 600.00 payments against three 600.00 fortnightly
    # paydays, paid in full, must settle all three -- not read two of
    # three paid quarters as complete non-payment.
    s1 = SuperRow(None, "A", None, None, date(2026, 7, 14), Decimal("600.00"), 2)
    s2 = SuperRow(None, "A", None, None, date(2026, 7, 28), Decimal("600.00"), 3)
    s3 = SuperRow(None, "A", None, None, date(2026, 8, 11), Decimal("600.00"), 4)
    result = join(
        [payroll("A", "2026-07-09", "600.00", row=2),
         payroll("A", "2026-07-23", "600.00", row=3),
         payroll("A", "2026-08-06", "600.00", row=4)],
        [s1, s2, s3],
    )
    outcomes = _by_row(result)
    for row_number in (2, 3, 4):
        assert outcomes[row_number].flag != "no super payment found"
        assert "partial:" not in outcomes[row_number].flag
        assert "over:" not in outcomes[row_number].flag
    assert outcomes[2].remitted == date(2026, 7, 14)
    assert outcomes[3].remitted == date(2026, 7, 28)
    assert outcomes[4].remitted == date(2026, 8, 11)
    assert result.orphans == []


def test_payday_on_the_periods_own_start_date_matches():
    # The opposite export convention from the touching-boundary case: a
    # period that starts ON the payday it settles (2026-07-09 to
    # 2026-07-22, payday 2026-07-09). The exclusive-start attempt from
    # round 3 dropped this into orphans and read the payday as unpaid;
    # inclusive-both-ends coverage matches it cleanly.
    result = join(
        [payroll("A", "2026-07-09", "612.00")],
        [super_row("A", "2026-07-09", "2026-07-22", "2026-07-14", "612.00")],
    )
    assert result.outcomes[0].remitted == date(2026, 7, 14)
    assert result.outcomes[0].flag == ""
    assert result.orphans == []


def test_monthly_payment_covering_two_paydays_settles_both_in_full():
    # The other exclusive-start casualty from the review: one monthly
    # payment (2026-07-01 to 2026-07-31), covering paydays 2026-07-01 and
    # 2026-07-15, paid in full. The regression read row 2 as falsely
    # unpaid and row 3 as falsely over:, with no orphan produced to hint
    # at either. Both must now settle cleanly, with the payment used (not
    # an orphan).
    result = join(
        [payroll("A", "2026-07-01", "612.00", row=2),
         payroll("A", "2026-07-15", "540.00", row=3)],
        [super_row("A", "2026-07-01", "2026-07-31", "2026-08-05", "1152.00", row=2)],
    )
    outcomes = _by_row(result)
    assert outcomes[2].flag != "no super payment found"
    assert "over:" not in outcomes[2].flag
    assert "over:" not in outcomes[3].flag
    assert outcomes[2].remitted == date(2026, 8, 5)
    assert outcomes[3].remitted == date(2026, 8, 5)
    assert result.orphans == []


def test_two_different_shared_payments_are_named_separately_not_merged():
    # The review's own reproduction: a row that received 300.00 from one
    # super row and 250.00 from a different one must show BOTH as distinct
    # notes, each naming its own super row number, amount and paid date --
    # deduplicating by note text would collapse two different payments
    # into what reads as one 550.00 payment, with no way to tell two
    # payments were involved.
    result = join(
        [payroll("A", "2026-07-09", "600.00", row=2),
         payroll("A", "2026-07-23", "700.00", row=3)],
        [super_row("A", "2026-07-01", "2026-07-31", "2026-07-20", "300.00", row=2),
         super_row("A", "2026-07-01", "2026-08-05", "2026-08-01", "250.00", row=3)],
    )
    outcomes = _by_row(result)
    flag = outcomes[2].flag
    assert flag.startswith("partial: 550.00 of 600.00 matched")
    assert "300.00 of 300.00 allocated from super row 2 (paid 2026-07-20)" in flag
    assert "250.00 of 250.00 allocated from super row 3 (paid 2026-08-01)" in flag
    # Two distinct note segments, not one deduplicated note.
    assert flag.count("allocated from super row") == 2


def test_zero_sg_amount_row_in_an_apportionment_group_is_not_a_missing_payment():
    # A payroll row that owes nothing must not read as a missed payment,
    # and must not inflate another row's "paydays covered" figure by being
    # counted as a competitor it never actually was.
    result = join(
        [payroll("A", "2026-07-09", "600.00", row=2),
         payroll("A", "2026-07-23", "0.00", row=3)],
        [super_row("A", "2026-07-01", "2026-07-31", "2026-08-01", "600.00")],
    )
    outcomes = _by_row(result)
    assert outcomes[3].flag == "no super guarantee owed for this payday"
    assert outcomes[3].remitted is None
    # The zero-need row was never really competing for the payment, so the
    # row that WAS paid shows a plain match, not a false shared-with-2-
    # paydays note that counts a row that received nothing.
    assert outcomes[2].flag == ""
    assert outcomes[2].remitted == date(2026, 8, 1)


def test_a_payment_matching_only_a_zero_sg_row_is_an_orphan_not_a_silent_credit():
    # If a super row's period structurally matches only ONE payroll row,
    # and that row owes nothing, there is no defensible recipient for the
    # money at all -- crediting it to a row that is about to be reported as
    # owing zero regardless would make the payment vanish from the output
    # entirely. Leaving it unclaimed, so it surfaces as an orphan, is the
    # honest answer.
    result = join(
        [payroll("A", "2026-07-09", "0.00")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "500.00")],
    )
    assert result.outcomes[0].flag == "no super guarantee owed for this payday"
    assert [o.row for o in result.orphans] == [2]


def test_pass2_allocation_is_independent_of_input_order_exhaustive():
    # Exhaustive proof, not a sample: every permutation of both the
    # payroll rows and the super rows fed to join must produce the exact
    # same allocation. The order that actually decides the result is the
    # sort inside join (payday/effective_period_end/row for the payroll
    # side, paid_date/row for the super side), never the order the caller
    # happened to build its lists in.
    base_payroll = [
        payroll("A", "2026-07-09", "600.00", row=2),
        payroll("A", "2026-07-23", "600.00", row=3),
        payroll("A", "2026-08-06", "600.00", row=4),
    ]
    base_super = [
        SuperRow(None, "A", None, None, date(2026, 7, 14), Decimal("600.00"), 2),
        SuperRow(None, "A", None, None, date(2026, 7, 28), Decimal("600.00"), 3),
        SuperRow(None, "A", None, None, date(2026, 8, 11), Decimal("600.00"), 4),
    ]
    results = set()
    for payroll_perm in itertools.permutations(base_payroll):
        for super_perm in itertools.permutations(base_super):
            result = join(list(payroll_perm), list(super_perm))
            outcomes = _by_row(result)
            snapshot = tuple(
                (row_number, outcomes[row_number].remitted, outcomes[row_number].flag)
                for row_number in (2, 3, 4)
            )
            results.add(snapshot)
    assert len(results) == 1, f"allocation depended on input order: {results}"


def test_a_payday_on_the_period_end_is_settled_before_an_earlier_payday():
    # Reproduction A. One payment, period 2026-07-03 to 2026-07-10, paid
    # 2026-07-15, 540.00 -- exactly the 10 July payday's obligation, and its
    # period ends on that payday. Plain oldest-first apportionment handed
    # the money to the 3 July row instead, reporting the payday that was
    # actually paid as unpaid and the unpaid one as part-paid. A super
    # payment's period end normally lands on the payday it covers, so that
    # payday is settled first.
    for payroll_rows in (
        [payroll("A", "2026-07-03", "612.00", row=2), payroll("A", "2026-07-10", "540.00", row=3)],
        [payroll("A", "2026-07-10", "540.00", row=3), payroll("A", "2026-07-03", "612.00", row=2)],
    ):
        result = join(
            payroll_rows,
            [super_row("A", "2026-07-03", "2026-07-10", "2026-07-15", "540.00", row=2)],
        )
        outcomes = _by_row(result)
        # The specific date, not just "some date": an order-independence
        # check alone cannot catch a sort applied backwards, since a
        # reversed sort is still deterministic.
        assert outcomes[3].remitted == date(2026, 7, 15)
        assert outcomes[3].flag == (
            "540.00 of 540.00 allocated from super row 2 (paid 2026-07-15), "
            "one of 2 paydays that payment covered"
        )
        assert outcomes[2].remitted is None
        assert outcomes[2].flag == "no super payment found"
        assert result.orphans == []


def test_period_end_priority_leaves_the_earlier_payday_short_not_the_later():
    # Reproduction B: the same shape with the 3 July payday's own earlier
    # payment present too. 212.00 of the second payment used to be pulled
    # back to 3 July, leaving 10 July short. The period-end payday takes
    # its money first, so the shortfall stays on the payday whose own
    # payment was genuinely short.
    for super_rows in (
        [super_row("A", "2026-07-03", "2026-07-10", "2026-07-15", "540.00", row=2),
         super_row("A", "2026-06-27", "2026-07-03", "2026-07-08", "400.00", row=3)],
        [super_row("A", "2026-06-27", "2026-07-03", "2026-07-08", "400.00", row=3),
         super_row("A", "2026-07-03", "2026-07-10", "2026-07-15", "540.00", row=2)],
    ):
        result = join(
            [payroll("A", "2026-07-03", "612.00", row=2),
             payroll("A", "2026-07-10", "540.00", row=3)],
            super_rows,
        )
        outcomes = _by_row(result)
        assert outcomes[3].remitted == date(2026, 7, 15)
        assert "partial" not in outcomes[3].flag
        assert outcomes[2].remitted == date(2026, 7, 8)
        assert outcomes[2].flag == "partial: 400.00 of 612.00 matched"


def test_monthly_payment_whose_last_payday_is_the_period_end_exact_short_and_over():
    # One monthly payment across three fortnightly paydays, where the last
    # payday (31 July) happens to sit exactly on the period end. Exact: all
    # three settle. Short: the period-end payday is settled first, so the
    # shortfall falls on 17 July -- the last row in the remaining
    # oldest-first order -- rather than on 31 July. That moves the flagged
    # exposure to an earlier deadline, which is the conservative direction
    # for a checker, and it is what the ruling asks for: the payday the
    # period names is the one the payment settles. Over: the unattributable
    # excess still lands on the chronologically last payday, unchanged by
    # the priority.
    def run(amount):
        return _by_row(join(
            [payroll("A", "2026-07-03", "600.00", row=2),
             payroll("A", "2026-07-17", "600.00", row=3),
             payroll("A", "2026-07-31", "600.00", row=4)],
            [super_row("A", "2026-07-01", "2026-07-31", "2026-08-15", amount, row=2)],
        ))

    exact = run("1800.00")
    for row_number in (2, 3, 4):
        assert exact[row_number].remitted == date(2026, 8, 15)
        assert "partial" not in exact[row_number].flag
        assert "over:" not in exact[row_number].flag

    short = run("1500.00")
    assert "partial" not in short[4].flag, "the payday on the period end must be settled first"
    assert "partial" not in short[2].flag
    assert short[3].flag.startswith("partial: 300.00 of 600.00 matched")
    assert short[4].remitted == date(2026, 8, 15)

    over = run("2100.00")
    assert over[4].flag.startswith("over: 900.00 against 600.00")
    assert "over:" not in over[2].flag and "over:" not in over[3].flag


def test_monthly_payment_clear_of_the_period_end_still_apportions_oldest_first():
    # The control for the test above: no payday touches the period end
    # (2026-08-11), so the priority never fires and the shortfall stays on
    # the newest payday, exactly as before the priority existed.
    result = join(
        [payroll("A", "2026-07-09", "600.00", row=2),
         payroll("A", "2026-07-23", "600.00", row=3),
         payroll("A", "2026-08-06", "600.00", row=4)],
        [super_row("A", "2026-07-01", "2026-08-11", "2026-08-15", "1500.00", row=2)],
    )
    outcomes = _by_row(result)
    assert "partial" not in outcomes[2].flag
    assert "partial" not in outcomes[3].flag
    assert outcomes[4].flag.startswith("partial: 300.00 of 600.00 matched")


def test_an_overpayment_on_already_settled_paydays_is_named_not_just_orphaned():
    # Rows 2 and 3 are each settled by their own payment. A third payment's
    # period spans both, so nothing is competing for it, nothing is
    # allocated, and no payroll row can carry an "over:" flag for it -- it
    # is a genuine excess contribution that exists nowhere in the result
    # except as an orphan. "Matched no payday" would read as unmatchable
    # data; the two cases have to be tellable apart.
    result = join(
        [payroll("A", "2026-07-09", "600.00", row=2),
         payroll("A", "2026-07-23", "600.00", row=3)],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "600.00", row=2),
         super_row("A", "2026-07-15", "2026-07-23", "2026-07-28", "600.00", row=3),
         super_row("A", "2026-07-01", "2026-07-31", "2026-08-15", "500.00", row=4)],
    )
    assert [o.row for o in result.orphans] == [4]
    reason = result.orphan_reasons[0]
    assert reason.super_row is result.orphans[0]
    assert reason.code == ORPHAN_PAYDAYS_SETTLED
    assert "already settled" in reason.message
    # Neither settled row invented an over: from the third payment.
    outcomes = _by_row(result)
    assert outcomes[2].flag == "" and outcomes[3].flag == ""


def test_a_payment_matching_no_payday_is_reported_differently_from_a_settled_one():
    # The other half of the distinction: a payment for an employee with no
    # payroll rows at all is unplaceable data, not an overpayment.
    result = join(
        [payroll("A", "2026-07-09", "612.00")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00"),
         super_row("B", "2026-07-01", "2026-07-09", "2026-07-14", "99.00", row=3)],
    )
    assert [r.code for r in result.orphan_reasons] == [ORPHAN_NO_PAYDAY]
    assert result.orphan_reasons[0].message == "matched no payday"
    assert ORPHAN_NO_PAYDAY != ORPHAN_PAYDAYS_SETTLED


def test_the_shared_note_counts_the_paydays_the_payment_covered():
    # The note's count is the payment's structural coverage, not how many
    # paydays still had a balance when it was applied. Here a period-less
    # payment is treated as covering all three of the employee's paydays,
    # but the 9 July one is already settled by its own payment, so only two
    # compete for it. Reporting "one of 2 paydays that payment covered"
    # understated what the payment reached.
    result = join(
        [payroll("A", "2026-07-09", "600.00", row=2),
         payroll("A", "2026-07-23", "600.00", row=3),
         payroll("A", "2026-08-06", "600.00", row=4)],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "600.00", row=2),
         SuperRow(None, "A", None, None, date(2026, 7, 28), Decimal("900.00"), 3)],
    )
    outcomes = _by_row(result)
    assert outcomes[2].flag == ""
    assert outcomes[3].flag == (
        "600.00 of 900.00 allocated from super row 3 (paid 2026-07-28), "
        "one of 3 paydays that payment covered"
    )
    assert outcomes[4].flag == (
        "partial: 300.00 of 600.00 matched; "
        "300.00 of 900.00 allocated from super row 3 (paid 2026-07-28), "
        "one of 3 paydays that payment covered"
    )


def test_orphans_are_reported_in_row_order_whatever_order_they_arrived_in():
    # The orphan list is shown to a user, so its order is part of the
    # answer. Two callers handing join the same rows in different orders
    # must not get two different-looking reports.
    result = join(
        [payroll("A", "2026-07-09", "612.00")],
        [super_row("Z", "2026-07-01", "2026-07-09", "2026-07-14", "99.00", row=4),
         super_row("Y", "2026-07-01", "2026-07-09", "2026-07-14", "88.00", row=2),
         super_row("X", "2026-07-01", "2026-07-09", "2026-07-14", "77.00", row=3)],
    )
    assert [o.row for o in result.orphans] == [2, 3, 4]
    assert [r.super_row.row for r in result.orphan_reasons] == [2, 3, 4]


def _render(result):
    """Everything join returns, as one string, so a shuffle comparison
    cannot pass by only checking the fields a hand-written assertion
    happened to look at."""
    lines = [result.key_mode]
    lines.extend(sorted(result.warnings))
    for outcome in sorted(result.outcomes, key=lambda o: o.payroll.row):
        lines.append(
            f"{outcome.payroll.row}|{outcome.remitted}|{outcome.last_known_paid_date}"
            f"|{outcome.flag}"
        )
    for reason in result.orphan_reasons:
        lines.append(f"orphan {reason.super_row.row}|{reason.code}|{reason.message}")
    return "\n".join(lines)


def test_the_whole_result_is_byte_identical_under_shuffled_inputs():
    # Order-independence over every shape this round touched, on the full
    # rendered result rather than one field. Shuffles, not permutations, so
    # the larger shapes are covered too.
    shapes = [
        (
            [payroll("A", "2026-07-03", "612.00", row=2),
             payroll("A", "2026-07-10", "540.00", row=3)],
            [super_row("A", "2026-07-03", "2026-07-10", "2026-07-15", "540.00", row=2),
             super_row("A", "2026-06-27", "2026-07-03", "2026-07-08", "400.00", row=3)],
        ),
        (
            [payroll("A", "2026-07-03", "600.00", row=2),
             payroll("A", "2026-07-17", "600.00", row=3),
             payroll("A", "2026-07-31", "600.00", row=4)],
            [super_row("A", "2026-07-01", "2026-07-31", "2026-08-15", "1500.00", row=2)],
        ),
        (
            [payroll("A", "2026-07-09", "600.00", row=2),
             payroll("A", "2026-07-23", "600.00", row=3),
             payroll("A", "2026-08-06", "600.00", row=4)],
            [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "600.00", row=2),
             SuperRow(None, "A", None, None, date(2026, 7, 28), Decimal("900.00"), 3),
             super_row("A", "2026-07-01", "2026-07-31", "2026-08-20", "50.00", row=4)],
        ),
    ]
    rng = random.Random(20260803)
    for payroll_rows, super_rows in shapes:
        expected = _render(join(list(payroll_rows), list(super_rows)))
        for _ in range(200):
            shuffled_payroll = list(payroll_rows)
            shuffled_super = list(super_rows)
            rng.shuffle(shuffled_payroll)
            rng.shuffle(shuffled_super)
            assert _render(join(shuffled_payroll, shuffled_super)) == expected


# ---------------------------------------------------------------------------
# Task 6: write_canonical / ImportReport / import_files
# ---------------------------------------------------------------------------


def test_canonical_output_feeds_the_normal_check(tmp_path):
    out = tmp_path / "contributions.csv"
    report = import_files(FIXTURES / "myob_payroll.csv", FIXTURES / "myob_super.csv", out)
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert [r["employee_id"] for r in rows] == ["Test Employee One", "Test Employee Two"]
    assert rows[0]["payment_date"] == "2026-07-09"
    assert rows[0]["sg_amount"] == "612.00"
    assert rows[0]["remitted_date"] == "2026-07-14"
    assert rows[0]["fund_received_date"] == ""  # no vendor export carries it
    # The other three flag columns are equally unsourced from any vendor
    # export and must be equally blank, not just the fund receipt date.
    assert rows[0]["first_contribution_to_fund"] == ""
    assert rows[0]["out_of_cycle"] == ""
    assert rows[0]["next_standard_payday"] == ""
    assert rows[0]["defined_benefit"] == ""
    assert report.matched == 2
    assert report.clean is True
    assert isinstance(report, ImportReport)


def test_write_canonical_writes_the_exact_header_and_blank_flag_columns(tmp_path):
    result = join(
        [payroll("A", "2026-07-09", "612.00")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00")],
    )
    out = tmp_path / "out.csv"
    write_canonical(result, out)
    with open(out, newline="", encoding="utf-8-sig") as f:
        reader = _csv.reader(f)
        header = next(reader)
        row = next(reader)
    assert header == CANONICAL_HEADER
    assert row == ["A", "2026-07-09", "612.00", "2026-07-14", "", "", "", "", ""]


def test_write_canonical_rounds_sg_amount_half_up_like_the_rest_of_the_tool(tmp_path):
    # report.money() elsewhere in this codebase rounds ROUND_HALF_UP. A
    # bare Decimal.quantize() call with no rounding mode defaults to
    # ROUND_HALF_EVEN and would write 612.00 here instead of 612.01 --
    # a different figure for the same money, depending only on which
    # function happened to format it. Pinned so that regression cannot
    # creep back in silently.
    result = join(
        [payroll("A", "2026-07-09", "612.005")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.005")],
    )
    out = tmp_path / "out.csv"
    write_canonical(result, out)
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert rows[0]["sg_amount"] == "612.01"


def test_write_canonical_header_matches_the_checkers_default_mapping():
    # CANONICAL_HEADER must be exactly csv_io.DEFAULT_MAPPING's values, in
    # the same field order, or the round trip below only works by accident
    # of dict ordering rather than by construction.
    assert CANONICAL_HEADER == list(DEFAULT_MAPPING.values())


def test_a_formula_in_an_employee_name_is_guarded(tmp_path):
    src = tmp_path / "payroll.csv"
    src.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "=cmd()|'/c calc',09/07/2026,09/07/2026,612.00\n"
        "-00123,09/07/2026,09/07/2026,540.00\n",
        encoding="utf-8",
    )
    sup = tmp_path / "super.csv"
    sup.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "=cmd()|'/c calc',Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,612.00\n"
        "-00123,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,540.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    import_files(src, sup, out)
    text = out.read_text(encoding="utf-8-sig")
    assert "'=cmd()" in text, "formula lead was not neutralised"
    assert "-00123" in text and "'-00123" not in text, "a plain code was mangled"


def test_canonical_csv_round_trips_through_parse_rows_and_the_real_cli(tmp_path):
    # Requirement: the canonical CSV must be readable by the existing
    # checker without modification. Proven two ways -- through the reader
    # function directly, with the default mapping and nothing special-cased
    # for this tool's own output, and separately through the actual CLI
    # entry point end to end.
    out = tmp_path / "contributions.csv"
    import_files(FIXTURES / "myob_payroll.csv", FIXTURES / "myob_super.csv", out)

    lines = parse_rows(out, DEFAULT_MAPPING)
    assert len(lines) == 2
    assert {l.employee_id for l in lines} == {"Test Employee One", "Test Employee Two"}
    assert {l.sg_amount for l in lines} == {Decimal("612.00"), Decimal("540.00")}
    assert all(l.remitted is not None for l in lines)
    assert all(l.received is None for l in lines)  # never invented

    report_out = tmp_path / "report.csv"
    code = cli_main([str(out), "-o", str(report_out), "--as-at", "2026-08-10"])
    assert code in (EXIT_OK, EXIT_LATE_FOUND), "the real CLI choked on our own output"
    with open(report_out, newline="", encoding="utf-8") as f:
        report_rows = [r for r in _csv.DictReader(f) if r["employee_id"] != "NOTE"]
    assert len(report_rows) == 2
    assert {r["employee_id"] for r in report_rows} == {
        "Test Employee One",
        "Test Employee Two",
    }


def test_output_refuses_to_overwrite_the_payroll_input(tmp_path):
    payroll = tmp_path / "payroll.csv"
    payroll.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "Test Employee One,09/07/2026,09/07/2026,612.00\n",
        encoding="utf-8",
    )
    super_ = tmp_path / "super.csv"
    super_.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "Test Employee One,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,612.00\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError) as exc:
        import_files(payroll, super_, payroll)
    assert "overwrite" in str(exc.value)
    # Refused before anything was written -- the original file survives
    # untouched, not truncated then abandoned mid-write.
    assert "612.00" in payroll.read_text(encoding="utf-8")


def test_output_refuses_to_overwrite_the_super_input(tmp_path):
    payroll = tmp_path / "payroll.csv"
    payroll.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "Test Employee One,09/07/2026,09/07/2026,612.00\n",
        encoding="utf-8",
    )
    super_ = tmp_path / "super.csv"
    super_.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "Test Employee One,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,612.00\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError) as exc:
        import_files(payroll, super_, super_)
    assert "overwrite" in str(exc.value)
    assert "Superannuation Guarantee" in super_.read_text(encoding="utf-8")


def test_report_distinguishes_orphan_codes_not_just_a_count(tmp_path):
    # ORPHAN_PAYDAYS_SETTLED (an overpayment on paydays already settled by
    # their own payments) and ORPHAN_NO_PAYDAY (a payment for an employee
    # with no payroll rows at all) are opposite findings for an accountant.
    # A report that only counted orphans could not tell them apart.
    payroll = tmp_path / "payroll.csv"
    payroll.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "A,09/07/2026,09/07/2026,600.00\n"
        "A,23/07/2026,23/07/2026,600.00\n",
        encoding="utf-8",
    )
    super_ = tmp_path / "super.csv"
    super_.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "A,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,600.00\n"
        "A,Superannuation Guarantee,15/07/2026,23/07/2026,28/07/2026,600.00\n"
        "A,Superannuation Guarantee,01/07/2026,31/07/2026,15/08/2026,500.00\n"
        "B,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,99.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    report = import_files(payroll, super_, out)

    assert report.orphans == 2
    assert report.orphan_counts == {ORPHAN_PAYDAYS_SETTLED: 1, ORPHAN_NO_PAYDAY: 1}
    codes = {r.code for r in report.orphan_reasons}
    assert codes == {ORPHAN_PAYDAYS_SETTLED, ORPHAN_NO_PAYDAY}
    assert ORPHAN_NO_AMOUNT not in codes and ORPHAN_NOTHING_OWED not in codes
    # Both paydays settled cleanly; neither invented an over: from the
    # overpayment, matching join()'s own contract.
    assert report.matched == 2
    assert report.clean is False
    settled_message = next(
        r.message for r in report.orphan_reasons if r.code == ORPHAN_PAYDAYS_SETTLED
    )
    assert "already settled" in settled_message
    assert any("already settled" in w for w in report.warnings)
    assert any("matched no payday" in w for w in report.warnings)


def test_outcome_counts_cover_every_payroll_row_exactly_once():
    # Every payroll row must land in exactly one bucket -- the brief's own
    # first draft silently dropped zero-sg-amount and undated-but-fully-
    # matched rows from every bucket, so the counts stopped summing to the
    # number of rows without raising anything.
    payroll_rows = [
        payroll("A", "2026-07-09", "612.00", row=2),   # matched, dated
        payroll("A", "2026-07-23", "0.00", row=3),      # owes nothing
        payroll("A", "2026-08-06", "612.00", row=4),    # undated
        payroll("A", "2026-08-20", "300.00", row=5),    # partial
        payroll("A", "2026-09-03", "300.00", row=6),    # over
        payroll("A", "2026-09-17", "612.00", row=7),    # unmatched
    ]
    super_rows = [
        super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00", row=2),
        super_row("A", "2026-07-25", "2026-08-06", None, "612.00", row=3),
        super_row("A", "2026-08-08", "2026-08-20", "2026-08-25", "150.00", row=4),
        super_row("A", "2026-08-22", "2026-09-03", "2026-09-08", "612.00", row=5),
    ]
    result = join(payroll_rows, super_rows)

    from paydaysuper.importers import _classify_outcome

    counts: dict[str, int] = {}
    for outcome in result.outcomes:
        counts[_classify_outcome(outcome)] = counts.get(_classify_outcome(outcome), 0) + 1

    assert sum(counts.values()) == len(payroll_rows)
    assert counts[OUTCOME_MATCHED] == 1
    assert counts[OUTCOME_OWES_NOTHING] == 1
    assert counts[OUTCOME_UNDATED] == 1
    assert counts[OUTCOME_PARTIAL] == 1
    assert counts[OUTCOME_OVER] == 1
    assert counts[OUTCOME_UNMATCHED] == 1


def test_import_report_clean_is_false_for_a_partial_payment(tmp_path):
    # `clean` must catch a partial match too, not only orphans -- the two
    # earlier `clean` assertions in this file happen to both go through the
    # orphans branch, so this pins the outcome_counts branch on its own.
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "Test Employee One,09/07/2026,09/07/2026,612.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "Test Employee One,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,300.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    report = import_files(payroll_path, super_path, out)
    assert report.partial == 1
    assert report.clean is False


def test_import_report_clean_is_true_for_a_wholly_ordinary_file(tmp_path):
    out = tmp_path / "contributions.csv"
    report = import_files(FIXTURES / "myob_payroll.csv", FIXTURES / "myob_super.csv", out)
    assert report.clean is True
    assert report.orphans == 0
    assert report.orphan_reasons == []


def test_import_files_derives_payroll_has_period_end_from_the_file(tmp_path):
    # No pay period end column at all in the payroll file. join() must be
    # told this is a structural fact about the file, not left to its
    # True default, so the "could be missed" warning actually fires.
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Superannuation Guarantee\n"
        "Test Employee One,09/07/2026,612.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "Test Employee One,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,612.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    report = import_files(payroll_path, super_path, out, vendor="myob-ar")
    assert any(
        "period" in w and "payday" in w for w in report.warnings
    ), report.warnings


def test_import_files_derives_super_has_period_columns_from_the_file(tmp_path):
    # No pay period columns at all in the super file. join() must see this
    # as a structural fact so its strongest warning fires -- a period-less
    # super row is treated as covering every payday for the employee.
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "Test Employee One,09/07/2026,09/07/2026,612.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Paid Date,Amount\n"
        "Test Employee One,Superannuation Guarantee,14/07/2026,612.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    report = import_files(payroll_path, super_path, out, vendor="myob-ar")
    assert any("no pay period columns" in w for w in report.warnings), report.warnings


def test_import_files_does_not_warn_when_both_files_have_full_period_columns(tmp_path):
    # The control for the two tests above: the ordinary myob fixtures have
    # every period column, so neither structural warning should fire.
    out = tmp_path / "contributions.csv"
    report = import_files(FIXTURES / "myob_payroll.csv", FIXTURES / "myob_super.csv", out)
    assert not any("period" in w and "payday" in w for w in report.warnings)
    assert not any("pay period column" in w for w in report.warnings)
