"""Command-line entry point."""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from . import LAW_CONTENT_DATE, __version__
from .calendar import CalendarError, load_calendar
from .csv_io import (
    LATEST_SANE_YEAR,
    CsvError,
    load_mapping,
    parse_date_text,
    parse_rows,
)
from .deadlines import PreRegimeError
from .profiles import Profile
from .rates import RatesError, load_gic, load_rates
from .report import EXPOSED, assess, console_summary, write_csv

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
    parsed = parse_date_text(value)
    if parsed is None:
        raise CsvError(
            f"{flag} expects a date such as 2026-08-10 or 10/08/2026, got {value!r}"
        )
    if parsed.year > LATEST_SANE_YEAR:
        raise CsvError(f"{flag} value {value!r} is not a real date")
    return parsed


def build_import_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="payday-super-check import",
        description=(
            "Build the contributions CSV from a payroll export and a super "
            "payments export, matching each payment to the payday it settles. "
            "No payroll system or clearing house exports a fund receipt date, "
            "so fund_received_date is always left blank for you to fill in."
        ),
    )
    parser.add_argument("--payroll", required=True, help="payroll activity export CSV")
    parser.add_argument(
        "--super", dest="super_path", required=True, help="super payments export CSV"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="contributions.csv",
        help="canonical CSV to write (default: contributions.csv)",
    )
    parser.add_argument(
        "--vendor",
        help="force a profile instead of detecting one (e.g. xero, myob-ar, employment-hero)",
    )
    return parser


# How many warning lines the console output shows in full before summarising
# the rest as a count. A file with thousands of orphaned or partial rows must
# not scroll the whole terminal history away.
MAX_WARNINGS_SHOWN = 20


def _profile_line(label: str, profile: Profile) -> str:
    marker = "" if profile.verified else " (unverified against a real export)"
    return f"{label} profile: {profile.key} -- {profile.name}{marker}"


def import_main(argv: list[str]) -> int:
    from .importers import (
        OUTCOME_MATCHED,
        OUTCOME_OVER,
        OUTCOME_OWES_NOTHING,
        OUTCOME_PARTIAL,
        OUTCOME_UNDATED,
        OUTCOME_UNMATCHED,
        import_files,
    )

    args = build_import_parser().parse_args(argv)
    try:
        report = import_files(args.payroll, args.super_path, args.output, args.vendor)
    # decimal.InvalidOperation is an ArithmeticError, not a ValueError, so it
    # is not covered by the CsvError/ValueError branch below. Every amount
    # this module builds is already guarded against it (see importers._amount
    # and its "too large to be a real amount" check), but this is the CLI's
    # own backstop against anything upstream that changes and stops holding
    # that guarantee: a raw traceback is never an acceptable failure mode
    # here, only "error: <message>".
    except (CsvError, ValueError, ArithmeticError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except FileNotFoundError as exc:
        print(f"error: file not found: {exc.filename}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"error: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_ERROR

    # Redirected stdout on Windows falls back to the locale encoding, which
    # cannot represent every employee name.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="backslashreplace")

    lines = [
        _profile_line("payroll", report.payroll_profile),
        _profile_line("super", report.super_profile),
        f"employee matching: by {report.key_mode}",
        "",
        # The single most important caveat this feature carries: every
        # vendor export this tool reads records when a payment left the
        # employer, never when the fund received it, so fund_received_date
        # cannot be filled in from any export and the checker's s 18C
        # deadline tests receipt, not remittance.
        "No payroll or clearing-house export carries a fund receipt date, so "
        "fund_received_date is written blank on every row. The checker's "
        "deadline tests receipt by the fund, not remittance -- fill that "
        "column in from your fund or clearing house before relying on any "
        "verdict it produces.",
        # The second load-bearing caveat: a partial payment and a missed one
        # look identical in the canonical CSV, because the file has no
        # column for a part payment. Silence here is how a 999.99-of-1000.00
        # payday turns into a checker report calling it a full 1000.00
        # shortfall, with an SG-charge estimate to match, and the only place
        # the true 999.99 survives is the warning line below.
        "A partially paid payday is written the same as a completely unpaid "
        "one: remitted_date is left blank, because the canonical file has no "
        "column for a part payment, so the checker will treat it as a full "
        "shortfall. The amount that actually arrived is not lost -- it is in "
        "the warning lines below, written as \"partial: <received> of <owed> "
        "matched\" -- apply that figure by hand until the file format can "
        "carry it directly.",
    ]

    if report.warnings:
        lines.append("")
        lines.append(f"warnings ({len(report.warnings)}):")
        shown = report.warnings[:MAX_WARNINGS_SHOWN]
        lines.extend(f"  - {w}" for w in shown)
        remaining = len(report.warnings) - len(shown)
        if remaining > 0:
            lines.append(f"  ... and {remaining} more")

    if report.orphan_reasons:
        lines.append("")
        lines.append(
            f"super payments that were not applied to any payday ({report.orphans}):"
        )
        # Broken out by code, not just the bare total: an overpayment on
        # paydays already settled (ORPHAN_PAYDAYS_SETTLED) and a payment
        # that matched no payday at all (ORPHAN_NO_PAYDAY) are opposite
        # findings for an accountant and must stay tellable apart here too.
        for code, count in sorted(report.orphan_counts.items()):
            lines.append(f"  {count}  {code}")

    counts = report.outcome_counts
    lines += [
        "",
        f"paydays: matched {counts.get(OUTCOME_MATCHED, 0)}, "
        f"no fund-receipt date {counts.get(OUTCOME_UNDATED, 0)}, "
        f"partial {counts.get(OUTCOME_PARTIAL, 0)}, "
        f"over {counts.get(OUTCOME_OVER, 0)}, "
        f"owes nothing {counts.get(OUTCOME_OWES_NOTHING, 0)}, "
        f"no payment found {counts.get(OUTCOME_UNMATCHED, 0)}",
        f"wrote {args.output}",
    ]

    print("\n".join(lines))
    return EXIT_OK if report.clean else EXIT_LATE_FOUND


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "import":
        return import_main(argv[1:])
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
    except OSError as exc:
        target = exc.filename or args.csv_path
        print(f"error: cannot read {target}: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_ERROR
    except OverflowError:
        # A sentinel date such as 9999-12-31 walked past date.max.
        print(
            "error: a date in this file is too far in the future to work with. "
            "Check for placeholder dates such as 9999-12-31.",
            file=sys.stderr,
        )
        return EXIT_ERROR

    try:
        write_csv(
            results,
            args.output,
            as_at,
            LAW_CONTENT_DATE,
            assessment_date,
            source=Path(args.csv_path).resolve(),
            gic_provenance=gic.provenance(),
        )
    except OSError as exc:
        print(f"error: cannot write {args.output}: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_ERROR

    # Redirected stdout on Windows falls back to the locale encoding, which
    # cannot represent every employee name.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="backslashreplace")
    print(
        console_summary(
            results, as_at, Path(args.output), LAW_CONTENT_DATE, rates, assessment_date
        )
    )

    return EXIT_LATE_FOUND if any(r.verdict in EXPOSED for r in results) else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
