import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from paydaysuper.csv_io import CsvError, load_mapping, parse_date_text, parse_rows

from conftest import SAMPLE as FIXTURE

HEADER = (
    "employee_id,payment_date,sg_amount,remitted_date,fund_received_date,"
    "first_contribution_to_fund,out_of_cycle,next_standard_payday,defined_benefit\n"
)


def write_csv(tmp_path: Path, *rows: str) -> Path:
    path = tmp_path / "pay.csv"
    path.write_text(HEADER + "".join(r + "\n" for r in rows), encoding="utf-8")
    return path


def test_parses_the_sample_fixture():
    lines = parse_rows(FIXTURE, *load_mapping(None))
    assert len(lines) == 10
    first = lines[0]
    assert first.employee_id == "EMP001"
    assert first.qe_day == date(2026, 7, 9)
    assert first.sg_amount == Decimal("612.00")
    assert first.received == date(2026, 7, 16)
    assert first.row == 2
    assert lines[4].first_to_fund is True
    assert lines[5].out_of_cycle is True
    assert lines[5].next_standard_qe_day == date(2026, 7, 23)
    assert lines[6].db_interest is True


def test_blank_optional_dates_become_none(tmp_path):
    path = write_csv(tmp_path, "E1,2026-07-09,600.00,,,no,no,,no")
    line = parse_rows(path, *load_mapping(None))[0]
    assert line.remitted is None and line.received is None


def test_day_first_dates_are_accepted(tmp_path):
    path = write_csv(tmp_path, "E1,09/07/2026,600.00,,,no,no,,no")
    assert parse_rows(path, *load_mapping(None))[0].qe_day == date(2026, 7, 9)


def test_currency_formatting_is_accepted(tmp_path):
    path = write_csv(tmp_path, 'E1,2026-07-09,"$1,234.56",,,no,no,,no')
    assert parse_rows(path, *load_mapping(None))[0].sg_amount == Decimal("1234.56")


def test_a_comma_in_the_decimal_position_is_refused_not_read_as_thousands(tmp_path):
    # Carried audit finding. This reader stripped every comma regardless of
    # position, so the European decimal 612,00 read as 61200: a hand-edited
    # canonical file reported a $612.00 shortfall as $61,200.00, with an SG
    # charge estimate of $62,010.11 - $99,216.18 against a true $620.10 -
    # $992.16. importers._amount already refused exactly this input, and the
    # README invites hand-editing the canonical file, so one package cannot
    # ship two amount parsers that disagree by 100x. Both now read the same
    # pattern, csv_io.AMOUNT_TEXT.
    path = write_csv(tmp_path, 'E1,2026-07-09,"612,00",,,no,no,,no')
    with pytest.raises(CsvError, match="612,00 is refused"):
        parse_rows(path, *load_mapping(None))


def test_a_thousands_separator_is_still_read(tmp_path):
    # Teeth for the test above: the refusal turns on WHERE the separator
    # sits, not on commas as such. Deleting the new check would leave this
    # green, and deleting the comma stripping entirely would fail it.
    path = write_csv(tmp_path, 'E1,2026-07-09,"1,234,567.89",,,no,no,,no')
    assert parse_rows(path, *load_mapping(None))[0].sg_amount == Decimal("1234567.89")


def test_a_space_after_the_dollar_sign_is_read(tmp_path):
    # REGRESSION (final re-review). Excel's accounting format puts the sign
    # flush left and the figure flush right, so a pasted cell reads
    # "$ 612.00". Removing the "$" left the space behind in the text the new
    # AMOUNT_TEXT pattern was matched against, and the file was refused with
    # a message blaming a comma for a space. It parsed at fd58595 and parses
    # again.
    path = write_csv(tmp_path, 'E1,2026-07-09,"$ 612.00",,,no,no,,no')
    assert parse_rows(path, *load_mapping(None))[0].sg_amount == Decimal("612.00")


