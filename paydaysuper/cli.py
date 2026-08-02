"""Command-line entry point."""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from . import LAW_CONTENT_DATE, __version__
from .calendar import CalendarError, load_calendar
from .csv_io import CsvError, load_mapping, parse_rows
from .deadlines import PreRegimeError
from .rates import RatesError, load_gic, load_rates
from .report import LATE, assess, console_summary, write_csv

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_LATE_FOUND = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="payday-super-check",
        description=(
            "Check super contributions against the payday-super deadlines "
            "(SGAA 1992 s 18C, in force for paydays from 1 July 2026) and "
            "estimate SG-charge exposure on late ones."
        ),
    )
    parser.add_argument("csv_path", help="contribution CSV to check")
    parser.add_argument(
        "-o", "--output", default="report.csv", help="report CSV to write (default: report.csv)"
    )
    parser.add_argument(
        "--as-at",
        help="date to measure unpaid notional earnings to (YYYY-MM-DD, default: today)",
    )
    parser.add_argument(
        "--assessment-date",
        help=(
            "date the ATO assessed the SG charge for these paydays (YYYY-MM-DD). "
            "Only contributions received before it clear the shortfall under s 18D. "
            "Omit if no assessment has issued."
        ),
    )
    parser.add_argument(
        "--mapping-file", help="JSON file mapping canonical field names to your CSV columns"
    )
    parser.add_argument(
        "--map",
        action="append",
        metavar="FIELD=COLUMN",
        help="override one column mapping; repeatable (e.g. --map qe_day=PayDate)",
    )
    parser.add_argument(
        "--holidays-override",
        help="JSON file adding or removing public holidays from the bundled calendar",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _parse_cli_date(value: str | None, flag: str) -> date | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise CsvError(f"{flag} expects a YYYY-MM-DD date, got {value!r}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        as_at = _parse_cli_date(args.as_at, "--as-at") or date.today()
        assessment_date = _parse_cli_date(args.assessment_date, "--assessment-date")
        if Path(args.output).resolve() == Path(args.csv_path).resolve():
            raise CsvError(
                "the report would overwrite the input file. Choose a different "
                "path with -o."
            )
        mapping, explicit = load_mapping(args.mapping_file, args.map)
        lines = parse_rows(args.csv_path, mapping, explicit)
        cal = load_calendar(args.holidays_override)
        gic = load_gic()
        rates = load_rates()
        results = assess(lines, cal, gic, as_at, assessment_date)
    except (CsvError, CalendarError, RatesError, PreRegimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except FileNotFoundError as exc:
        print(f"error: file not found: {exc.filename}", file=sys.stderr)
        return EXIT_ERROR

    try:
        write_csv(results, args.output, as_at, LAW_CONTENT_DATE)
    except OSError as exc:
        print(f"error: cannot write {args.output}: {exc.strerror}", file=sys.stderr)
        return EXIT_ERROR

    print(console_summary(results, as_at, Path(args.output), LAW_CONTENT_DATE, rates))

    return EXIT_LATE_FOUND if any(r.verdict == LATE for r in results) else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
