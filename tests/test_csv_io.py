import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from paydaysuper.csv_io import CsvError, load_mapping, parse_rows

FIXTURE = Path(__file__).parent / "fixtures" / "sample_payrun.csv"

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


def test_impossible_date_is_rejected_with_row_number(tmp_path):
    path = write_csv(tmp_path, "E1,31/02/2026,600.00,,,no,no,,no")
    with pytest.raises(CsvError, match="row 2"):
        parse_rows(path, *load_mapping(None))


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
    example = Path(__file__).parent.parent / "examples" / "mapping.example.json"
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


def test_absurdly_large_amount_is_rejected(tmp_path):
    path = write_csv(tmp_path, "E1,2026-07-09,1e26,,,no,no,,no")
    with pytest.raises(CsvError, match="too large"):
        parse_rows(path, *load_mapping(None))