@pytest.mark.parametrize(
    "text, expected",
    [
        # Every amount shape that parsed at fd58595, the commit before the
        # separator rule arrived, with the value it produced then. The rule
        # is about WHERE a comma or space sits; narrowing the pattern past
        # that quietly took four unrelated shapes with it, all of which a
        # spreadsheet or an ERP extract does emit.
        ("612.00", "612.00"),
        ("612", "612"),
        ("$612.00", "612.00"),
        ("$ 612.00", "612.00"),
        ("$  612.00", "612.00"),
        (" 612.00 ", "612.00"),
        ("$612.00 ", "612.00"),
        ("1,234.00", "1234.00"),
        ("$1,234.00", "1234.00"),
        ("$ 1,234.00", "1234.00"),
        ("$  1,234.00", "1234.00"),
        ("1 234.00", "1234.00"),
        ("1,234,567.89", "1234567.89"),
        ("1 234 567.89", "1234567.89"),
        ("12,345", "12345"),
        (".50", "0.50"),
        ("612.", "612"),
        ("+612.00", "612.00"),
        ("1e2", "1E+2"),
        ("1E2", "1E+2"),
        ("1e+2", "1E+2"),
        ("1.5e3", "1.5E+3"),
        ("1,000e2", "1.000E+5"),
    ],
)
def test_every_amount_shape_that_parsed_before_the_separator_rule_still_parses(
    tmp_path, text, expected
):
    path = write_csv(tmp_path, f'E1,2026-07-09,"{text}",,,no,no,,no')
    assert parse_rows(path, *load_mapping(None))[0].sg_amount == Decimal(expected)


@pytest.mark.parametrize(
    "text",
    [
        "612,00",
        "1,2",
        "1,23",
        "1 2",
        "1234,567",
        "1,234,56",
        "12,34,567",
        "1,,234",
    ],
)
def test_a_separator_out_of_the_thousands_position_stays_refused(tmp_path, text):
    # The other side of the same pattern, and the reason it exists: each of
    # these parsed at fd58595 and each read a hundred or a thousand times
    # the figure the file meant.
    path = write_csv(tmp_path, f'E1,2026-07-09,"{text}",,,no,no,,no')
    with pytest.raises(CsvError, match="is refused"):
        parse_rows(path, *load_mapping(None))


def test_impossible_date_is_rejected_with_row_number(tmp_path):
    path = write_csv(tmp_path, "E1,31/02/2026,600.00,,,no,no,,no")
    with pytest.raises(CsvError, match="row 2"):
        parse_rows(path, *load_mapping(None))


def test_date_with_trailing_junk_is_rejected(tmp_path):
    path = write_csv(tmp_path, "E1,2026-07-09 not-a-time,600.00,,,no,no,,no")
    with pytest.raises(CsvError, match="row 2"):
        parse_rows(path, *load_mapping(None))


def test_iso_datetime_is_accepted_as_its_calendar_day(tmp_path):
    path = write_csv(tmp_path, "E1,2026-07-09T14:30:00+10:00,600.00,,,no,no,,no")
    assert parse_rows(path, *load_mapping(None))[0].qe_day == date(2026, 7, 9)


@pytest.mark.parametrize(
    "text",
    [
        # .NET DateTime and SQL Server datetime2 stamp seven fractional-second
        # digits; the last case is a nine-digit nanosecond stamp. Python 3.10,
        # the declared floor, refuses a fraction longer than six digits that
        # 3.11+ truncates itself, so these are the cases that exercise the
        # parser's own truncation on the floor version.
        "2026-07-09T00:00:00.0000000",
        "2026-07-09 00:00:00.0000000",
        "2026-07-09T00:00:00.0000000Z",
        "2026-07-09T14:30:00.1234567+10:00",
        "2026-07-09 00:00:00.000000000",
    ],
)
def test_long_fractional_seconds_parse_the_same_on_every_supported_python(text):
    assert parse_date_text(text) == date(2026, 7, 9)


def test_dotnet_timestamp_is_accepted_as_its_calendar_day(tmp_path):
    path = write_csv(tmp_path, "E1,2026-07-09T00:00:00.0000000,600.00,,,no,no,,no")
    assert parse_rows(path, *load_mapping(None))[0].qe_day == date(2026, 7, 9)


