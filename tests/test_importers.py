import csv as _csv
import itertools
import random
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from paydaysuper.cli import EXIT_ERROR, EXIT_LATE_FOUND, EXIT_OK
from paydaysuper.cli import main as cli_main
from paydaysuper.csv_io import (
    CsvError,
    DEFAULT_MAPPING,
    LATEST_SANE_YEAR,
    parse_rows,
)
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
    _amount,
    import_files as _import_files,
    join,
    read_payroll,
    read_super,
    write_canonical,
)

FIXTURES = Path(__file__).parent / "fixtures" / "importers"


def import_files(*args, **kwargs):
    """Most importer unit cases isolate another rule using synthetic exports
    whose statutory allocation is assumed reconciled. Production remains
    fail-closed; the dedicated CLI regression exercises the default."""
    kwargs.setdefault("statutory_allocation_confirmed", True)
    return _import_files(*args, **kwargs)


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


def test_a_date_outside_the_profiles_own_formats_still_reads(tmp_path):
    # SURVIVING MUTATION (branch review). Deleting _date's parse_date_text
    # fallback broke nothing: every fixture date matches its own profile's
    # date_formats, so the fallback had no test at all. myob-ar declares
    # only %d/%m/%Y and %d/%m/%y, and "9 Jul 2026" is a date the checker
    # itself reads -- refusing it here would fail a file the second command
    # would have accepted.
    path = tmp_path / "payroll.csv"
    path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "Test Employee One,9 Jul 2026,9 Jul 2026,612.00\n",
        encoding="utf-8",
    )
    rows, profile, _ = read_payroll(path, vendor="myob-ar-payroll")
    assert "%d %b %Y" not in profile.date_formats, "the profile must not read it directly"
    assert rows[0].payday == date(2026, 7, 9)
    assert rows[0].period_end == date(2026, 7, 9)


def test_a_negative_amount_is_refused_by_both_readers(tmp_path):
    # SURVIVING MUTATION (branch review). Deleting the negative-amount
    # refusal broke nothing, and Task 5's controller correction leans on it
    # explicitly: the round-4 implementer's concern that join could receive
    # a negative super amount was dismissed BECAUSE _amount raises on any
    # negative, so nothing negative reaches the allocation code through the
    # real path. A negative there subtracts from a payday's balance and
    # conjures money onto another one.
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "Test Employee One,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,-612.00\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError, match="negative"):
        read_super(super_path, vendor="myob-ar-super")

    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "Test Employee One,09/07/2026,09/07/2026,(612.00)\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError, match="negative"):
        read_payroll(payroll_path, vendor="myob-ar-payroll")


def test_read_payroll_reads_payday_and_amount():
    rows, profile, _ = read_payroll(FIXTURES / "myob_payroll.csv")
    assert profile.key == "myob-ar-payroll"
    assert rows[0].payday == date(2026, 7, 9)
    assert rows[0].sg_amount == Decimal("612.00")


def test_read_payroll_surfaces_the_resolved_columns_for_this_file():
    _, _, resolved = read_payroll(FIXTURES / "myob_payroll.csv")
    assert resolved["period_end"] == "Pay Period End"


def test_xero_pair_is_detected_and_imports(tmp_path):
    # The shipped xero profiles had no fixture at all: only the MYOB pair
    # was ever exercised. Detection must pick the xero profiles unforced
    # (the Employee Number heading is what separates xero-payroll from
    # myob-business-payroll, whose normalised signature also matches), the
    # SG filter must drop the salary-sacrifice row, and the canonical file
    # must carry the vendor payment date as a remittance date only.
    payroll_rows, payroll_profile, _ = read_payroll(FIXTURES / "xero_payroll.csv")
    assert payroll_profile.key == "xero-payroll"
    assert payroll_rows[0].payday == date(2026, 7, 9)
    assert payroll_rows[0].sg_amount == Decimal("612.00")

    super_rows, super_profile, _ = read_super(FIXTURES / "xero_super.csv")
    assert super_profile.key == "xero-super"
    assert len(super_rows) == 2, "salary sacrifice row was not excluded"
    assert {r.amount for r in super_rows} == {Decimal("612.00"), Decimal("540.00")}

    out = tmp_path / "contributions.csv"
    report = import_files(FIXTURES / "xero_payroll.csv", FIXTURES / "xero_super.csv", out)
    assert report.matched == 2
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert [r["employee_id"] for r in rows] == ["E1", "E2"]
    assert rows[0]["payment_date"] == "2026-07-09"
    assert rows[0]["sg_amount"] == "612.00"
    assert rows[0]["remitted_date"] == "2026-07-14"
    assert rows[0]["fund_received_date"] == ""  # no vendor export carries it


def test_employment_hero_pair_is_detected_and_imports(tmp_path):
    # Same gap for the Employment Hero / KeyPay profiles, plus their one
    # extra rule: the Beam Status column decides whether a Payment Date is
    # written as a remittance date at all. Both fixture statuses (Sent to
    # fund, Reconciled) evidence money that left the employer.
    payroll_rows, payroll_profile, _ = read_payroll(
        FIXTURES / "employment_hero_payroll.csv"
    )
    assert payroll_profile.key == "employment-hero-payroll"
    assert payroll_rows[0].payday == date(2026, 7, 9)
    assert payroll_rows[0].sg_amount == Decimal("612.00")

    super_rows, super_profile, _ = read_super(FIXTURES / "employment_hero_super.csv")
    assert super_profile.key == "employment-hero-super"
    assert len(super_rows) == 2, "salary sacrifice row was not excluded"
    assert {r.amount for r in super_rows} == {Decimal("612.00"), Decimal("540.00")}

    out = tmp_path / "contributions.csv"
    report = import_files(
        FIXTURES / "employment_hero_payroll.csv",
        FIXTURES / "employment_hero_super.csv",
        out,
    )
    assert report.matched == 2
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert [r["employee_id"] for r in rows] == [
        "Test Employee One",
        "Test Employee Two",
    ]
    assert rows[0]["payment_date"] == "2026-07-09"
    assert rows[0]["sg_amount"] == "612.00"
    assert rows[0]["remitted_date"] == "2026-07-14"
    assert rows[1]["remitted_date"] == "2026-07-30"
    assert rows[0]["fund_received_date"] == ""  # a Beam status is not receipt


def test_myob_business_pair_is_detected_and_imports(tmp_path):
    payroll_rows, payroll_profile, _ = read_payroll(
        FIXTURES / "myob_business_payroll.csv"
    )
    assert payroll_profile.key == "myob-business-payroll"
    assert payroll_rows[0].sg_amount == Decimal("612.00")

    super_rows, super_profile, _ = read_super(FIXTURES / "myob_business_super.csv")
    assert super_profile.key == "myob-business-super"
    assert len(super_rows) == 2, "salary sacrifice row was not excluded"

    out = tmp_path / "contributions.csv"
    report = import_files(
        FIXTURES / "myob_business_payroll.csv",
        FIXTURES / "myob_business_super.csv",
        out,
    )
    assert report.matched == 2
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert [r["employee_id"] for r in rows] == ["E1", "E2"]
    assert rows[0]["remitted_date"] == "2026-07-14"
    assert rows[0]["remitted_amount"] == "612.00"


def test_employment_hero_uses_super_guarantee_not_qualifying_earnings(tmp_path):
    path = tmp_path / "both.csv"
    path.write_text(
        "Employee,Date Paid,Pay Period Ending,Super Guarantee,Qualifying Earnings\n"
        "Test Employee One,09/07/2026,09/07/2026,1.00,612.00\n",
        encoding="utf-8",
    )
    rows, profile, resolved = read_payroll(path)
    assert profile.key == "employment-hero-payroll"
    assert resolved["amount"] == "Super Guarantee"
    assert rows[0].sg_amount == Decimal("1.00")


def test_myob_ar_membership_number_is_not_compared_with_payroll_card_id(tmp_path):
    super_path = tmp_path / "membership.csv"
    super_path.write_text(
        "Employee Name,Employee Membership #,Superannuation Category,Period From,"
        "Period To,Paid Date,Amount\n"
        "Alice,M-9,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,612.00\n",
        encoding="utf-8",
    )
    rows, profile, resolved = read_super(super_path)
    assert profile.key == "myob-ar-super"
    assert "employee_id" not in resolved
    assert rows[0].employee_id is None

    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Card ID,Date,Pay Period End,Superannuation Guarantee\n"
        "Alice,C-1,09/07/2026,09/07/2026,612.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    report = import_files(payroll_path, super_path, out, vendor="myob-ar")
    assert report.key_mode == "name"
    assert report.matched == 1
    assert report.unmatched == 0
    assert any("name" in warning for warning in report.warnings)


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


def test_a_placeholder_year_is_refused_here_not_by_the_checker_afterwards(tmp_path):
    # IMPORTANT regression. _date never applied csv_io.LATEST_SANE_YEAR,
    # which csv_io._parse_date and the CLI's --as-at parsing both do, so a
    # payroll export carrying the routine ERP sentinel 31/12/9999 imported
    # with exit 0 and "matched 2" -- and the very next command refused the
    # file this one had just written. Same rule _amount's magnitude guard
    # already states: a value this module accepts and the checker would
    # refuse must be refused here, at the point closest to the bad input.
    path = tmp_path / "payroll.csv"
    path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "Test Employee One,31/12/9999,31/12/9999,612.00\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError, match="not a real date"):
        read_payroll(path, vendor="myob-ar-payroll")


def test_the_import_date_ceiling_is_exactly_the_checkers_own(tmp_path):
    # Boundary, both sides, against csv_io.LATEST_SANE_YEAR itself rather
    # than a copied literal: 2200 is a date, 2201 is a sentinel. A ceiling
    # one year off either way would let the importer and the checker
    # disagree about a file again.
    def payroll_with(payday: str):
        path = tmp_path / f"payroll_{payday.replace('/', '_')}.csv"
        path.write_text(
            "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
            f"Test Employee One,{payday},{payday},612.00\n",
            encoding="utf-8",
        )
        return path

    last_sane = f"31/12/{LATEST_SANE_YEAR}"
    rows, _, _ = read_payroll(payroll_with(last_sane), vendor="myob-ar-payroll")
    assert rows[0].payday == date(LATEST_SANE_YEAR, 12, 31)
    with pytest.raises(CsvError, match="not a real date"):
        read_payroll(payroll_with(f"01/01/{LATEST_SANE_YEAR + 1}"), vendor="myob-ar-payroll")


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


