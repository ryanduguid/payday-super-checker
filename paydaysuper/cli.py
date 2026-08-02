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
from .rates import RatesError, load_gic
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        as_at = (
            datetime.strptime(args.as_at, "%Y-%m-%d").date() if args.as_at else date.today()
        )
        mapping = load_mapping(args.mapping_file, args.map)
        lines = parse_rows(args.csv_path, mapping)
        cal = load_calendar(args.holidays_override)
        gic = load_gic()
        results = assess(lines, cal, gic, as_at)
    except (CsvError, CalendarError, RatesError, PreRegimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except FileNotFoundError as exc:
        print(f"error: file not found: {exc.filename}", file=sys.stderr)
        return EXIT_ERROR

    write_csv(results, args.output)
    print(console_summary(results, as_at, Path(args.output), LAW_CONTENT_DATE))

    return EXIT_LATE_FOUND if any(r.verdict == LATE for r in results) else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