@pytest.mark.parametrize(
    "text",
    [
        "20260709",
        "2026-W28-4",
        "2026-07",
        # Shapes newer interpreters read but 3.10, the declared floor,
        # refuses: comma decimal seconds, compact times, hour-only offsets.
        # The shape gate refuses them on every version.
        "2026-07-09T00:00:00,1234567",
        "2026-07-09T000000",
        "2026-07-09T00:00:00+10",
    ],
)
def test_iso_shapes_beyond_the_documented_surface_are_refused(text):
    # fromisoformat on Python 3.11+ reads compact dates, week dates and bare
    # year-months (2026-07 as its FIRST day); 3.10 refuses all three and the
    # README documents none of them. Refused on every version rather than
    # parsed on some: version-dependent acceptance is how the same file gets
    # two different compliance verdicts.
    assert parse_date_text(text) is None


@pytest.mark.parametrize(
    "text",
    [
        # Python 3.10 fromisoformat accepts only 3- or 6-digit fractions;
        # zero-padding to microseconds makes short fractions parse the same
        # on every supported interpreter.
        "2026-07-09T14:30:00.5+10:00",
        "2026-07-09T00:00:00.12345",
        "2026-07-09 23:59:59.1",
    ],
)
def test_short_fractional_seconds_parse_the_same_on_every_supported_python(text):
    assert parse_date_text(text) == date(2026, 7, 9)


def test_unreadable_amount_is_rejected(tmp_path):
    path = write_csv(tmp_path, "E1,2026-07-09,n/a,,,no,no,,no")
    with pytest.raises(CsvError, match="row 2"):
        parse_rows(path, *load_mapping(None))


def test_negative_amount_is_rejected(tmp_path):
    path = write_csv(tmp_path, "E1,2026-07-09,-600.00,,,no,no,,no")
    with pytest.raises(CsvError, match="negative"):
        parse_rows(path, *load_mapping(None))


def test_empty_employee_id_is_rejected(tmp_path):
    path = write_csv(tmp_path, ",2026-07-09,600.00,,,no,no,,no")
    with pytest.raises(CsvError, match="employee_id is empty"):
        parse_rows(path, *load_mapping(None))


def test_unreadable_flag_is_rejected(tmp_path):
    path = write_csv(tmp_path, "E1,2026-07-09,600.00,,,maybe,no,,no")
    with pytest.raises(CsvError, match="yes/no"):
        parse_rows(path, *load_mapping(None))


def test_missing_required_column_names_it(tmp_path):
    path = tmp_path / "pay.csv"
    path.write_text("employee_id,sg_amount\nE1,600.00\n", encoding="utf-8")
    with pytest.raises(CsvError, match="payment_date"):
        parse_rows(path, *load_mapping(None))


def test_header_only_file_is_rejected(tmp_path):
    path = tmp_path / "pay.csv"
    path.write_text(HEADER, encoding="utf-8")
    with pytest.raises(CsvError, match="no data rows"):
        parse_rows(path, *load_mapping(None))


def test_utf8_bom_header_is_handled(tmp_path):
    path = tmp_path / "pay.csv"
    path.write_text(HEADER + "E1,2026-07-09,600.00,,,no,no,,no\n", encoding="utf-8-sig")
    assert parse_rows(path, *load_mapping(None))[0].employee_id == "E1"


def test_mapping_overrides_apply(tmp_path):
    path = tmp_path / "pay.csv"
    path.write_text("Emp,PayDate,Super\nE1,2026-07-09,600.00\n", encoding="utf-8")
    mapping, explicit = load_mapping(None, ["employee_id=Emp", "qe_day=PayDate", "sg_amount=Super"])
    assert parse_rows(path, mapping, explicit)[0].sg_amount == Decimal("600.00")


def test_mapping_file_is_read(tmp_path):
    mapping_file = tmp_path / "map.json"
    mapping_file.write_text(
        json.dumps({"employee_id": "Emp", "qe_day": "PayDate", "sg_amount": "Super"}),
        encoding="utf-8",
    )
    path = tmp_path / "pay.csv"
    path.write_text("Emp,PayDate,Super\nE1,2026-07-09,600.00\n", encoding="utf-8")
    assert parse_rows(path, *load_mapping(mapping_file))[0].employee_id == "E1"


def test_unknown_mapping_field_is_rejected():
    with pytest.raises(CsvError, match="not one of"):
        load_mapping(None, ["payday=PayDate"])


