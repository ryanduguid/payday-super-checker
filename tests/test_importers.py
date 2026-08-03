from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from paydaysuper.csv_io import CsvError
from paydaysuper.importers import PayrollRow, SuperRow, join, read_payroll, read_super

FIXTURES = Path(__file__).parent / "fixtures" / "importers"


def test_read_super_keeps_only_super_guarantee():
    rows, profile = read_super(FIXTURES / "myob_super.csv")
    assert profile.key == "myob-ar-super"
    assert len(rows) == 2, "salary sacrifice row was not excluded"
    assert {r.amount for r in rows} == {Decimal("612.00"), Decimal("540.00")}


def test_read_super_reads_australian_day_first_dates():
    rows, _ = read_super(FIXTURES / "myob_super.csv")
    assert rows[0].paid_date == date(2026, 7, 14)
    assert rows[0].period_end == date(2026, 7, 9)


def test_read_payroll_reads_payday_and_amount():
    rows, profile = read_payroll(FIXTURES / "myob_payroll.csv")
    assert profile.key == "myob-ar-payroll"
    assert rows[0].payday == date(2026, 7, 9)
    assert rows[0].sg_amount == Decimal("612.00")


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


def test_a_super_row_bracketing_two_paydays_is_refused_not_guessed():
    # One super payment whose period is wide enough to bracket two separate
    # paydays for the same employee is genuinely ambiguous: picking the
    # first one in the input list (silently, by list order) would settle
    # whichever payday happens to come first in the file, not necessarily
    # the one the payment was actually for, and the two paydays carry
    # different deadlines (2026-07-20 and 2026-08-04). Reordering the CSV
    # must never be able to change which one gets flagged as unpaid, so
    # this refuses instead of guessing.
    with pytest.raises(CsvError) as exc:
        join(
            [payroll("A", "2026-07-09", "300.00", row=2),
             payroll("A", "2026-07-23", "300.00", row=3)],
            [super_row("A", "2026-07-01", "2026-07-31", "2026-08-28", "300.00", row=2)],
        )
    message = str(exc.value)
    assert "super row 2" in message  # names the super row itself
    assert "rows 2, 3" in message  # and every payroll row it could settle


def test_ambiguous_coverage_is_refused_regardless_of_amount():
    # Matching never looks at amount -- only employee and period coverage --
    # so the ambiguity check must not either. Two payroll rows with
    # DIFFERENT amounts but the same period end, bracketed by one super row,
    # are exactly as ambiguous as two with the same amount.
    with pytest.raises(CsvError) as exc:
        join([payroll("A", "2026-07-09", "612.00", row=2),
              payroll("A", "2026-07-09", "500.00", row=3)],
             [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00")])
    assert "rows 2, 3" in str(exc.value)


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
