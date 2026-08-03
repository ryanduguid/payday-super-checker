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
                    date.fromisoformat(paid), Decimal(amount), row)


def test_exact_match_sets_the_remittance_date():
    result = join([payroll("A", "2026-07-09", "612.00")],
                  [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "612.00")])
    assert result.outcomes[0].remitted == date(2026, 7, 14)
    assert result.outcomes[0].flag == ""
    assert result.orphans == []


def test_split_payment_takes_the_later_date():
    # The obligation is not met until the whole amount reaches the fund.
    result = join([payroll("A", "2026-07-09", "612.00")],
                  [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "300.00", row=2),
                   super_row("A", "2026-07-01", "2026-07-09", "2026-07-21", "312.00", row=3)])
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


def test_a_super_row_is_claimed_by_at_most_one_payroll_row():
    # One super payment whose period is wide enough to bracket two separate
    # paydays for the same employee must settle only the first one it is
    # tried against, not both -- otherwise its amount is double-counted into
    # two totals and the same dollar looks like it discharged two separate
    # obligations.
    result = join(
        [payroll("A", "2026-07-09", "300.00", row=2),
         payroll("A", "2026-07-23", "300.00", row=3)],
        [super_row("A", "2026-07-01", "2026-07-31", "2026-08-01", "300.00", row=2)],
    )
    assert result.outcomes[0].remitted == date(2026, 8, 1)
    assert result.outcomes[0].flag == ""
    assert result.outcomes[1].remitted is None
    assert result.outcomes[1].flag == "no super payment found"
    assert result.orphans == []


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