def test_malformed_map_argument_is_rejected():
    with pytest.raises(CsvError, match="field=column"):
        load_mapping(None, ["qe_day"])


def test_duplicate_column_names_are_rejected(tmp_path):
    path = tmp_path / "pay.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,sg_amount\nE1,2026-07-09,600.00,900.00\n",
        encoding="utf-8",
    )
    with pytest.raises(CsvError, match="duplicate column"):
        parse_rows(path, *load_mapping(None))


def test_trailing_empty_headers_are_tolerated(tmp_path):
    """Excel leaves trailing commas on the header row; that is not a
    duplicate-column problem."""
    path = tmp_path / "pay.csv"
    path.write_text(
        "employee_id,payment_date,sg_amount,,\nE1,2026-07-09,600.00,,\n", encoding="utf-8"
    )
    assert parse_rows(path, *load_mapping(None))[0].sg_amount == Decimal("600.00")


def test_truncated_row_is_rejected_not_assumed_blank(tmp_path):
    path = tmp_path / "pay.csv"
    path.write_text(HEADER + "E1,2026-07-09,600.00\n", encoding="utf-8")
    with pytest.raises(CsvError, match="row 2 stops early"):
        parse_rows(path, *load_mapping(None))


def test_mapped_column_that_does_not_exist_is_rejected(tmp_path):
    """A typo in --map must not look the same as an absent column."""
    path = write_csv(tmp_path, "E1,2026-07-09,600.00,,,no,no,,no")
    mapping, explicit = load_mapping(None, ["received=Fund Recieved Date"])
    with pytest.raises(CsvError, match="not found"):
        parse_rows(path, mapping, explicit)


def test_unmapped_optional_column_absence_is_fine(tmp_path):
    path = tmp_path / "pay.csv"
    path.write_text("employee_id,payment_date,sg_amount\nE1,2026-07-09,600.00\n", encoding="utf-8")
    line = parse_rows(path, *load_mapping(None))[0]
    assert line.received is None and line.first_to_fund is False


def test_shipped_example_mapping_file_loads():
    example = FIXTURE.parent / "mapping.example.json"
    mapping, explicit = load_mapping(example)
    assert mapping["qe_day"] == "Payment Date"
    assert "_comment" not in explicit


def test_nan_and_infinity_amounts_are_rejected(tmp_path):
    for text in ("nan", "Infinity", "-Infinity"):
        path = write_csv(tmp_path, f"E1,2026-07-09,{text},,,no,no,,no")
        with pytest.raises(CsvError, match="row 2"):
            parse_rows(path, *load_mapping(None))


def test_row_with_more_values_than_columns_is_rejected(tmp_path):
    path = tmp_path / "pay.csv"
    path.write_text(HEADER + "E1,2026-07-09,600.00,,,no,no,,no,900.00\n", encoding="utf-8")
    with pytest.raises(CsvError, match="more values than the header"):
        parse_rows(path, *load_mapping(None))


def test_mapping_file_that_is_not_an_object_is_rejected(tmp_path):
    mapping_file = tmp_path / "map.json"
    mapping_file.write_text(json.dumps(["employee_id"]), encoding="utf-8")
    with pytest.raises(CsvError, match="JSON object"):
        load_mapping(mapping_file)


def test_mapping_file_that_is_not_json_is_a_csv_error_naming_the_file(tmp_path):
    # json.JSONDecodeError is a ValueError, so the CLI already printed
    # "error: ..." for it, but the message was a bare parse error with no
    # path in it. Re-raised as the module's own error naming the file, the
    # way profiles.load_profiles already does.
    mapping_file = tmp_path / "map.json"
    mapping_file.write_text("{not json", encoding="utf-8")
    with pytest.raises(CsvError) as excinfo:
        load_mapping(mapping_file)
    message = str(excinfo.value)
    assert "is not valid JSON" in message
    assert str(mapping_file) in message


def test_absurdly_large_amount_is_rejected(tmp_path):
    path = write_csv(tmp_path, "E1,2026-07-09,10000000000000000,,,no,no,,no")
    with pytest.raises(CsvError, match="too large"):
        parse_rows(path, *load_mapping(None))