def test_two_identical_punctuation_only_headings_are_refused_like_csv_io_refuses_them(
    tmp_path,
):
    # MINOR regression. _check_duplicate_headers skipped any heading whose
    # normalised key was falsy, so two byte-identical "###" columns walked
    # straight past the importer while csv_io refuses them outright --
    # contradicting this module's own docstring, which claims its refusal
    # is a SUPERSET of csv_io's rather than a different shape of it.
    path = tmp_path / "punct_headers.csv"
    path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee,###,###\n"
        "Test Employee One,09/07/2026,09/07/2026,612.00,a,b\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError, match="normalise to the same heading"):
        read_payroll(path, vendor="myob-ar-payroll")

    # The claim the docstring makes: csv_io refuses this file too, so the
    # importer refusing it keeps the superset true rather than merely
    # matching it here by accident.
    canonical = tmp_path / "canonical.csv"
    canonical.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,"
        "defined_benefit,###,###\n"
        "E1,2026-07-09,612.00,,,no,no,,no,a,b\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError, match="duplicate column name"):
        parse_rows(canonical, DEFAULT_MAPPING)


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
    # the earlier-dated first contribution settles 3 July before the second
    # is processed, so 3 July has zero balance left and the second payment
    # flows entirely to 10 July. Both rows end up plainly matched, with no
    # shared-payment note -- only one row was still competing for the second
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


def test_split_payment_with_one_undated_row_limits_the_date_to_the_dated_subtotal():
    # remitted_amount prevents the known date from reading as settlement of
    # the whole liability. The dated subtotal can be credited on that date;
    # the undated remainder stays exposed.
    result = join(
        [payroll("A", "2026-07-09", "612.00")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "300.00", row=2),
         super_row("A", "2026-07-01", "2026-07-09", None, "312.00", row=3)],
    )
    assert result.outcomes[0].remitted == date(2026, 7, 14)
    assert result.outcomes[0].remitted_amount == Decimal("300.00")
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


def test_two_employee_ids_differing_only_in_punctuation_stay_distinct(tmp_path):
    # CRITICAL regression. `_key` folded ids through
    # profiles.normalise_header, which strips [^0-9a-z ]+ because it was
    # written for HEADINGS. Applied to an id it merged E-001 and E001 into
    # one employee: the single 1112.00 payment recorded against E-001
    # covered both paydays, both rows were written with remitted
    # 2026-07-12, the run exited 0, and the workpaper showed Bob Ng -- who
    # received nothing -- as settled with no exposure at all. Ids are
    # compared exactly now.
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Employee ID,Date,Pay Period End,Superannuation Guarantee\n"
        "Ann Ward,E-001,10/07/2026,10/07/2026,612.00\n"
        "Bob Ng,E001,24/07/2026,24/07/2026,500.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Employee ID,Superannuation Category,Period From,Period To,"
        "Paid Date,Amount\n"
        "Ann Ward,E-001,Superannuation Guarantee,01/07/2026,31/07/2026,12/07/2026,1112.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    report = import_files(payroll_path, super_path, out)

    assert report.key_mode == "id"
    assert report.unmatched == 1, "Bob Ng's payday received nothing and must say so"
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    ann = next(r for r in rows if r["employee_id"] == "E-001")
    bob = next(r for r in rows if r["employee_id"] == "E001")
    assert ann["remitted_date"] == "2026-07-12"
    assert bob["remitted_date"] == "", "E001 is not E-001; nothing was paid against it"


def test_two_names_differing_only_in_punctuation_stay_distinct(tmp_path):
    # The name fallback folds case and whitespace and stops there. Folding
    # punctuation as well (what normalise_header does to a heading) merges
    # O'Brien with OBrien, and one of the two then reads as settled out of
    # the other's payment.
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "O'Brien,10/07/2026,10/07/2026,612.00\n"
        "OBrien,24/07/2026,24/07/2026,500.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "O'Brien,Superannuation Guarantee,01/07/2026,31/07/2026,12/07/2026,1112.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    report = import_files(payroll_path, super_path, out)

    assert report.key_mode == "name"
    assert report.unmatched == 1
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    obrien = next(r for r in rows if r["employee_id"] == "O'Brien")
    plain = next(r for r in rows if r["employee_id"] == "OBrien")
    assert obrien["remitted_date"] == "2026-07-12"
    assert plain["remitted_date"] == ""


def test_a_name_with_no_ascii_letters_imports_instead_of_stopping_the_run(tmp_path):
    # Same root cause, opposite symptom. normalise_header() returns the
    # empty string for a name with no ASCII alphanumerics in it, so a
    # payroll row with a perfectly populated employee column died at join()
    # with "row 2: the employee column is empty" and no file was written at
    # all. Chinese, Korean, Greek, Cyrillic and Arabic names all blocked
    # the entire import. The name is written as escapes because every file
    # in this repo is ASCII; the fixture on disk is UTF-8.
    name = "\u5f20\u4f1f"  # a two-character Chinese name
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        f"{name},10/07/2026,10/07/2026,612.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        f"{name},Superannuation Guarantee,01/07/2026,10/07/2026,15/07/2026,612.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    report = import_files(payroll_path, super_path, out)

    assert report.matched == 1
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert rows[0]["employee_id"] == name
    assert rows[0]["remitted_date"] == "2026-07-15"


