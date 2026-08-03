from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from paydaysuper.csv_io import CsvError
from paydaysuper.importers import read_payroll, read_super

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
