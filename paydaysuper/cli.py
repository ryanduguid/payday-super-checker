"""Command-line entry point."""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

from . import LAW_CONTENT_DATE, __version__
from .atomic_io import csv_destination, markdown_destination
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
    parser.add_argument(
        "--confirm-remittance-only",
        action="store_true",
        help=(
            "confirm you accept a remittance-only review: no in-scope positive row "
            "has a fund-receipt date on or before the as-at date, so the file "
            "cannot produce ON_TIME"
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _parse_cli_date(value: str | None, flag: str) -> date | None:
    if value is None:
        return None
    try:
        parsed = parse_date_text(value)
    except CsvError as exc:
        # The offset refusal names no flag of its own; say which one.
        raise CsvError(f"{flag} {exc}")
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


def build_review_pack_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="payday-super-check review-pack",
        description=(
            "Build a deterministic, privacy-conscious practitioner checklist from "
            "a payday-super-checker report CSV. The source CSV remains the row-level "
            "workpaper and every professional judgement remains human-only."
        ),
    )
    parser.add_argument("report_csv", help="report CSV produced by payday-super-check")
    parser.add_argument(
        "-o",
        "--output",
        default="practitioner-review.md",
        help="Markdown review pack to write (default: practitioner-review.md)",
    )
    return parser


def _same_local_path(left: str | Path, right: str | Path) -> bool:
    """Compare operator-selected local paths without dereferencing them here.

    ``realpath`` normalises relative components and follows existing symlinks,
    so an output alias cannot replace the report used as input.  This CLI is a
    single-user local-file tool; the comparison deliberately imposes no
    artificial safe root on the operator's selected workpaper location.
    """
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(
        os.path.realpath(right)
    )


def review_pack_main(argv: list[str]) -> int:
    from .practitioner_pack import (
        PractitionerPackError,
        load_report_snapshot,
        write_practitioner_pack,
    )

    args = build_review_pack_parser().parse_args(argv)
    requested_output = Path(args.output)
    output = requested_output
    try:
        if _same_local_path(args.report_csv, requested_output):
            raise PractitionerPackError(
                f"the review pack would overwrite the input report {args.report_csv}. "
                "Choose a different path with -o."
            )
        output = markdown_destination(requested_output)
        snapshot = load_report_snapshot(args.report_csv)
        write_practitioner_pack(snapshot, output)
    except (PractitionerPackError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except FileNotFoundError as exc:
        print(f"error: file not found: {exc.filename}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        target = exc.filename or args.report_csv
        verb = "cannot write" if exc.filename == str(output) else "cannot read"
        print(f"error: {verb} {target}: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_ERROR

    _reconfigure_stdout_for_unicode()
    print(f"wrote {output}")
    return EXIT_LATE_FOUND if snapshot.needs_attention else EXIT_OK


# How many warning lines the console output shows in full before summarising
# the rest as a count. A file with thousands of orphaned or row-level
# warnings must not scroll the whole terminal history away. Never applied to
# a structural warning (there are at most a handful of those) or to a
# warning whose per-row amount or missing-date fact requires explicit
# reconciliation -- see _UNCAPPABLE_WARNING.
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

# A partial, over-payment or missing-remittance-date warning carries a figure
# the operator still has to reconcile. The canonical CSV now preserves the
# matched total as well as the dated subtotal, but neither amount proves that
# the fund received it. Truncating these warnings would hide which rows need
# that evidence, so they remain exempt from the cap.
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
        # The second load-bearing caveat separates operational remittance from
        # the amount associated with the payday. matched_amount survives even
        # where the vendor supplied no payment date and caps any later receipt.
        "A dated part payment writes remitted_date and remitted_amount; "
        "sg_amount stays the amount owed. matched_amount separately records "
        "the total associated with the payday, even when the vendor supplied "
        "no payment date, and caps any fund receipt later added to the row. "
        "Where a match contains dated and undated super rows, remitted_date is "
        "conservatively the latest known date for the dated subtotal: the "
        "checker credits none of the subtotal before that date and only "
        "remitted_amount afterwards. An entirely undated match leaves both "
        "remittance fields blank but keeps matched_amount. The warning lines "
        "below still name every "
        "partial: <received> of <owed> matched and every \"... has no "
        "payment date on record\" figure.",
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
    if argv and argv[0] == "review-pack":
        return review_pack_main(argv[1:])
    args = build_parser().parse_args(argv)

    try:
        as_at = _parse_cli_date(args.as_at, "--as-at")
        if as_at is None:
            # Named out loud rather than silently assumed: the host clock's
            # calendar day is not necessarily the Australian date -- a UTC
            # server in the hours around midnight AEST is a day behind, and
            # a day is exactly what a deadline verdict turns on. The reader
            # already refuses UTC-marked datetime INPUTS for this reason;
            # the default as-at deserves at least a notice. No timezone
            # conversion is attempted: naming the assumption keeps the
            # operator in charge of it.
            as_at = date.today()
            print(
                f"note: --as-at not supplied; assuming {as_at.isoformat()} from this "
                "machine's clock, which may not be today's date in Australia. Pass "
                "--as-at explicitly in scheduled runs.",
                file=sys.stderr,
            )
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
    except OverflowError:
        # A sentinel date such as 9999-12-31 walked past date.max. Before the
        # ArithmeticError backstop below, which covers this subclass and
        # would otherwise swallow the specific message.
        print(
            "error: a date in this file is too far in the future to work with. "
            "Check for placeholder dates such as 9999-12-31.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    # decimal.InvalidOperation is an ArithmeticError, not a ValueError, so it
    # is not covered by the CsvError/ValueError names below. Every amount read
    # here is already guarded against it (see csv_io._parse_amount and its
    # "too large to be a real amount" check), but this is the check path's own
    # backstop against anything upstream that changes and stops holding that
    # guarantee, mirroring import_main's: a raw traceback is never an
    # acceptable failure mode here, only "error: <message>".
    except (
        CsvError, CalendarError, RatesError, PreRegimeError, ValueError, ArithmeticError
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except FileNotFoundError as exc:
        print(f"error: file not found: {exc.filename}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        target = exc.filename or args.csv_path
        print(f"error: cannot read {target}: {exc.strerror or exc}", file=sys.stderr)
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
    except (ValueError, ArithmeticError) as exc:
        # Backstop: the -o rule is already checked above, so anything landing
        # here is a new write-time rejection. "error: <message>" either way.
        # ArithmeticError because rounding to cents can raise
        # decimal.InvalidOperation here: notional earnings compound an
        # accepted sg_amount, so a figure whose every input passed its own
        # magnitude guard can still outgrow the default decimal context by
        # the time write_csv quantises it.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"error: cannot write {args.output}: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_ERROR

    _reconfigure_stdout_for_unicode()
    try:
        summary = console_summary(
            results,
            as_at,
            Path(args.output),
            LAW_CONTENT_DATE,
            rates,
            assessment_date,
            remittance_only_confirmed=args.confirm_remittance_only,
        )
    except (ValueError, ArithmeticError) as exc:
        # Same backstop as write_csv's, and needed for the same reason:
        # the summary quantises TOTALS across the exposed rows, so figures
        # that each rounded to cents inside write_csv can still sum past
        # the default decimal context here. The report itself is complete
        # on disk by this point, so name that in the message rather than
        # leaving the operator to guess whether the file can be trusted.
        print(
            f"error: {exc}. The report was still written to {args.output}; "
            "only this console summary failed.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    print(summary)

    return (
        EXIT_LATE_FOUND
        if needs_attention(
            results, remittance_only_confirmed=args.confirm_remittance_only
        )
        else EXIT_OK
    )


if __name__ == "__main__":
    raise SystemExit(main())