def test_a_sub_cent_shortfall_is_not_reported_as_a_partial_payment(tmp_path):
    # CRITICAL regression. join compared raw Decimals while write_canonical
    # writes money(), quantised to cents, so 540.00 paid against 540.004
    # owed read as a short payment: the remittance date was blanked and the
    # checker reported the whole 540.00 as a shortfall with an SG-charge
    # estimate on top, on a payday where every payable cent arrived on time.
    result = join(
        [payroll("A", "2026-07-09", "540.004")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-15", "540.00")],
    )
    assert result.outcomes[0].flag == ""
    assert result.outcomes[0].remitted == date(2026, 7, 15)

    # And the date survives into the file the checker actually reads.
    out = tmp_path / "out.csv"
    write_canonical(result, out)
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert rows[0]["sg_amount"] == "540.00"
    assert rows[0]["remitted_date"] == "2026-07-15"


def test_a_sub_cent_excess_is_not_reported_as_an_overpayment():
    # The mirror case: 540.004 paid against 540.00 owed printed "over:
    # 540.004 against 540.00, check for salary sacrifice" and sent an
    # accountant looking for a salary-sacrifice mix-up over four tenths of
    # a cent.
    result = join(
        [payroll("A", "2026-07-09", "540.00")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-15", "540.004")],
    )
    assert result.outcomes[0].flag == ""


def test_a_whole_cent_difference_is_still_flagged_both_ways():
    # Teeth for the two tests above: rounding to cents must not blunt the
    # comparison itself. One cent short is still partial, one cent over is
    # still over.
    short = join(
        [payroll("A", "2026-07-09", "540.01")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-15", "540.00")],
    )
    assert short.outcomes[0].flag.startswith("partial: ")
    over = join(
        [payroll("A", "2026-07-09", "540.00")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-15", "540.01")],
    )
    assert over.outcomes[0].flag.startswith("over: ")


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


def test_last_known_paid_date_is_used_for_the_dated_subtotal():
    # A partly-undated group keeps the one date the operator does have and
    # applies it only to remitted_amount, not to the full liability.
    result = join(
        [payroll("A", "2026-07-09", "612.00")],
        [super_row("A", "2026-07-01", "2026-07-09", "2026-07-14", "300.00", row=2),
         super_row("A", "2026-07-01", "2026-07-09", None, "312.00", row=3)],
    )
    outcome = result.outcomes[0]
    assert outcome.remitted == date(2026, 7, 14)
    assert outcome.remitted_amount == Decimal("300.00")
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


def test_an_overpayment_cannot_be_carried_onto_a_later_payday(tmp_path):
    # SURVIVING MUTATION (branch review). Removing the max(Decimal("0"), ...)
    # clamp in _unmet broke nothing, and it is not semantically equivalent:
    # it is the guard the round-2 critical fix was built on.
    #
    # Payday 1 owes 500.00 and receives 800.00 on its own. Payday 2 owes
    # 500.00, and a later payment of 400.00 spans both. With the clamp,
    # payday 1's unmet balance is 0, so payday 2 takes 400.00 of the 400.00
    # and reads "partial: 400.00 of 500.00 matched" with its remitted date
    # withheld. Without it, payday 1's balance is -300.00, `remaining -=
    # share` ADDS that 300 back to the pot, and payday 2 reads "over:
    # 700.00 against 500.00" with a remittance date written: 300.00 of an
    # overpayment on one payday is conjured onto the next and flips it from
    # a reported shortfall to reported settled.
    payday_1 = payroll("A", "2026-07-09", "500.00", row=2)
    payday_2 = payroll("A", "2026-07-23", "500.00", row=3)
    result = join(
        [payday_1, payday_2],
        [
            # Covers payday 1 alone, and overpays it.
            super_row("A", "2026-07-01", "2026-07-09", "2026-07-10", "800.00", row=2),
            # Spans both paydays and allocates oldest outstanding first.
            super_row("A", "2026-07-01", "2026-07-31", "2026-07-24", "400.00", row=3),
        ],
    )
    first, second = result.outcomes
    assert first.flag.startswith("over: 800.00 against 500.00")
    assert second.flag == "partial: 400.00 of 500.00 matched"

    out = tmp_path / "out.csv"
    write_canonical(result, out)
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert rows[1]["sg_amount"] == "500.00"
    assert rows[1]["remitted_amount"] == "400.00"
    assert rows[1]["remitted_date"] == "2026-07-24"


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


def test_a_zero_amount_payment_covering_two_paydays_says_it_has_nothing_to_give():
    # SURVIVING MUTATION (branch review). Changing ORPHAN_NO_AMOUNT to
    # ORPHAN_NO_PAYDAY in _why_orphaned broke nothing: the only test
    # touching this code asserted `ORPHAN_NO_AMOUNT not in codes`, a
    # negative that passes either way. The branch is reachable -- a super
    # row of 0.00 covering two paydays that both still owe -- and the two
    # codes say opposite things to an accountant. "no payday matched" sends
    # someone looking for a missing payroll row; the payroll rows are right
    # there and it is the payment that is empty.
    result = join(
        [payroll("A", "2026-07-09", "500.00", row=2),
         payroll("A", "2026-07-23", "500.00", row=3)],
        [super_row("A", "2026-07-01", "2026-07-31", "2026-07-24", "0.00", row=2)],
    )
    assert [o.flag for o in result.outcomes] == [
        "no super payment found",
        "no super payment found",
    ]
    assert len(result.orphan_reasons) == 1
    reason = result.orphan_reasons[0]
    assert reason.code == ORPHAN_NO_AMOUNT
    assert reason.code != ORPHAN_NO_PAYDAY
    assert "carries no amount" in reason.message


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


def test_a_payday_on_the_period_end_does_not_jump_an_earlier_shortfall():
    # A vendor period ending on 10 July does not override LCR 2026/2's
    # earliest-shortfall ordering.
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
        assert outcomes[2].remitted == date(2026, 7, 15)
        assert outcomes[2].flag == (
            "partial: 540.00 of 612.00 matched; 540.00 of 540.00 allocated "
            "from super row 2 (paid 2026-07-15), "
            "one of 2 paydays that payment covered"
        )
        assert outcomes[3].remitted is None
        assert outcomes[3].flag == "no super payment found"
        assert result.orphans == []


def test_lcr_2026_2_applies_a_short_payment_to_the_earliest_shortfall():
    """A vendor period ending on the later payday is not a statutory
    allocation instruction. LCR 2026/2 applies the contribution to the
    earliest QE day with a shortfall."""
    result = join(
        [
            payroll("A", "2026-07-03", "100.00", row=2),
            payroll("A", "2026-07-10", "100.00", row=3),
        ],
        [
            super_row(
                "A", "2026-07-03", "2026-07-10", "2026-07-15", "100.00", row=2
            )
        ],
    )
    outcomes = _by_row(result)

    assert outcomes[2].remitted == date(2026, 7, 15)
    assert outcomes[3].remitted is None


def test_import_refuses_unreconciled_statutory_allocation_then_accepts_confirmation(
    tmp_path, capsys
):
    """The export has employer payment dates, not fund-receipt order or ATO
    assessment facts. Multiple paydays for one employee therefore require
    an explicit LCR 2026/2 reconciliation before a canonical file is written."""
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "A,03/07/2026,03/07/2026,100.00\n"
        "A,10/07/2026,10/07/2026,100.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "A,Superannuation Guarantee,03/07/2026,10/07/2026,15/07/2026,100.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    common = [
        "import",
        "--payroll",
        str(payroll_path),
        "--super",
        str(super_path),
        "--vendor",
        "myob-ar",
        "-o",
        str(out),
    ]

    code = cli_main(common)

    assert code == EXIT_ERROR
    assert not out.exists()
    error = capsys.readouterr().err
    assert "LCR 2026/2" in error
    assert "fund-receipt order" in error
    assert "--confirm-statutory-allocation" in error

    code = cli_main(common + ["--confirm-statutory-allocation"])

    assert code == EXIT_LATE_FOUND
    assert out.exists()
    printed = capsys.readouterr().out
    assert "operator confirmed" in printed
    with open(out, newline="", encoding="utf-8-sig") as handle:
        rows = list(_csv.DictReader(handle))
    assert rows[0]["remitted_date"] == "2026-07-15"
    assert rows[1]["remitted_date"] == ""


def test_fund_order_fills_the_earlier_shortfall_before_the_later_payday():
    # The 8 July contribution first leaves 212 owing on 3 July. The next
    # contribution clears that earliest shortfall before reaching 10 July.
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
        assert outcomes[2].remitted == date(2026, 7, 15)
        assert "partial" not in outcomes[2].flag
        assert outcomes[3].remitted == date(2026, 7, 15)
        assert outcomes[3].flag.startswith("partial: 328.00 of 540.00 matched")


def test_monthly_payment_whose_last_payday_is_the_period_end_exact_short_and_over():
    # Exact: all three settle. Short: LCR 2026/2 leaves the newest payday
    # short after the two earliest shortfalls are cleared. Over: the excess
    # remains surfaced on the newest payday.
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
    assert short[4].flag.startswith("partial: 300.00 of 600.00 matched")
    assert "partial" not in short[2].flag
    assert "partial" not in short[3].flag
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
    assert row == [
        "A",
        "2026-07-09",
        "612.00",
        "2026-07-14",
        "",
        "",
        "",
        "",
        "",
        "612.00",
        "612.00",
    ]


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


def test_write_canonical_prefers_employee_id_over_employee_name(tmp_path):
    # Swapping `row.employee_id or row.employee_name` to the reverse order
    # in write_canonical survives every other test in this file, because
    # every fixture used so far is name-only. It matters downstream: the
    # checker's s 18C(2) item-4 alignment groups by employee_id, so two
    # employees who happen to share a name would silently merge if the
    # canonical file wrote the name instead of the id whenever both exist.
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Employee ID,Date,Pay Period End,Superannuation Guarantee\n"
        "Alice Smith,E001,09/07/2026,09/07/2026,612.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Employee ID,Superannuation Category,Period From,Period To,"
        "Paid Date,Amount\n"
        "Alice Smith,E001,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,612.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    import_files(payroll_path, super_path, out)
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert rows[0]["employee_id"] == "E001"
    assert rows[0]["employee_id"] != "Alice Smith"


def test_one_employee_is_written_under_one_label_when_only_some_rows_have_an_id(
    tmp_path,
):
    # MINOR regression. write_canonical wrote `employee_id or
    # employee_name`, decided per row, while `join` had matched on the name
    # for the whole file (one blank id anywhere forces name matching). A
    # file where the same person carries an id on one payday and not the
    # next was written as two employees, and the checker groups its s
    # 18C(2) item-4 alignment by employee_id, so the 20-business-day window
    # opened by the first payday stopped reaching the second.
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Employee ID,Date,Pay Period End,Superannuation Guarantee\n"
        "Ann Ward,E001,10/07/2026,10/07/2026,612.00\n"
        "Ann Ward,,24/07/2026,24/07/2026,612.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "Ann Ward,Superannuation Guarantee,01/07/2026,10/07/2026,12/07/2026,612.00\n"
        "Ann Ward,Superannuation Guarantee,11/07/2026,24/07/2026,26/07/2026,612.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    report = import_files(payroll_path, super_path, out)
    assert report.key_mode == "name"

    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert len(rows) == 2
    assert len({r["employee_id"] for r in rows}) == 1, "one person, one identity"


def test_a_partial_payment_is_not_written_as_fully_remitted(tmp_path):
    # CRITICAL regression. A dated part payment used to write remitted_date
    # beside the FULL sg_amount with no remitted_amount column, so the
    # checker read a short-paid payday as settled in full. sg_amount stays
    # the liability and remitted_amount is the dated money. With no fund
    # receipt, the checker must expose the whole statutory shortfall while
    # separately reporting the operationally unremitted remainder.
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "A,09/07/2026,09/07/2026,1000.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "A,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,1.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    report = import_files(payroll_path, super_path, out)
    assert report.partial == 1

    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert rows[0]["sg_amount"] == "1000.00"
    assert rows[0]["remitted_date"] == "2026-07-14"
    assert rows[0]["remitted_amount"] == "1.00"
    assert rows[0]["matched_amount"] == "1.00"

    report_out = tmp_path / "report.csv"
    code = cli_main(
        [
            str(out),
            "-o",
            str(report_out),
            "--as-at",
            "2026-08-10",
            "--confirm-transition-allocation",
        ]
    )
    assert code == EXIT_LATE_FOUND
    with open(report_out, newline="", encoding="utf-8") as f:
        checker_rows = list(_csv.DictReader(f))
    checker_row = next(r for r in checker_rows if r["employee_id"] == "A")
    assert checker_row["verdict"] in ("UNPAID", "LATE")
    assert Decimal(checker_row["final_shortfall"]) == Decimal("1000.00")


def test_an_absurdly_large_sg_amount_is_refused_with_csverror(tmp_path):
    # IMPORTANT. csv_io._parse_amount refuses amount.adjusted() > 15
    # because a value beyond that cannot be quantized to cents under the
    # default decimal context. importers._amount had no such guard, so a
    # value this large parsed fine at read time and only blew up later, as
    # a raw decimal.InvalidOperation from report.money()'s quantize() call
    # inside write_canonical -- an ArithmeticError, not a CsvError, so it
    # escapes the CLI's `except (CsvError, ..., ValueError)` entirely.
    absurd = "1" + "0" * 30  # 10**30
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        f"A,09/07/2026,09/07/2026,{absurd}.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        f"A,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,{absurd}.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    with pytest.raises(CsvError) as exc:
        import_files(payroll_path, super_path, out)
    assert "too large" in str(exc.value)
    # Refused before write_canonical ever opened the output file.
    assert not out.exists()


def test_importer_refuses_the_same_magnitude_the_checker_refuses(tmp_path):
    # IMPORTANT. Before this fix, a value strictly between 10**16 and
    # 10**26 (past csv_io's own adjusted() > 15 cutoff, but under the
    # regex-only limit importers._amount used to enforce) imported and
    # wrote CLEANLY, then csv_io.parse_rows refused the importer's own
    # output on the very next run: the importer produced a file the
    # checker itself would not accept. 10**16 is the smallest such value.
    huge = "10000000000000000.00"  # 10**16
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        f"A,09/07/2026,09/07/2026,{huge}\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError) as exc:
        read_payroll(payroll_path, vendor="myob-ar-payroll")
    assert "too large" in str(exc.value)

    # Same boundary, same text, through the checker's own reader: proves
    # this is genuinely the value the checker would refuse, not a
    # coincidence of wording.
    checker_path = tmp_path / "checker.csv"
    checker_path.write_text(
        "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
        "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
        f"A,2026-07-09,{huge},,,no,no,,no\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError):
        parse_rows(checker_path, DEFAULT_MAPPING)


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
    assert "'-00123" in text, "numeric-looking formula lead was not neutralised"


def test_canonical_csv_round_trips_through_parse_rows_and_the_real_cli(tmp_path, capsys):
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
    code = cli_main(
        [
            str(out),
            "-o",
            str(report_out),
            "--as-at",
            "2026-08-10",
            "--confirm-transition-allocation",
        ]
    )
    assert code == EXIT_LATE_FOUND
    assert "cannot produce ON_TIME" in capsys.readouterr().out
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


def test_dated_subtotal_with_an_undated_remainder_is_classified_partial():
    result = join(
        [payroll("A", "2026-07-09", "1000.00", row=2)],
        [
            super_row(
                "A", "2026-07-01", "2026-07-09", "2026-07-20", "600.00", row=2
            ),
            super_row("A", "2026-07-01", "2026-07-09", None, "400.00", row=3),
        ],
    )

    from paydaysuper.importers import _classify_outcome

    assert _classify_outcome(result.outcomes[0]) == OUTCOME_PARTIAL


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


def test_a_payroll_file_spanning_30_june_warns_instead_of_dead_ending(tmp_path, capsys):
    # IMPORTANT regression. A financial-year export spans 1 July, which is
    # the ordinary shape of the file a user reaches for. It imported with
    # exit 0 and no warning at all, and the check then died with "1 row(s)
    # have a QE day before 1 Jul 2026 ... Remove them and run again" and
    # wrote no report -- so README's "two commands turn a payroll export
    # into a checked report" was false for any full-year export. The
    # importer knows REGIME_START; it says so now, names the rows, and says
    # what to do about them.
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "Test Employee One,25/06/2026,25/06/2026,540.00\n"
        "Test Employee One,10/07/2026,10/07/2026,612.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "Test Employee One,Superannuation Guarantee,20/06/2026,25/06/2026,26/06/2026,540.00\n"
        "Test Employee One,Superannuation Guarantee,01/07/2026,10/07/2026,15/07/2026,612.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    report = import_files(payroll_path, super_path, out)
    warning = next(w for w in report.warnings if "before 2026-07-01" in w)
    assert "row(s) 2" in warning, warning
    assert "delete them" in warning

    # It reaches the console, and ahead of the per-row detail: this is the
    # one warning that decides whether the second command runs at all.
    code = cli_main(
        ["import", "--payroll", str(payroll_path), "--super", str(super_path),
         "-o", str(out)]
    )
    assert code in (EXIT_OK, EXIT_LATE_FOUND)
    printed = capsys.readouterr().out
    assert "before 2026-07-01" in printed

    # And the dead-end the warning is about is real: the check refuses the
    # file this run just wrote. If REGIME_START ever moves, or the checker
    # stops refusing, this half fails and the warning gets revisited.
    assert cli_main([str(out), "-o", str(tmp_path / "report.csv")]) == EXIT_ERROR
    assert "before 1 Jul 2026" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Task 7: the `import` CLI subcommand
# ---------------------------------------------------------------------------


def test_import_subcommand_writes_the_file(tmp_path, capsys):
    out = tmp_path / "contributions.csv"
    code = cli_main(
        [
            "import",
            "--payroll",
            str(FIXTURES / "myob_payroll.csv"),
            "--super",
            str(FIXTURES / "myob_super.csv"),
            "-o",
            str(out),
        ]
    )
    assert code == EXIT_OK
    assert out.exists()
    printed = capsys.readouterr().out
    # The exact label-to-key pairing, not just that both keys appear
    # somewhere: a swap of the two _profile_line calls would still contain
    # both substrings but pair them with the wrong label.
    assert "payroll profile: myob-ar-payroll" in printed
    assert "super profile: myob-ar-super" in printed
    assert "unverified" in printed
    assert "receipt" in printed.lower()


def test_import_replaces_an_output_symlink_without_touching_its_target(tmp_path):
    """The importer has the same output-link boundary as the checker."""
    output = tmp_path / "contributions.csv"
    protected_target = tmp_path / "protected.csv"
    protected_target.write_text("leave this file alone\n", encoding="utf-8")
    try:
        output.symlink_to(protected_target)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable in this test environment: {exc}")

    assert (
        cli_main(
            [
                "import",
                "--payroll",
                str(FIXTURES / "myob_payroll.csv"),
                "--super",
                str(FIXTURES / "myob_super.csv"),
                "-o",
                str(output),
            ]
        )
        == EXIT_OK
    )

    assert not output.is_symlink()
    assert protected_target.read_text(encoding="utf-8") == "leave this file alone\n"
    assert "employee_id" in output.read_text(encoding="utf-8-sig")


def test_import_refuses_an_output_symlink_to_the_payroll_input(tmp_path):
    """Alias checks must still resolve a selected output symlink to its input."""
    payroll = FIXTURES / "myob_payroll.csv"
    super_ = FIXTURES / "myob_super.csv"
    before = payroll.read_bytes()
    output = tmp_path / "contributions.csv"
    try:
        output.symlink_to(payroll)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable in this test environment: {exc}")

    with pytest.raises(CsvError, match="output would overwrite"):
        import_files(payroll, super_, output)

    assert output.is_symlink()
    assert payroll.read_bytes() == before


def test_import_returns_two_when_a_payday_has_no_payment(tmp_path):
    src = tmp_path / "payroll.csv"
    src.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "Test Employee One,09/07/2026,09/07/2026,612.00\n"
        "Test Employee Three,09/07/2026,09/07/2026,700.00\n",
        encoding="utf-8",
    )
    code = cli_main(
        [
            "import",
            "--payroll",
            str(src),
            "--super",
            str(FIXTURES / "myob_super.csv"),
            "-o",
            str(tmp_path / "out.csv"),
        ]
    )
    assert code == EXIT_LATE_FOUND


def test_import_clean_file_returns_zero(tmp_path):
    # The control for the above: the ordinary myob fixtures join cleanly, so
    # the exit code must be 0, not 2.
    out = tmp_path / "out.csv"
    code = cli_main(
        [
            "import",
            "--payroll",
            str(FIXTURES / "myob_payroll.csv"),
            "--super",
            str(FIXTURES / "myob_super.csv"),
            "-o",
            str(out),
        ]
    )
    assert code == EXIT_OK


def test_plain_check_dispatch_still_works_with_transition_confirmation(tmp_path):
    # The exact exit code and real report contents, not just "did not
    # crash". The sample crosses the LCR 2026/1 transition, so its explicit
    # synthetic-balance confirmation is part of the safe invocation.
    # test_integration.py's own
    # test_cli_writes_report_and_flags_late pins the same fixture at a
    # different --as-at date far more thoroughly; this test's job is
    # narrower: prove the `import` subcommand's dispatch in main() did not
    # disturb the plain check invocation at all.
    from conftest import SAMPLE

    out = tmp_path / "report.csv"
    code = cli_main(
        [
            str(SAMPLE),
            "-o",
            str(out),
            "--as-at",
            "2026-09-01",
            "--confirm-transition-allocation",
        ]
    )
    assert code == EXIT_LATE_FOUND
    assert out.exists()

    with open(out, newline="", encoding="utf-8") as f:
        rows = list(_csv.DictReader(f))
    data = [r for r in rows if r["employee_id"] != "NOTE"]
    assert len(data) == 10
    assert {r["verdict"] for r in data} == {
        "ON_TIME",
        "AT_RISK",
        "LATE",
        "UNPAID",
        "SKIPPED",
    }
    unpaid = next(r for r in data if r["employee_id"] == "EMP004")
    assert unpaid["verdict"] == "UNPAID"
    assert unpaid["sg_amount"] == "780.00"


def test_import_error_is_printed_without_a_traceback_and_exits_one(tmp_path, capsys):
    code = cli_main(
        [
            "import",
            "--payroll",
            str(tmp_path / "does_not_exist.csv"),
            "--super",
            str(FIXTURES / "myob_super.csv"),
            "-o",
            str(tmp_path / "out.csv"),
        ]
    )
    assert code == EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.err.startswith("error:")
    assert "Traceback" not in captured.err
    assert not (tmp_path / "out.csv").exists()


def test_import_catches_arithmetic_error_from_import_files(tmp_path, capsys, monkeypatch):
    # decimal.InvalidOperation is an ArithmeticError, not a ValueError, so it
    # is invisible to a plain `except (CsvError, ValueError)`. Every amount
    # importers.py builds is already guarded against actually producing one
    # (see the "too large to be a real amount" checks), so this proves the
    # CLI's own backstop by forcing the case directly rather than relying on
    # finding a real input that still triggers it.
    from decimal import InvalidOperation

    import paydaysuper.importers as importers_module

    def _boom(*args, **kwargs):
        raise InvalidOperation("synthetic failure for the CLI's own guard")

    monkeypatch.setattr(importers_module, "import_files", _boom)

    code = cli_main(
        [
            "import",
            "--payroll",
            str(FIXTURES / "myob_payroll.csv"),
            "--super",
            str(FIXTURES / "myob_super.csv"),
            "-o",
            str(tmp_path / "out.csv"),
        ]
    )
    assert code == EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.err.startswith("error:")
    assert "Traceback" not in captured.err


def test_import_prints_the_partial_warning_and_writes_remitted_amount(
    tmp_path, capsys
):
    # A dated 999.99 of 1000.00 match must keep the per-row warning AND
    # write remitted_amount so the checker reports the 0.01 operationally
    # unremitted remainder. With no fund receipt, the statutory shortfall
    # remains the full 1000.00.
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "A,09/07/2026,09/07/2026,1000.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "A,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,999.99\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    code = cli_main(
        [
            "import",
            "--payroll",
            str(payroll_path),
            "--super",
            str(super_path),
            "-o",
            str(out),
        ]
    )
    assert code == EXIT_LATE_FOUND
    printed = capsys.readouterr().out

    assert "row 2: partial: 999.99 of 1000.00 matched" in printed
    lowered = printed.lower()
    assert "remitted_amount" in lowered
    assert printed.index("partial: 999.99 of 1000.00 matched") < printed.index("wrote ")

    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert rows[0]["sg_amount"] == "1000.00"
    assert rows[0]["remitted_date"] == "2026-07-14"
    assert rows[0]["remitted_amount"] == "999.99"
    assert rows[0]["matched_amount"] == "999.99"

    report_out = tmp_path / "report.csv"
    check_code = cli_main(
        [
            str(out),
            "-o",
            str(report_out),
            "--as-at",
            "2026-08-10",
            "--confirm-transition-allocation",
        ]
    )
    assert check_code == EXIT_LATE_FOUND
    with open(report_out, newline="", encoding="utf-8") as f:
        checker_row = next(r for r in _csv.DictReader(f) if r["employee_id"] == "A")
    assert checker_row["verdict"] == "UNPAID"
    assert Decimal(checker_row["final_shortfall"]) == Decimal("1000.00")


def test_mixed_dated_and_undated_match_uses_the_latest_known_date_conservatively(
    tmp_path, capsys
):
    # A single canonical row cannot represent several dated instalments.
    # Use the latest known date for the dated subtotal: before that date no
    # operational credit is taken; on or after it only that subtotal is shown
    # as remitted. With no fund receipt, neither date reduces the statutory
    # shortfall.
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "A,09/07/2026,09/07/2026,1000.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "A,Superannuation Guarantee,01/07/2026,09/07/2026,01/08/2026,600.00\n"
        "A,Superannuation Guarantee,01/07/2026,09/07/2026,,400.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    code = cli_main(
        ["import", "--payroll", str(payroll_path), "--super", str(super_path),
         "-o", str(out)]
    )
    assert code == EXIT_LATE_FOUND
    printed = capsys.readouterr().out

    assert "row 2: 400.00 of 1000.00 matched has no payment date on record" in printed
    assert "latest known payment date 2026-08-01" in printed
    assert "no fund-receipt date" not in printed

    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert rows[0]["sg_amount"] == "1000.00"
    assert rows[0]["remitted_date"] == "2026-08-01"
    assert rows[0]["remitted_amount"] == "600.00"

    before_report = tmp_path / "before.csv"
    before_code = cli_main(
        [
            str(out),
            "-o",
            str(before_report),
            "--as-at",
            "2026-07-25",
            "--confirm-transition-allocation",
        ]
    )
    assert before_code == EXIT_LATE_FOUND
    with open(before_report, newline="", encoding="utf-8") as f:
        before = next(r for r in _csv.DictReader(f) if r["employee_id"] == "A")
    assert Decimal(before["final_shortfall"]) == Decimal("1000.00")

    after_report = tmp_path / "after.csv"
    after_code = cli_main(
        [
            str(out),
            "-o",
            str(after_report),
            "--as-at",
            "2026-08-02",
            "--confirm-transition-allocation",
        ]
    )
    assert after_code == EXIT_LATE_FOUND
    with open(after_report, newline="", encoding="utf-8") as f:
        after = next(r for r in _csv.DictReader(f) if r["employee_id"] == "A")
    assert Decimal(after["final_shortfall"]) == Decimal("1000.00")


def test_import_never_truncates_a_partial_warning_however_many_there_are(
    tmp_path, capsys
):
    # IMPORTANT REVIEW FINDING (round 1). The original cap sliced
    # report.warnings uniformly, so a file with more than MAX_WARNINGS_SHOWN
    # partial rows silently dropped the only surviving record of what
    # actually arrived for the rows past the cut -- exactly what the
    # caveat printed above the warnings block promises never happens.
    # Reproduction: 60 employees, each owed 1000.00, each paid 900.00 plus
    # their own index (900.00 .. 959.00) -- an ordinary small-business
    # payroll, well past the 20-line cap. Every one of the 60 partial
    # figures must survive in the console output, and the canonical CSV
    # must still show why they matter (remitted_date blank on every one).
    n = 60
    payroll_lines = ["Employee Name,Date,Pay Period End,Superannuation Guarantee"]
    super_lines = [
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount"
    ]
    for i in range(n):
        name = f"Employee{i:02d}"
        payroll_lines.append(f"{name},09/07/2026,09/07/2026,1000.00")
        paid = 900 + i
        super_lines.append(
            f"{name},Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,{paid}.00"
        )
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text("\n".join(payroll_lines) + "\n", encoding="utf-8")
    super_path = tmp_path / "super.csv"
    super_path.write_text("\n".join(super_lines) + "\n", encoding="utf-8")

    out = tmp_path / "contributions.csv"
    code = cli_main(
        [
            "import",
            "--payroll",
            str(payroll_path),
            "--super",
            str(super_path),
            "-o",
            str(out),
        ]
    )
    assert code == EXIT_LATE_FOUND
    printed = capsys.readouterr().out

    # All 60 partial figures present, not just the first 19 or 20.
    partial_lines = re.findall(r"row \d+: partial: [\d.]+ of 1000\.00 matched", printed)
    assert len(partial_lines) == n
    assert "row 2: partial: 900.00 of 1000.00 matched" in printed  # first
    assert "row 61: partial: 959.00 of 1000.00 matched" in printed  # last, past any old cap

    # Nothing about the partial figures is described as hidden: the only
    # "more" line, if any, must explicitly disclaim partial/over content.
    for line in printed.splitlines():
        if "more" in line and "partial" not in line and "over-payment" not in line:
            pytest.fail(f"an overflow line does not say it excludes partials: {line!r}")

    # The canonical CSV now carries remitted_amount; remitted_date stays
    # set on a fully dated partial so the checker can compute the remainder.
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    first, last = rows[0], rows[-1]
    assert first["employee_id"] == "Employee00"
    assert first["remitted_date"] == "2026-07-14"
    assert first["remitted_amount"] == "900.00"
    assert last["employee_id"] == "Employee59"
    assert last["remitted_date"] == "2026-07-14"
    assert last["remitted_amount"] == "959.00"


def test_import_never_truncates_an_undated_warning_however_many_there_are(
    tmp_path, capsys
):
    # PART 3(b) REGRESSION. An OUTCOME_UNDATED row -- every dollar owed was
    # matched, but no part of the match carries a payment date -- needs a
    # per-row reconciliation warning even though matched_amount now preserves
    # the amount in the canonical file. Before this fix these warnings were
    # sliced by the ordinary MAX_WARNINGS_SHOWN cap like any other row-level
    # warning, so a file with more than the cap silently hid which rows still
    # needed payment and receipt evidence.
    # Reproduction: 25 employees, each owed 500.00 and paid exactly 500.00,
    # but every super row's Paid Date is blank.
    n = 25
    payroll_lines = ["Employee Name,Date,Pay Period End,Superannuation Guarantee"]
    super_lines = [
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount"
    ]
    for i in range(n):
        name = f"Employee{i:02d}"
        payroll_lines.append(f"{name},09/07/2026,09/07/2026,500.00")
        super_lines.append(
            f"{name},Superannuation Guarantee,01/07/2026,09/07/2026,,500.00"
        )
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text("\n".join(payroll_lines) + "\n", encoding="utf-8")
    super_path = tmp_path / "super.csv"
    super_path.write_text("\n".join(super_lines) + "\n", encoding="utf-8")

    out = tmp_path / "contributions.csv"
    code = cli_main(
        [
            "import",
            "--payroll",
            str(payroll_path),
            "--super",
            str(super_path),
            "-o",
            str(out),
        ]
    )
    assert code == EXIT_LATE_FOUND
    printed = capsys.readouterr().out

    # All 25 undated figures present, not just the first 19 or 20 once the
    # one structural (name-matching) warning takes a slot.
    undated_lines = re.findall(
        r"row \d+: matched super rows carry no payment date", printed
    )
    assert len(undated_lines) == n
    assert "row 2: matched super rows carry no payment date" in printed  # first
    assert "row 26: matched super rows carry no payment date" in printed  # last

    # Nothing was truncated at all: with every row-level warning exempt from
    # the cap, no "... and N more" line has anything left to summarise.
    assert "... and" not in printed

    # The canonical CSV preserves the association but does not convert it to
    # payment or receipt evidence. The uncapped warning still identifies the
    # row that needs those dates reconciled.
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert rows[0]["employee_id"] == "Employee00"
    assert rows[0]["sg_amount"] == "500.00"
    assert rows[0]["remitted_date"] == ""
    assert rows[0]["matched_amount"] == "500.00"


def test_undated_partial_survives_receipt_date_enrichment_without_full_credit(
    tmp_path,
):
    """A known 600/1000 match must not collapse into legacy full credit.

    The supported workflow writes an import workpaper and later adds the fund
    receipt date. The amount known at import therefore has to survive in a
    machine-readable column even when the vendor supplied no remittance date.
    """
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "A,09/07/2026,09/07/2026,1000.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "A,Superannuation Guarantee,01/07/2026,09/07/2026,,600.00\n",
        encoding="utf-8",
    )
    contributions = tmp_path / "contributions.csv"
    import_files(payroll_path, super_path, contributions, vendor="myob-ar")

    with open(contributions, newline="", encoding="utf-8-sig") as source:
        reader = _csv.DictReader(source)
        rows = list(reader)
        fieldnames = reader.fieldnames
    assert rows[0]["remitted_date"] == ""
    assert rows[0]["remitted_amount"] == ""
    assert rows[0]["matched_amount"] == "600.00"

    rows[0]["fund_received_date"] = "2026-07-15"
    with open(contributions, "w", newline="", encoding="utf-8-sig") as target:
        writer = _csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    report = tmp_path / "report.csv"
    code = cli_main(
        [
            str(contributions),
            "-o",
            str(report),
            "--as-at",
            "2026-08-10",
            "--confirm-transition-allocation",
        ]
    )
    assert code == EXIT_LATE_FOUND
    with open(report, newline="", encoding="utf-8") as source:
        result = next(_csv.DictReader(source))
    assert result["verdict"] == "UNPAID"
    assert Decimal(result["final_shortfall"]) == Decimal("400.00")


def test_structural_warnings_print_before_the_per_row_block(tmp_path, capsys):
    # PART 3(a) REGRESSION. The partial/over exemption from the warning cap
    # used to be implemented by hoisting every partial/over warning above
    # everything else in report.warnings, including the structural "matched
    # on employee name" caveat that says the whole join might have merged
    # two employees who share a name -- a caveat that governs whether the
    # join can be trusted at all. That pushed it to the LAST bullet instead
    # of the first. Structural warnings (join()'s own `warnings`, never
    # prefixed with a row number) must print before the per-row block,
    # whatever mix of uncapped and capped row-level warnings follows.
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "A,09/07/2026,09/07/2026,1000.00\n"
        "B,09/07/2026,09/07/2026,700.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "A,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,999.99\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    code = cli_main(
        [
            "import",
            "--payroll",
            str(payroll_path),
            "--super",
            str(super_path),
            "-o",
            str(out),
        ]
    )
    assert code == EXIT_LATE_FOUND
    printed = capsys.readouterr().out

    structural = (
        "matched on employee name because one of the files has no id column"
    )
    partial = "row 2: partial: 999.99 of 1000.00 matched"  # uncapped category
    unmatched = "row 3: no super payment found"  # capped ("other") category

    assert structural in printed
    assert partial in printed
    assert unmatched in printed
    # The structural warning precedes BOTH row-level categories, not just
    # the one that happens to be capped.
    assert printed.index(structural) < printed.index(partial)
    assert printed.index(structural) < printed.index(unmatched)


def test_import_caps_only_non_partial_warnings_at_a_pinned_literal(tmp_path, capsys):
    # MINOR REVIEW FINDING (round 1). The original version of this test
    # derived its expected "shown" and "remaining" counts by importing
    # MAX_WARNINGS_SHOWN from cli.py, so it could never fail no matter what
    # that constant was changed to -- both sides of every assertion moved
    # together. The counts below (20 shown, 5 hidden) are literals, pinned
    # to today's real MAX_WARNINGS_SHOWN = 20 rather than re-derived from
    # it, so a change to that constant is a real, visible test failure.
    #
    # Employee-id columns are used on both sides so every row matches by
    # id, not name, and no structural "matched on employee name" warning
    # sneaks into the count. One clean anchor payday is matched in full
    # (flag "", no warning at all); 25 further super payments carry an id
    # with no matching payroll row at all, so each becomes an
    # ORPHAN_NO_PAYDAY orphan warning -- none of them partial, over or
    # undated, so all 25 are subject to the cap.
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Employee ID,Date,Pay Period End,Superannuation Guarantee\n"
        "Anchor,E001,09/07/2026,09/07/2026,612.00\n",
        encoding="utf-8",
    )
    super_lines = [
        "Employee Name,Employee ID,Superannuation Category,Period From,Period To,"
        "Paid Date,Amount",
        "Anchor,E001,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,612.00",
    ]
    for i in range(25):
        eid = f"ORPHAN{i:02d}"
        super_lines.append(
            f"{eid},{eid},Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,50.00"
        )
    super_path = tmp_path / "super.csv"
    super_path.write_text("\n".join(super_lines) + "\n", encoding="utf-8")

    out = tmp_path / "contributions.csv"
    code = cli_main(
        [
            "import",
            "--payroll",
            str(payroll_path),
            "--super",
            str(super_path),
            "-o",
            str(out),
        ]
    )
    assert code == EXIT_LATE_FOUND
    printed = capsys.readouterr().out

    assert "employee matching: by id" in printed  # confirms no id-column noise warning
    assert "warnings (25):" in printed
    # Literal 20, not MAX_WARNINGS_SHOWN - 0: if the cap constant in cli.py
    # is changed (even to something degenerate like 1), this count stops
    # matching and the test fails, rather than silently tracking the
    # change.
    assert printed.count("matched no payday") == 20
    assert (
        "... and 5 more (none of them a partial, over-payment or "
        "missing-remittance-date figure -- those are always shown in full "
        "above)" in printed
    )


def test_import_distinguishes_orphan_codes_in_the_console_output(tmp_path, capsys):
    # ORPHAN_PAYDAYS_SETTLED (an overpayment on paydays already settled by
    # their own payments) and ORPHAN_NO_PAYDAY (a payment for an employee
    # with no payroll rows at all) are opposite findings for an accountant.
    # The console output, not just ImportReport, must keep them tellable
    # apart rather than collapsing to one "2 orphans" figure.
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(
        "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
        "A,09/07/2026,09/07/2026,600.00\n"
        "A,23/07/2026,23/07/2026,600.00\n",
        encoding="utf-8",
    )
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
        "A,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,600.00\n"
        "A,Superannuation Guarantee,15/07/2026,23/07/2026,28/07/2026,600.00\n"
        "A,Superannuation Guarantee,01/07/2026,31/07/2026,15/08/2026,500.00\n"
        "B,Superannuation Guarantee,01/07/2026,09/07/2026,14/07/2026,99.00\n",
        encoding="utf-8",
    )
    out = tmp_path / "contributions.csv"
    code = cli_main(
        [
            "import",
            "--payroll",
            str(payroll_path),
            "--super",
            str(super_path),
            "-o",
            str(out),
            "--confirm-statutory-allocation",
        ]
    )
    assert code == EXIT_LATE_FOUND
    printed = capsys.readouterr().out
    assert ORPHAN_PAYDAYS_SETTLED in printed
    assert ORPHAN_NO_PAYDAY in printed
    # The two counts are distinct entries (1 each), not folded into a single
    # combined line.
    assert f"1  {ORPHAN_PAYDAYS_SETTLED}" in printed
    assert f"1  {ORPHAN_NO_PAYDAY}" in printed
    # The section header's own count is the real total (2), not hardcoded --
    # this is a literal pin, independent of report.orphans, so a hardcoded
    # "(0)" or any other wrong figure fails here directly.
    assert "super payments that were not applied to any payday (2):" in printed


