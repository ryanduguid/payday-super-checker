"""Command-line entry point."""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from . import LAW_CONTENT_DATE, __version__
from .atomic_io import csv_destination
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
from .report import assess, console_summary, needs_attention, write_csv

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_LATE_FOUND = 2


def _reconfigure_stdout_for_unicode() -> None:
    """Redirected stdout on Windows falls back to the locale encoding (cp1252
    under PEP 528), which cannot represent every character a run might need
    to print. The check and import paths both print caller-supplied output
    filenames, which are exactly as free to carry non-ASCII text. Both call
    this, once, before their first print()."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="backslashreplace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="payday-super-check",
        description=(
            "Experimental review of super contributions against payday-super deadlines "
            "(SGAA 1992 s 18C, in force for paydays from 1 July 2026) and "
            "experimental SG-charge exposure estimates on established late ones."
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
    parser.add_argument(
        "--confirm-transition-allocation",
        action="store_true",
        help=(
            "confirm you reconciled every contribution dated no later than 28 Jul "
            "2026 under LCR 2026/1: pre-1 Jul amounts are unused excess and 1-28 Jul "
            "amounts remain after any June-quarter employee shortfall"
        ),
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
            "payments export after the statutory allocation is reconciled. "
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
    parser.add_argument(
        "--confirm-statutory-allocation",
        action="store_true",
        help=(
            "confirm you reconciled LCR 2026/2 allocation using actual fund-receipt "
            "order, every relevant payday and contribution, and any SG-charge "
            "assessment; required when one employee has multiple positive paydays"
        ),
    )
    return parser


# How many warning lines the console output shows in full before summarising
# the rest as a count. A file with thousands of orphaned or row-level
# warnings must not scroll the whole terminal history away. Never applied to
# a structural warning (there are at most a handful of those) or to a
# warning that carries a figure the canonical CSV cannot hold -- see
# _UNCAPPABLE_WARNING.
MAX_WARNINGS_SHOWN = 20

# import_files builds every row-level warning as f"row {n}: {flag}" or
# f"super row {n}: {message}" -- see ImportReport's own docstring -- so this
# tells a row-level warning (this file's per-payday or per-orphan detail)
# apart from a STRUCTURAL warning (join()'s own `warnings`: the employee-key
# fallback, a missing pay-period column), which never carries a row number
# this way. Structural warnings are printed before the row-level block
# regardless of the cap, and are few enough (at most three today) that they
# are never capped either.
_ROW_LEVEL_WARNING = re.compile(r"^(row|super row) \d+: ")

# A partial, over-payment or missing-remittance-date warning carries the
# ONLY surviving record of a figure the canonical CSV cannot hold:
# write_canonical leaves remitted_date blank for an OUTCOME_PARTIAL row
# regardless, and an OUTCOME_UNDATED row's remitted_date is blank for the
# identical reason (join() sets `remitted=None` the moment any part of the
# match is undated) -- both read to the checker as unfunded, and the one
# thing that shows otherwise is this warning line. Truncating either under
# the warning cap would make the caveat printed above the warnings block
# ("the amount that actually arrived is not lost -- it is in the warning
# lines below") false for exactly the rows it matters most for. These are
# therefore exempt from the cap entirely, however many there are; only the
# remaining, less urgent row-level warnings (a plain "no super payment
# found", an orphan message) are capped. Matched by literal text built in
# importers.join -- "partial: "/"over: " prefix the flag, "carry no payment
# date" and "matched has no payment date on record" are the two undated
# phrasings -- the same coupling _classify_outcome documents on itself, and
# equally invisible from here if either wording changes; a test guards it.
_UNCAPPABLE_WARNING = re.compile(
    r"^row \d+: (partial|over): "
    r"|carry no payment date"
    r"|matched has no payment date on record"
)


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
        report = import_files(
            args.payroll,
            args.super_path,
            args.output,
            args.vendor,
            statutory_allocation_confirmed=args.confirm_statutory_allocation,
        )
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
        # This command reads TWO input files and writes one output file, so
        # unlike the single-CSV check path there is no one obvious "the"
        # file to name. open() sets exc.filename to whichever path it was
        # actually working on, so that is trusted first; the join of both
        # input paths is only a fallback for the rare OSError that leaves
        # it unset (e.g. from Path.resolve() rather than open()).
        filename = exc.filename
        target = filename or f"{args.payroll} or {args.super_path}"
        # Resolve BOTH sides. The writer is handed the originally selected
        # output path, so exc.filename comes back unresolved; comparing it
        # against a resolved --output never matched for a relative path,
        # including the default, and a failed write was announced as a failed
        # read of a file the user never supplied. Only compare when the
        # exception carried a filename: the fallback above is a join of the two
        # input paths and must never be read as the output.
        # Compare against the writer's own destination rather than resolving
        # either side. atomic_text_output re-raises with str(csv_destination(
        # out_path)), and importers passes the originally selected --output
        # through unchanged, so this is the exact string the writer used. It
        # is also the only comparison that does not put a user-supplied path
        # through resolve(), which reads the filesystem.
        writing = filename is not None and filename == str(csv_destination(args.output))
        verb = "cannot write" if writing else "cannot read"
        print(f"error: {verb} {target}: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_ERROR

    _reconfigure_stdout_for_unicode()

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
        "Two kinds of payday are written the same as a completely unpaid "
        "one, with remitted_date left blank, and the checker treats both as "
        "a full shortfall. A partly paid payday, because the canonical file "
        "has no column for a part payment. And a payday matched IN FULL "
        "where any of the super rows behind the match carries no payment "
        "date, because a date covering only part of the money would read as "
        "proof the whole of it went. Neither figure is lost -- both are in "
        "the warning lines below, written as \"partial: <received> of "
        "<owed> matched\" and as \"... has no payment date on record\" -- "
        "apply them by hand until the file format can carry them directly.",
    ]

    if report.warnings:
        lines.append("")
        lines.append(f"warnings ({len(report.warnings)}):")
        # Structural warnings first, always in full, however many row-level
        # warnings follow. The employee-key fallback in particular governs
        # whether the whole join can be trusted, so it must never be pushed
        # past a long list of per-row detail -- see _ROW_LEVEL_WARNING.
        structural = [w for w in report.warnings if not _ROW_LEVEL_WARNING.match(w)]
        row_level = [w for w in report.warnings if _ROW_LEVEL_WARNING.match(w)]
        lines.extend(f"  - {w}" for w in structural)
        carries_a_figure = [w for w in row_level if _UNCAPPABLE_WARNING.search(w)]
        other = [w for w in row_level if not _UNCAPPABLE_WARNING.search(w)]
        # Every partial, over-payment or missing-remittance-date warning,
        # always -- never truncated.
        lines.extend(f"  - {w}" for w in carries_a_figure)
        shown_other = other[:MAX_WARNINGS_SHOWN]
        lines.extend(f"  - {w}" for w in shown_other)
        remaining_other = len(other) - len(shown_other)
        if remaining_other > 0:
            lines.append(
                f"  ... and {remaining_other} more (none of them a partial, "
                "over-payment or missing-remittance-date figure -- those are "
                "always shown in full above)"
            )

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
        f"no remittance date {counts.get(OUTCOME_UNDATED, 0)}, "
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
        # Every file this command reads, not only the positional one.
        # --mapping-file and --holidays-override are input files the operator
        # wrote by hand, and an -o aimed at either used to destroy it in
        # silence: the run finished normally and returned its ordinary exit
        # code (EXIT_LATE_FOUND on anything with an exposed line, which a
        # scheduled wrapper reads as a finding rather than an error) with
        # nothing on stderr. The .csv suffix rule below is not a substitute --
        # it constrains the output NAME only, so an override file that happens
        # to be named .csv walks straight past it. importers.import_files
        # guards both of ITS inputs the same way. README.md's "Local file
        # boundary" section and SECURITY.md's "Local path trust boundary"
        # section both state the rule for the tool as a whole, so those two
        # and this loop and that one have to move together.
        output = Path(args.output).resolve()
        for value, label in (
            (args.csv_path, "the input file"),
            (args.mapping_file, "the --mapping-file input"),
            (args.holidays_override, "the --holidays-override input"),
        ):
            if value is not None and Path(value).resolve() == output:
                raise CsvError(
                    f"the report would overwrite {label} {value}. Choose a "
                    "different path with -o."
                )
        # Reject a bad -o here rather than at write time, so the operator is
        # told before the whole assessment runs. write_csv enforces the same
        # rule, but the ValueError it raises reaches a handler that only
        # covers OSError.
        csv_destination(args.output)
        mapping, explicit = load_mapping(args.mapping_file, args.map)
        lines = parse_rows(args.csv_path, mapping, explicit)
        cal = load_calendar(args.holidays_override)
        gic = load_gic()
        rates = load_rates()
        results = assess(
            lines,
            cal,
            gic,
            as_at,
            assessment_date,
            transition_allocation_confirmed=args.confirm_transition_allocation,
        )
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
    except ValueError as exc:
        # Backstop: the -o rule is already checked above, so anything landing
        # here is a new write-time rejection. "error: <message>" either way.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"error: cannot write {args.output}: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_ERROR

    _reconfigure_stdout_for_unicode()
    print(
        console_summary(
            results, as_at, Path(args.output), LAW_CONTENT_DATE, rates, assessment_date
        )
    )

    return EXIT_LATE_FOUND if needs_attention(results) else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
