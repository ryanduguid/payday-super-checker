"""CSV reading with loud failures.

Payroll exports vary, so column names are mapped explicitly. Nothing is
guessed and nothing is coerced silently: a value the parser cannot read
raises with its row number rather than defaulting to zero or today.
"""
from __future__ import annotations

import csv
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .deadlines import ContribLine

CANONICAL = {
    "employee_id": True,
    "qe_day": True,
    "sg_amount": True,
    "remitted": False,
    "received": False,
    "first_to_fund": False,
    "out_of_cycle": False,
    "next_standard_qe_day": False,
    "db_interest": False,
}

DEFAULT_MAPPING = {
    "employee_id": "employee_id",
    "qe_day": "payment_date",
    "sg_amount": "sg_amount",
    "remitted": "remitted_date",
    "received": "fund_received_date",
    "first_to_fund": "first_contribution_to_fund",
    "out_of_cycle": "out_of_cycle",
    "next_standard_qe_day": "next_standard_payday",
    "db_interest": "defined_benefit",
}

TRUE_WORDS = {"y", "yes", "true", "1", "t"}
FALSE_WORDS = {"", "n", "no", "false", "0", "f"}


class CsvError(ValueError):
    pass


def load_mapping(path: str | Path | None, overrides: list[str] | None = None) -> dict[str, str]:
    mapping = dict(DEFAULT_MAPPING)
    if path is not None:
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        unknown = set(user) - set(CANONICAL)
        if unknown:
            raise CsvError(
                f"mapping file has unknown fields: {sorted(unknown)}; "
                f"valid fields are {sorted(CANONICAL)}"
            )
        mapping.update(user)
    for item in overrides or []:
        if "=" not in item:
            raise CsvError(f"--map expects field=column, got {item!r}")
        field, column = item.split("=", 1)
        if field not in CANONICAL:
            raise CsvError(f"--map field {field!r} is not one of {sorted(CANONICAL)}")
        mapping[field] = column
    return mapping


def _parse_date(value: str, field: str, row: int) -> date:
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise CsvError(
        f"row {row}: cannot read {field} value {value!r}: use YYYY-MM-DD or DD/MM/YYYY "
        "(day first, Australian order)"
    )


def _parse_amount(value: str, field: str, row: int) -> Decimal:
    text = value.strip().replace("$", "").replace(",", "").replace(" ", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        raise CsvError(f"row {row}: cannot read {field} value {value!r} as an amount")
    if amount < 0:
        raise CsvError(f"row {row}: {field} is negative ({value!r})")
    return amount


def _parse_bool(value: str, field: str, row: int) -> bool:
    text = value.strip().lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    raise CsvError(f"row {row}: cannot read {field} value {value!r} as yes/no")


def parse_rows(path: str | Path, mapping: dict[str, str]) -> list[ContribLine]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise CsvError(f"{path} has no header row")
        headers = {h.strip() for h in reader.fieldnames}
        missing = [
            mapping[field]
            for field, required in CANONICAL.items()
            if required and mapping[field] not in headers
        ]
        if missing:
            raise CsvError(
                f"{path} is missing required column(s): {missing}. Columns found: "
                f"{sorted(headers)}. Map your own names with --map field=column."
            )

        lines: list[ContribLine] = []
        for i, raw in enumerate(reader, start=2):  # row 1 is the header
            row = {(k.strip() if k else k): (v or "") for k, v in raw.items()}

            def optional(field: str) -> str:
                return row.get(mapping[field], "")

            employee = row[mapping["employee_id"]].strip()
            if not employee:
                raise CsvError(f"row {i}: employee_id is empty")

            remitted_raw = optional("remitted").strip()
            received_raw = optional("received").strip()
            next_raw = optional("next_standard_qe_day").strip()

            line = ContribLine(
                employee_id=employee,
                qe_day=_parse_date(row[mapping["qe_day"]], "qe_day", i),
                sg_amount=_parse_amount(row[mapping["sg_amount"]], "sg_amount", i),
                remitted=_parse_date(remitted_raw, "remitted", i) if remitted_raw else None,
                received=_parse_date(received_raw, "received", i) if received_raw else None,
                first_to_fund=_parse_bool(optional("first_to_fund"), "first_to_fund", i),
                out_of_cycle=_parse_bool(optional("out_of_cycle"), "out_of_cycle", i),
                next_standard_qe_day=(
                    _parse_date(next_raw, "next_standard_qe_day", i) if next_raw else None
                ),
                db_interest=_parse_bool(optional("db_interest"), "db_interest", i),
                row=i,
            )
            lines.append(line)

    if not lines:
        raise CsvError(f"{path} has a header but no data rows")
    return lines