def test_import_vendor_flag_forces_a_profile(tmp_path, capsys):
    out = tmp_path / "contributions.csv"
    code = cli_main(
        [
            "import",
            "--payroll",
            str(FIXTURES / "myob_payroll.csv"),
            "--super",
            str(FIXTURES / "myob_super.csv"),
            "-o",
            str(out),
            "--vendor",
            "myob-ar",
        ]
    )
    assert code == EXIT_OK
    printed = capsys.readouterr().out
    assert "myob-ar-payroll" in printed
    assert "myob-ar-super" in printed

    # MINOR REVIEW FINDING (round 1). Without this, the test had no teeth:
    # the myob fixtures auto-detect to myob-ar-payroll/myob-ar-super anyway,
    # so replacing args.vendor with None at the call to import_files would
    # leave every assertion above green. Forcing an incompatible vendor
    # against these fixtures must fail -- proof --vendor genuinely reaches
    # detect() rather than being silently ignored.
    code = cli_main(
        [
            "import",
            "--payroll",
            str(FIXTURES / "myob_payroll.csv"),
            "--super",
            str(FIXTURES / "myob_super.csv"),
            "-o",
            str(out),
            "--vendor",
            "xero",
        ]
    )
    assert code == EXIT_ERROR


def test_the_vendor_advice_is_followable_for_a_two_file_command(tmp_path, capsys):
    # IMPORTANT regression. profiles.detect's message was written for a
    # single-file caller: "--vendor myob" answered "Name the exact profile
    # key with --vendor to pick one", and a user who did exactly that got
    # "--vendor 'myob-ar-payroll' matches no super profile", because
    # import_files passes ONE vendor string to both readers. Only the shared
    # stem works. Walk the chain a user walks and pin that each step points
    # at something that does.
    def run(vendor):
        return cli_main(
            [
                "import",
                "--payroll", str(FIXTURES / "myob_payroll.csv"),
                "--super", str(FIXTURES / "myob_super.csv"),
                "-o", str(tmp_path / "contributions.csv"),
                "--vendor", vendor,
            ]
        )

    assert run("myob") == EXIT_ERROR
    err = capsys.readouterr().err
    assert "myob-ar" in err
    assert "exact profile key" not in err, "the advice that cannot be followed"

    assert run("myob-ar-payroll") == EXIT_ERROR
    err = capsys.readouterr().err
    assert "'myob-ar'" in err

    assert run("myob-ar") == EXIT_OK


def test_import_names_the_failing_file_in_an_os_error(tmp_path, capsys):
    # IMPORTANT REVIEW FINDING (round 1). The import command takes TWO
    # input files, unlike the check command's single csv_path, so its
    # OSError handler cannot fall back to naming "the" input file the way
    # main()'s own `target = exc.filename or args.csv_path` does. The
    # original handler printed only `error: {exc.strerror or exc}` and
    # dropped the filename entirely -- `error: Permission denied` gives no
    # clue which of --payroll/--super failed. A directory in place of a
    # file reproduces a real, common PermissionError on Windows without
    # needing actual OS permissions to be misconfigured.
    a_directory = tmp_path / "a_directory"
    a_directory.mkdir()
    code = cli_main(
        [
            "import",
            "--payroll",
            str(a_directory),
            "--super",
            str(FIXTURES / "myob_super.csv"),
            "-o",
            str(tmp_path / "out.csv"),
        ]
    )
    assert code == EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.err.startswith("error: cannot read ")
    assert str(a_directory) in captured.err
    assert "Traceback" not in captured.err


def test_reconfigure_stdout_for_unicode_prevents_a_non_ascii_crash():
    # MINOR REVIEW FINDING (round 1). Proven directly against a real
    # io.TextIOWrapper set to strict cp1252 -- the shape stdout actually
    # takes when redirected on Windows (PEP 528's fallback locale
    # encoding). Without paydaysuper.cli._reconfigure_stdout_for_unicode,
    # writing a character outside cp1252's range (a CJK character, not
    # merely non-ASCII -- e.g. "e with an accent" is IN cp1252 and would
    # not reproduce the bug) raises UnicodeEncodeError; with it, the same
    # write succeeds and the UTF-8 bytes survive exactly, not mangled or
    # backslash-escaped (utf-8 can represent this character natively, so
    # the errors="backslashreplace" fallback never has to fire here).
    import io

    from paydaysuper.cli import _reconfigure_stdout_for_unicode

    non_cp1252_char = "\u4e2d"  # CJK ideogram, outside Windows-1252's range (not Latin-1)

    before_buffer = io.BytesIO()
    before = io.TextIOWrapper(before_buffer, encoding="cp1252", errors="strict")
    with pytest.raises(UnicodeEncodeError):
        before.write(non_cp1252_char)

    after_buffer = io.BytesIO()
    after = io.TextIOWrapper(after_buffer, encoding="cp1252", errors="strict")
    original_stdout = sys.stdout
    sys.stdout = after
    try:
        _reconfigure_stdout_for_unicode()
        after.write(non_cp1252_char)
        after.flush()
    finally:
        sys.stdout = original_stdout
    assert after_buffer.getvalue() == non_cp1252_char.encode("utf-8")


def test_both_cli_paths_call_the_shared_stdout_reconfigure(tmp_path, monkeypatch):
    # MINOR REVIEW FINDING (round 1). The reconfigure block used to be
    # duplicated verbatim at two call sites (check path and import path);
    # extracted into one shared helper per the review, both call sites must
    # still actually call it. A spy wrapping the real implementation proves
    # both main() and import_main() reach it exactly once per run, on a
    # real successful run of each (not merely that the helper works in
    # isolation, which the test above already covers).
    import paydaysuper.cli as cli_module

    calls = []
    real = cli_module._reconfigure_stdout_for_unicode

    def _spy():
        calls.append(True)
        real()

    monkeypatch.setattr(cli_module, "_reconfigure_stdout_for_unicode", _spy)

    out = tmp_path / "contributions.csv"
    code = cli_main(
        [
            "import",
            "--payroll",
            str(FIXTURES / "myob_payroll.csv"),
            "--super",
            str(FIXTURES / "myob_super.csv"),
            "-o",
            str(out),
        ]
    )
    assert code == EXIT_OK
    assert len(calls) == 1

    from conftest import SAMPLE

    report_out = tmp_path / "report.csv"
    code = cli_main(
        [
            str(SAMPLE),
            "-o",
            str(report_out),
            "--as-at",
            "2026-09-01",
            "--confirm-transition-allocation",
        ]
    )
    assert code == EXIT_LATE_FOUND
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Blocker: amounts are quantised to cents at the read boundary
# ---------------------------------------------------------------------------


SUBCENT_PAYROLL = (
    "Employee Name,Date,Pay Period End,Superannuation Guarantee\n"
    "Test Employee Two,09/07/2026,09/07/2026,{owed}\n"
    "Test Employee Two,23/07/2026,23/07/2026,600.00\n"
)

SUBCENT_SUPER = (
    "Employee Name,Superannuation Category,Period From,Period To,Paid Date,Amount\n"
    "Test Employee Two,Superannuation Guarantee,01/07/2026,09/07/2026,15/07/2026,{first}\n"
    "Test Employee Two,Superannuation Guarantee,01/07/2026,31/07/2026,{second},600.00\n"
)


def _subcent_files(tmp_path, owed, first, second):
    """The blocker's reproduction as two real vendor files.

    Payday 09/07 is settled in full on 15/07, five days inside its 20/07
    deadline, by a super row whose period covers that payday alone. The
    second super row's period spans 09/07 and 23/07, so it reaches a payday
    it did not settle. That is harmless only while the payday has no
    balance left for it to take."""
    payroll_path = tmp_path / "payroll.csv"
    super_path = tmp_path / "super.csv"
    payroll_path.write_text(SUBCENT_PAYROLL.format(owed=owed), encoding="utf-8")
    super_path.write_text(
        SUBCENT_SUPER.format(first=first, second=second), encoding="utf-8"
    )
    return payroll_path, super_path


def _canonical_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(_csv.DictReader(f))


def _outcomes_by_row(payroll_path, super_path):
    payroll_rows, _, _ = read_payroll(payroll_path)
    super_rows, _, _ = read_super(super_path)
    return sorted(join(payroll_rows, super_rows).outcomes, key=lambda o: o.payroll.row)


def test_a_sub_cent_payroll_figure_does_not_drag_the_remittance_date(tmp_path):
    # BLOCKER (final re-review). Payroll owed 540.004 and a dated super row
    # paid 540.00 of it on 15/07. The 0.004 left over stayed in the payday's
    # unmet balance, and the NEXT super row -- one whose period merely spans
    # that payday on its way to a later one -- spent its 0.004 there. That
    # pulled the second row's 30/07 payment date into the match, max() made
    # it the payday's remittance date, and a payday funded in full five days
    # inside its deadline reported LATE for the whole $540.00 with an SG
    # charge estimate on top. Amounts are read to the cent now, so there is
    # no fraction left for the second payment to spend.
    payroll_path, super_path = _subcent_files(tmp_path, "540.004", "540.00", "30/07/2026")
    out = tmp_path / "contributions.csv"
    report = import_files(payroll_path, super_path, out)
    rows = _canonical_rows(out)
    assert rows[0]["payment_date"] == "2026-07-09"
    assert rows[0]["sg_amount"] == "540.00"
    assert rows[0]["remitted_date"] == "2026-07-15"
    assert report.matched == 2
    # No share of the second payment reached the settled payday at all, so
    # there is no "0.004 of 600.00 allocated" note to read past either.
    assert [w for w in report.warnings if "allocated" in w] == []


def test_a_sub_cent_payroll_figure_does_not_blank_the_date_when_the_second_row_is_undated(
    tmp_path,
):
    # The same blocker's other face. With the second super row carrying no
    # payment date, the 0.004 it spent on the settled payday made that
    # payday's match part-undated, `join` blanked `remitted` outright, and
    # the checker read a fully funded payday as $540.00 UNPAID. The settled
    # payday keeps its own 15/07 date now; only the payday that undated
    # payment really did settle goes without one.
    payroll_path, super_path = _subcent_files(tmp_path, "540.004", "540.00", "")
    out = tmp_path / "contributions.csv"
    import_files(payroll_path, super_path, out)
    rows = _canonical_rows(out)
    assert rows[0]["payment_date"] == "2026-07-09"
    assert rows[0]["remitted_date"] == "2026-07-15"
    assert rows[1]["payment_date"] == "2026-07-23"
    assert rows[1]["remitted_date"] == ""


def test_the_cent_clean_control_still_reads_the_same(tmp_path):
    # The control the blocker was found against: the same files but for
    # 540.00 owed rather than 540.004. It always produced 2026-07-15, and
    # the fix must not have moved it.
    payroll_path, super_path = _subcent_files(tmp_path, "540.00", "540.00", "30/07/2026")
    out = tmp_path / "contributions.csv"
    import_files(payroll_path, super_path, out)
    rows = _canonical_rows(out)
    assert rows[0]["remitted_date"] == "2026-07-15"
    assert rows[1]["remitted_date"] == "2026-07-30"


def test_a_sub_cent_figure_on_the_super_side_triggers_nothing_either(tmp_path):
    # The mirror image: 540.00 owed, 539.996 paid. Before the read boundary
    # quantised, that left 0.004 unmet on a payday paid in full to the cent,
    # and the same later payment dragged in the same wrong date.
    payroll_path, super_path = _subcent_files(tmp_path, "540.00", "539.996", "30/07/2026")
    out = tmp_path / "contributions.csv"
    import_files(payroll_path, super_path, out)
    rows = _canonical_rows(out)
    assert rows[0]["remitted_date"] == "2026-07-15"
    # Not merely the right date: the payday reads as settled in full, with
    # no partial flag from the four-tenths of a cent that went missing.
    assert [o.flag for o in _outcomes_by_row(payroll_path, super_path)] == ["", ""]


def test_the_blocker_reproduction_checks_clean_end_to_end(tmp_path, capsys):
    # Through both commands, the way a user meets it: import, then check.
    # The verdict and the dollar figure are what the blocker got wrong, so
    # pin those, not only the date in the intermediate file.
    payroll_path, super_path = _subcent_files(tmp_path, "540.004", "540.00", "30/07/2026")
    out = tmp_path / "contributions.csv"
    assert (
        cli_main(
            ["import", "--payroll", str(payroll_path), "--super", str(super_path),
             "-o", str(out), "--confirm-statutory-allocation"]
        )
        == EXIT_OK
    )
    capsys.readouterr()
    code = cli_main(
        [
            str(out),
            "-o",
            str(tmp_path / "report.csv"),
            "--as-at",
            "2026-08-03",
            "--confirm-transition-allocation",
        ]
    )
    printed = capsys.readouterr().out
    assert code == EXIT_LATE_FOUND
    assert "cannot produce ON_TIME" in printed
    assert "LATE: 0" in printed and "UNPAID: 0" in printed
    assert "shortfall $540.00" not in printed
    assert "SG charge estimate" not in printed


def test_amounts_are_read_to_the_cent_half_up():
    # ROUND_HALF_UP through report.cents, the same rounding money() applies
    # on the way out, so the figure read and the figure written are one
    # rounding of the input rather than two. ROUND_HALF_EVEN, the default a
    # bare quantize() would take, gives 612.00 for 612.005.
    assert _amount("540.004", "sg amount", 2) == Decimal("540.00")
    assert _amount("539.996", "amount", 2) == Decimal("540.00")
    assert _amount("612.005", "sg amount", 2) == Decimal("612.01")
    assert _amount("0.005", "amount", 2) == Decimal("0.01")
    assert _amount("1e2", "amount", 2) == Decimal("100.00")
    assert _amount("1,234.567", "amount", 2) == Decimal("1234.57")
    # Cent-clean by construction: the exponent, not only the value, because
    # that is what stops a later subtraction producing a third decimal.
    assert _amount("612", "sg amount", 2).as_tuple().exponent == -2


def test_an_amount_under_half_a_cent_is_refused_rather_than_rounded_away():
    # The decision quantising at the read boundary forces. Trimming 540.004
    # to 540.00 costs a fraction of a cent no report here could ever show
    # anyway. Rounding 0.004 to 0.00 destroys the row instead: a payment
    # that still carries a date and still matches a payday while carrying no
    # money, or a liability that silently becomes a payday owing nothing.
    # Refused loudly instead, naming the row and the field.
    with pytest.raises(CsvError, match=r"row 4: amount value '0\.004' is under half a cent"):
        _amount("0.004", "amount", 4)
    with pytest.raises(CsvError, match=r"sg amount value '0\.0049' is under half a cent"):
        _amount("0.0049", "sg amount", 2)
    # An exact zero is not a rounding casualty. A payday owing no super
    # guarantee is ordinary, and already has an outcome of its own.
    assert _amount("0", "sg amount", 2) == Decimal("0.00")
    assert _amount("0.00", "amount", 2) == Decimal("0.00")


def test_a_sub_cent_row_is_refused_through_the_whole_import(tmp_path, capsys):
    payroll_path, super_path = _subcent_files(tmp_path, "0.004", "540.00", "30/07/2026")
    code = cli_main(
        ["import", "--payroll", str(payroll_path), "--super", str(super_path),
         "-o", str(tmp_path / "contributions.csv")]
    )
    assert code == EXIT_ERROR
    assert "under half a cent" in capsys.readouterr().err


def _received(outcome):
    """What one payroll row was actually allocated, read back off the flag
    `join` wrote. Anything other than the full sg_amount is named there."""
    partial = re.match(r"partial: (\S+) of ", outcome.flag)
    if partial:
        return Decimal(partial.group(1))
    over = re.match(r"over: (\S+) against ", outcome.flag)
    if over:
        return Decimal(over.group(1))
    if outcome.flag in ("no super payment found", "no super guarantee owed for this payday"):
        return Decimal("0")
    return outcome.payroll.sg_amount


def test_unmet_never_holds_a_sub_cent_residue_and_money_is_conserved(monkeypatch):
    # The invariant the whole fix rests on, checked over the allocator
    # itself rather than argued from the read boundary alone. `_unmet` is
    # wrapped, so every balance the allocator actually works with is
    # inspected, across thousands of randomised joins built from figures
    # that DO carry sub-cent digits in the file.
    #
    # Money conservation and determinism ride along, because the read
    # boundary now changes a value on its way in: every cent of every super
    # row that was used lands on exactly one payday, nothing is invented,
    # and the same rows in any order render identically.
    import paydaysuper.join as join_module

    balances = []
    real_unmet = join_module._unmet

    def spy(row, allocated_total):
        value = real_unmet(row, allocated_total)
        balances.append(value)
        return value

    monkeypatch.setattr(join_module, "_unmet", spy)

    rng = random.Random(20260804)
    paydays = ["2026-07-09", "2026-07-23", "2026-08-06"]
    figures = ["540.004", "539.996", "600.00", "612.005", "0.01", "1,234.567", "$ 300.00", "0"]
    starts = ["2026-07-01", "2026-07-10"]
    ends = ["2026-07-09", "2026-07-23", "2026-07-31", "2026-08-06", "2026-08-10"]
    paids = ["2026-07-15", "2026-07-30", None]
    refused = 0
    joined = 0
    inspected = 0  # balances `_unmet` actually produced, over the whole run
    for trial in range(3000):
        payroll_rows = [
            PayrollRow(None, "A", date.fromisoformat(d), date.fromisoformat(d),
                       _amount(rng.choice(figures), "sg amount", i), i)
            for i, d in enumerate(paydays, start=2)
        ]
        super_rows = []
        for i in range(2, 2 + rng.randint(1, 4)):
            paid = rng.choice(paids)
            super_rows.append(
                SuperRow(
                    None, "A",
                    date.fromisoformat(rng.choice(starts)),
                    date.fromisoformat(rng.choice(ends)),
                    date.fromisoformat(paid) if paid else None,
                    _amount(rng.choice(figures), "amount", i),
                    i,
                )
            )
        balances.clear()
        try:
            result = join(list(payroll_rows), list(super_rows))
        except CsvError:
            refused += 1
            continue  # an ambiguity refusal is a valid outcome, not a residue
        joined += 1

        inspected += len(balances)
        for value in balances:
            assert value == value.quantize(Decimal("0.01")), (trial, value)

        allocated = sum((_received(o) for o in result.outcomes), Decimal("0"))
        used = sum(
            (s.amount for s in super_rows if s not in result.orphans), Decimal("0")
        )
        assert allocated == used, (trial, allocated, used)
        assert allocated == allocated.quantize(Decimal("0.01")), (trial, allocated)

        shuffled_payroll = list(payroll_rows)
        shuffled_super = list(super_rows)
        rng.shuffle(shuffled_payroll)
        rng.shuffle(shuffled_super)
        assert _render(join(shuffled_payroll, shuffled_super)) == _render(result), trial
    # Guard the guard. A run where nearly everything was refused, or where
    # every super row happened to cover one payday and `_unmet` was never
    # reached, would sail through the loop above having tested almost
    # nothing. `_unmet` is only consulted for a payment more than one payday
    # could claim, which is exactly the shape the blocker needed.
    assert joined > 1500, (joined, refused)
    assert inspected > 3000, inspected


def test_the_importer_reads_excels_accounting_format_too(tmp_path):
    # csv_io._parse_amount's regression, on the importer's side of the same
    # shared pattern. The two parsers exist to agree about what a figure
    # means, so a file the checker reads and the importer refuses is exactly
    # the drift they were built to prevent.
    payroll_path, super_path = _subcent_files(tmp_path, "$ 540.00", "$  540.00", "30/07/2026")
    out = tmp_path / "contributions.csv"
    import_files(payroll_path, super_path, out)
    rows = _canonical_rows(out)
    assert rows[0]["sg_amount"] == "540.00"
    assert rows[0]["remitted_date"] == "2026-07-15"


def test_a_vendor_that_matches_nothing_is_not_told_to_type_myob(tmp_path, capsys):
    # COSMETIC (final re-review). `--vendor quickbooks` matched no profile
    # and was answered with the advice written for someone who typed a real
    # profile key that was too long: "name the stem both of a vendor's
    # profiles start with -- 'myob-ar', not 'myob-ar-payroll'". Neither name
    # in that sentence has anything to do with what was typed. The advice
    # belongs only where the name typed really is one of this vendor's own
    # keys worn too long.
    code = cli_main(
        [
            "import",
            "--payroll", str(FIXTURES / "myob_payroll.csv"),
            "--super", str(FIXTURES / "myob_super.csv"),
            "-o", str(tmp_path / "contributions.csv"),
            "--vendor", "quickbooks",
        ]
    )
    err = capsys.readouterr().err
    assert code == EXIT_ERROR
    assert "matches no payroll profile" in err
    assert "'myob-ar'" not in err
    assert "name the stem" not in err
    # The list of what IS available survives: it is the part that answers
    # the question actually asked.
    assert "xero-payroll" in err


def test_import_calls_a_failed_write_a_write_even_with_a_relative_output(tmp_path, monkeypatch, capsys):
    # ROUND 9. The handler decided read-vs-write by comparing exc.filename
    # against a RESOLVED --output. The writer is deliberately handed the
    # originally selected path, so exc.filename comes back unresolved and the
    # comparison never matched for a relative -o, including the default. A
    # failed write was then announced as "cannot read <output>" -- a file the
    # user never supplied as an input at all.
    monkeypatch.chdir(tmp_path)
    # a directory in place of the output file makes the write fail, without
    # needing OS permissions to be misconfigured
    (tmp_path / "contributions.csv").mkdir()

    code = cli_main(
        [
            "import",
            "--payroll",
            str(FIXTURES / "myob_payroll.csv"),
            "--super",
            str(FIXTURES / "myob_super.csv"),
        ]
    )

    assert code != 0
    err = capsys.readouterr().err
    assert "cannot write" in err
    assert "cannot read" not in err


# ---------------------------------------------------------------------------
# Beam status gate: a batch whose status shows the money never left the
# employer must not have its Payment Date written as a remittance date.
# ---------------------------------------------------------------------------

EH_PAYROLL = (
    "Employee,Date Paid,Pay Period Ending,Super Guarantee\n"
    "Test Employee One,09/07/2026,09/07/2026,612.00\n"
)

EH_SUPER = (
    "Employee,Contribution Type,Period Start,Period End,Payment Date,Amount,Status\n"
    "Test Employee One,Super Guarantee,01/07/2026,09/07/2026,{paid},612.00,{status}\n"
)


def _eh_files(tmp_path, status, paid="14/07/2026"):
    payroll_path = tmp_path / "payroll.csv"
    payroll_path.write_text(EH_PAYROLL, encoding="utf-8")
    super_path = tmp_path / "super.csv"
    super_path.write_text(EH_SUPER.format(paid=paid, status=status), encoding="utf-8")
    return payroll_path, super_path


def test_a_created_batch_is_not_written_as_a_remitted_payday(tmp_path):
    # CRITICAL regression. The employment-hero-super profile mapped the Beam
    # Status column, read_super resolved it, and then nothing ever looked at
    # it: a batch at Status=Created -- money never sent -- had its Payment
    # Date written straight into remitted_date, the import exited 0, and the
    # checker read a wholly unfunded payday as AT_RISK "remitted by the
    # deadline" instead of unpaid.
    payroll_path, super_path = _eh_files(tmp_path, "Created")
    out = tmp_path / "contributions.csv"
    report = import_files(payroll_path, super_path, out, vendor="employment-hero")

    rows = _canonical_rows(out)
    assert rows[0]["sg_amount"] == "612.00"
    assert rows[0]["remitted_date"] == "", "a Created batch was never paid"
    assert report.outcome_counts.get(OUTCOME_UNDATED) == 1
    assert report.clean is False
    # The caveat names the status: the export DOES carry a date, and the
    # status is the reason it was not used.
    assert any(
        "super row 2" in w and "'Created'" in w and "never left the employer" in w
        for w in report.warnings
    ), report.warnings


def test_a_created_batch_exits_nonzero_through_the_real_cli(tmp_path, capsys):
    payroll_path, super_path = _eh_files(tmp_path, "Created")
    out = tmp_path / "contributions.csv"
    code = cli_main(
        ["import", "--payroll", str(payroll_path), "--super", str(super_path),
         "-o", str(out), "--vendor", "employment-hero"]
    )
    printed = capsys.readouterr().out
    assert code == EXIT_LATE_FOUND, "an unfunded payday must not exit 0"
    assert "'Created'" in printed
    assert _canonical_rows(out)[0]["remitted_date"] == ""


@pytest.mark.parametrize("status", ["Created", "Submission accepted", "Awaiting payment"])
def test_every_not_yet_paid_beam_status_blanks_the_paid_date(tmp_path, status):
    _, super_path = _eh_files(tmp_path, status)
    rows, _, _ = read_super(super_path, vendor="employment-hero")
    assert rows[0].paid_date is None
    assert rows[0].unpaid_status == status


@pytest.mark.parametrize(
    "status",
    [
        "Awaiting clearance",
        "Sent to fund",
        "Reconciled",
        # Status comparison folds like every other heading-shaped value.
        "RECONCILED",
    ],
)
def test_every_sent_beam_status_keeps_the_paid_date(tmp_path, status):
    payroll_path, super_path = _eh_files(tmp_path, status)
    rows, _, _ = read_super(super_path, vendor="employment-hero")
    assert rows[0].paid_date == date(2026, 7, 14)
    assert rows[0].unpaid_status is None

    out = tmp_path / "contributions.csv"
    report = import_files(payroll_path, super_path, out, vendor="employment-hero")
    assert _canonical_rows(out)[0]["remitted_date"] == "2026-07-14"
    assert report.clean is True


@pytest.mark.parametrize("status", ["Processing", ""])
def test_a_status_outside_the_beam_ladder_is_refused_not_guessed(tmp_path, status):
    # A status the profile does not classify could mean either thing, and
    # guessing "paid" writes a remittance date for money that may never have
    # left, while guessing "unpaid" invents a shortfall. Refused instead,
    # naming the row.
    _, super_path = _eh_files(tmp_path, status)
    with pytest.raises(CsvError) as exc:
        read_super(super_path, vendor="employment-hero")
    message = str(exc.value)
    assert "row 2" in message
    assert "status" in message


def test_eh_super_without_a_status_column_is_refused(tmp_path):
    # Forced with --vendor, detection's signature check never runs, so a
    # Status-less file would otherwise read every Payment Date as a
    # remittance again -- the exact defect the status gate exists to stop.
    super_path = tmp_path / "super.csv"
    super_path.write_text(
        "Employee,Contribution Type,Period Start,Period End,Payment Date,Amount\n"
        "Test Employee One,Super Guarantee,01/07/2026,09/07/2026,14/07/2026,612.00\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError, match="payment status column"):
        read_super(super_path, vendor="employment-hero")
