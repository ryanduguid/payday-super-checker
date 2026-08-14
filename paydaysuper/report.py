"""Verdicts, exposure figures, console summary and report.csv."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from . import __version__
from .atomic_io import atomic_text_output
from .calendar import BusinessCalendar
from .deadlines import (
    ITEM4_ALIGNED,
    REGIME_START,
    SKIP_DB,
    USUAL_7BD,
    ContribLine,
    Deadline,
    PreRegimeError,
    annotate_calendar_risk,
    annotate_missing_flag,
    apply_item4,
    compute_due,
)
from .rates import GicTable
from .sgc import exposure_range, notional_earnings, uplift_scenarios

TRANSITION_END = date(2026, 7, 28)

ON_TIME = "ON_TIME"
LATE = "LATE"
AT_RISK = "AT_RISK"
UNPAID = "UNPAID"
UNKNOWN = "UNKNOWN"
SKIPPED = "SKIPPED"

VERDICTS = (ON_TIME, AT_RISK, LATE, UNPAID, UNKNOWN, SKIPPED)
EXPOSED = (LATE, UNPAID)

CENTS = Decimal("0.01")

# Appended wherever the verdict rests on a remittance date with no
# fund-receipt date supplied at all. Named here so the console can tell it
# apart from a caveat that says something about the particular row: the
# at-risk block's header already says this, so listing it per row would only
# repeat the header. A row whose only receipt date post-dates the as-at date
# gets a distinct variant caveat instead, because "no fund-receipt date
# supplied" would be false there and the variant says something the header
# does not.
NO_RECEIPT_CAVEAT = (
    "no fund-receipt date supplied: the statutory test is receipt by the "
    "fund (SGAA s 18C(1)), so a remittance date alone cannot show the "
    "contribution was on time"
)

# Characters Excel and Sheets can evaluate at the start of a cell. Classifying
# selected suffixes as safe is not reliable: scientific notation, booleans,
# R1C1 references and workbook-defined names can all be alphanumeric. The
# spreadsheet-facing CSV is therefore always quoted after any leading space;
# the source payroll export remains the record of the unmodified identifier.
FORMULA_LEAD = ("=", "+", "-", "@")


def money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return str(value.quantize(CENTS, rounding=ROUND_HALF_UP))


def cents(value: Decimal | None) -> Decimal:
    return Decimal("0") if value is None else value.quantize(CENTS, rounding=ROUND_HALF_UP)


def csv_safe(text: str) -> str:
    """Stop a spreadsheet treating a cell as a formula.

    Applied to every field written from input text, not to a single
    trusted-looking one. This report writes employee ids; `importers.
    write_canonical` writes employee names as well, and puts its dates and
    amounts through the same guard rather than reasoning per field about
    which of them could ever start with `=`.

    The trigger is looked for after leading whitespace, not at position 0:
    a sheet ignores the space, so testing position 0 let " =cmd" through a
    guard that catches "=cmd". Every formula-leading value is quoted. A
    selective suffix rule leaves data-integrity gaps such as `+1E3`, `-R1C1`,
    `+TRUE` and workbook-defined names."""
    stripped = text.lstrip()
    if stripped[:1] in FORMULA_LEAD:
        return "'" + text
    return text


def twelve_months_before(d: date) -> date:
    """The same calendar date a year earlier, with 29 February falling back
    to 28 February."""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, month=2, day=28)


def financial_year(d: date) -> str:
    """Australian financial year label for a date, e.g. 2026-27."""
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"


@dataclass
class Result:
    line: ContribLine
    deadline: Deadline
    verdict: str
    days_late: int | None = None
    lateness_basis: str = ""
    base_shortfall: Decimal | None = None
    final_shortfall: Decimal | None = None
    offset_s18d: bool = False
    nec: Decimal | None = None
    sgc_low: Decimal | None = None
    sgc_high: Decimal | None = None
    uplift: dict[str, dict[str, Decimal]] | None = None
    notes: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    # Set where a material deadline fact cannot be pinned down: either the
    # holiday calendar ends before the deadline or an unevidenced earlier
    # contribution could trigger item 4. Holds the two candidate verdicts,
    # attention-driving outcome first. The historical attribute name is
    # retained for report-CSV and API compatibility.
    horizon_verdicts: tuple[str, str] | None = None

    @property
    def warnings(self) -> list[str]:
        return self.caveats + self.notes


def _date_problem(line: ContribLine) -> str | None:
    if line.received is not None and line.remitted is not None and line.received < line.remitted:
        return (
            f"row {line.row}: fund receipt date {line.received.isoformat()} is before the "
            f"remittance date {line.remitted.isoformat()}, which cannot happen"
        )
    return None


def _flag_duplicates(lines: list[ContribLine]) -> None:
    """Two identical rows are double-counted, and a re-exported pay run is a
    common way to get them. They can also be legitimate (one payday split
    across two funds), so this warns rather than refuses."""
    groups: dict[tuple, list[ContribLine]] = {}
    for line in lines:
        key = (
            line.employee_id,
            line.qe_day,
            line.sg_amount,
            line.remitted,
            line.received,
            line.first_to_fund,
            line.out_of_cycle,
            line.next_standard_qe_day,
            line.db_interest,
        )
        groups.setdefault(key, []).append(line)
    for group in groups.values():
        if len(group) > 1:
            rows = ", ".join(str(line.row) for line in group)
            note = (
                f"rows {rows} are identical, so this payday is counted "
                f"{len(group)} times. Check the export was not doubled"
            )
            for line in group:
                line.duplicate_note = note


def assess(
    lines: list[ContribLine],
    cal: BusinessCalendar,
    gic: GicTable,
    as_at: date,
    assessment_date: date | None = None,
    *,
    transition_allocation_confirmed: bool = False,
) -> list[Result]:
    """Assess each contribution line.

    `assessment_date` is the day the ATO made (or is assumed to make) an SG
    charge assessment for these QE days. Late contributions received before
    then reduce the final shortfall to nil (s 18D). Left as None, the tool
    assumes no assessment has issued, which is the usual case for an
    employer checking their own records.

    `transition_allocation_confirmed` is deliberately false by default.
    LCR 2026/1 requires contributions made from 1 to 28 July 2026 to be
    applied first to any June-quarter shortfall, and permits a pre-1 July
    amount to carry forward only to the extent it was unused excess. This
    file format has neither balance, so a contribution dated no later than
    28 July cannot safely be assigned to a new-regime payday without an
    operator reconciling it first."""
    # Collect every date problem before stopping, so the operator can fix
    # the whole file in one pass rather than one row per run.
    problems = [p for p in (_date_problem(line) for line in lines) if p]
    if problems:
        raise ValueError("; ".join(problems))

    _flag_duplicates(lines)

    # Report every pre-regime row at once, not one per run.
    pre_regime = [line for line in lines if line.qe_day < REGIME_START]
    if pre_regime:
        rows = ", ".join(str(line.row) for line in pre_regime[:10])
        more = f" and {len(pre_regime) - 10} more" if len(pre_regime) > 10 else ""
        raise PreRegimeError(
            f"{len(pre_regime)} row(s) have a QE day before 1 Jul 2026 (rows {rows}"
            f"{more}; earliest {min(l.qe_day for l in pre_regime).isoformat()}): the old "
            "quarterly SG law applies to them and this tool covers payday super only. "
            "Remove them and run again."
        )

    # Prefer the fund-receipt date because that is the contribution fact the
    # checker ultimately tests. Where it is absent, a remittance on or before
    # 28 July could still have reached the fund in the overlap period, so it
    # is included rather than guessed away. Rows with no payment fact, nil SG
    # and defined-benefit interests do not allocate a contribution here.
    transition_rows: list[ContribLine] = []
    for line in lines:
        contribution_date = line.received if line.received is not None else line.remitted
        if (
            not line.db_interest
            and line.sg_amount > 0
            and contribution_date is not None
            and contribution_date <= TRANSITION_END
        ):
            transition_rows.append(line)
    if transition_rows and not transition_allocation_confirmed:
        rows = ", ".join(str(line.row) for line in transition_rows[:10])
        more = f" and {len(transition_rows) - 10} more" if len(transition_rows) > 10 else ""
        raise ValueError(
            f"{len(transition_rows)} row(s) use a contribution dated no later than "
            f"28 Jul 2026 (rows {rows}{more}). LCR 2026/1 requires pre-1 July "
            "amounts to be unused excess and 1-28 July amounts to reduce any "
            "employee June-quarter shortfall first. This file cannot calculate "
            "those old-regime balances. Reconcile them for every affected employee, "
            "then rerun with --confirm-transition-allocation; no payroll payment, "
            "lodgment or accounting decision is made by this tool"
        )
    transition_row_ids = {id(line) for line in transition_rows}

    pairs = [(line, compute_due(line, cal)) for line in lines]
    apply_item4(pairs, as_at)
    annotate_missing_flag(pairs)
    annotate_calendar_risk(pairs, cal)

    results: list[Result] = []
    for line, dl in pairs:
        result = Result(line, dl, UNKNOWN, notes=list(dl.notes), caveats=list(dl.caveats))
        if id(line) in transition_row_ids:
            result.notes.append(
                "operator confirmed the LCR 2026/1 transition allocation: any "
                "pre-1 July amount is unused excess and any 1-28 July amount remains "
                "after the employee's June-quarter shortfall"
            )
        if line.duplicate_note:
            result.caveats.append(line.duplicate_note)
        if dl.pathway == SKIP_DB or dl.due is None:
            result.verdict = SKIPPED
            results.append(result)
            continue

        # A row carrying no SG has no exposure behind any verdict, so the
        # amount is tested once here rather than bolted onto one branch of
        # the ladder. Bolted to the UNPAID branch alone, a 0.00 row with a
        # late remittance or receipt date still came out LATE and still
        # forced exit code 2.
        if line.sg_amount <= 0:
            if dl.due < as_at:
                result.caveats.append(
                    f"the deadline passed on {dl.due.isoformat()}, but this row records "
                    "no SG amount, so there is nothing to assess. Check the amount "
                    "column if this payday should have carried super"
                )
            else:
                result.caveats.append(
                    "this row records no SG amount, so there is nothing to assess. "
                    "Check the amount column if this payday should have carried super"
                )
            results.append(result)
            continue

        # An as-at report must not use a future remittance or receipt to settle
        # a historical shortfall. Keeping that future fact in the calculation
        # made the report say a contribution was already offset on a date when
        # the fund had not received it yet.
        settled = line.received if line.received is not None and line.received <= as_at else None
        remitted = line.remitted if line.remitted is not None and line.remitted <= as_at else None
        if line.received is not None and line.received > as_at:
            result.caveats.append(
                f"fund receipt date {line.received.isoformat()} is after the as-at date "
                f"{as_at.isoformat()}: it is ignored for this as-at report"
            )
        if line.remitted is not None and line.remitted > as_at:
            result.caveats.append(
                f"remittance date {line.remitted.isoformat()} is after the as-at date "
                f"{as_at.isoformat()}: it is ignored for this as-at report"
            )
        if settled is None and remitted is not None:
            if line.received is not None:
                # A receipt date exists but post-dates the as-at date, so
                # NO_RECEIPT_CAVEAT would be false on this row. The variant
                # keeps the constant meaning exactly what the console's
                # at-risk filter assumes it means.
                result.caveats.append(
                    "the only fund-receipt date on record "
                    f"({line.received.isoformat()}) is after the as-at date, so as at "
                    f"{as_at.isoformat()} the statutory test of receipt by the fund "
                    "(SGAA s 18C(1)) is not met and a remittance date alone cannot "
                    "show the contribution was on time"
                )
            else:
                result.caveats.append(NO_RECEIPT_CAVEAT)

        # Past the calendar's coverage the holiday table is empty, so every
        # weekday counts as a business day and the deadline computed here can
        # only be too EARLY. That asymmetry decides which verdicts survive.
        #
        # A date on or before the computed deadline is on time under every
        # possible holiday set, because a missing holiday can only push the
        # real deadline later, never earlier. Those verdicts are provable and
        # are given. Only a date after the computed deadline is indeterminable:
        # it is late on this calendar and could be on time on the real one.
        #
        # A pre-payment verdict is not affected either: it compares the receipt
        # with the QE day and a 12-month calendar window, never the deadline.
        past_horizon = dl.due > cal.coverage_until
        horizon_unknown = (
            "the date recorded here is after that deadline, and a holiday the "
            "calendar does not hold could move the deadline past it, so the line is "
            "left unassessed rather than called late. Supply the missing holidays "
            "with --holidays-override and set its \"verified_until\" to the last date "
            "you entered them for, or extend paydaysuper/data/business_days.json, "
            "to assess it"
        )
        horizon_figures = (
            f"the deadline {dl.due.isoformat()} runs past the calendar's coverage "
            f"({cal.coverage_until.isoformat()}) and can only move later, so days late "
            "is left blank and the notional earnings and SG charge figures on this "
            "line are a maximum, not a settled amount"
        )
        possible_item4_due = dl.possible_item4_due
        item4_uncertain = (
            possible_item4_due is not None and possible_item4_due > dl.due
        )
        item4_unknown = (
            "an earlier positive row could extend this deadline to "
            f"{possible_item4_due.isoformat()} under s 18C(2) item 4, but the "
            "file does not evidence an eligible contribution received by the fund, "
            "applied to that earlier QE day and on time. The deadline shown is the "
            "latest one proved by the supplied facts; reconcile the fund receipt and "
            "statutory allocation before deciding between the candidate verdicts"
            if item4_uncertain
            else ""
        )

        stale_prepayment = False
        if settled is not None:
            if settled < line.qe_day:
                # Pre-payments count only inside the 12-month window ending
                # the day before the QE day (s 18C(1)(c)(ii)).
                earliest = twelve_months_before(
                    line.qe_day - timedelta(days=1)
                ) + timedelta(days=1)
                if settled >= earliest:
                    result.verdict = ON_TIME
                    result.notes.append(
                        "received before the QE day: counted as an on-time pre-payment "
                        "under s 18C(1)(c)(ii)"
                    )
                else:
                    stale_prepayment = True
                    result.caveats.append(
                        f"received {settled.isoformat()}, before the 12-month pre-payment "
                        "window in s 18C(1)(c)(ii), so it cannot be applied to this payday. "
                        "The payday is treated as unfunded"
                    )
                    if dl.due >= as_at:
                        # Unfunded, but not yet due. Same treatment as a payday
                        # with nothing recorded against it at all: a deadline
                        # that has not arrived cannot have been missed, so there
                        # is no shortfall, no SG charge and nothing to flag.
                        result.caveats.append(
                            "the deadline has not passed, so there is nothing to assess "
                            "on this payday yet"
                        )
                        results.append(result)
                        continue
                    if (
                        past_horizon
                        or (
                            item4_uncertain
                            and possible_item4_due is not None
                            and as_at <= possible_item4_due
                        )
                    ):
                        result.verdict = UNKNOWN
                        result.horizon_verdicts = (LATE, "NOT_YET_DUE")
                        if past_horizon:
                            result.caveats.append(
                                "the payday is unfunded, but the deadline runs past the "
                                "calendar's coverage and may not have passed. No exposure "
                                "is calculated until the missing whole-of-jurisdiction "
                                "holiday facts are supplied"
                            )
                        if item4_uncertain:
                            result.caveats.append(item4_unknown)
                        results.append(result)
                        continue
                    result.verdict = LATE
            elif (
                item4_uncertain
                and possible_item4_due is not None
                and dl.due < settled <= possible_item4_due
            ):
                result.verdict = UNKNOWN
                result.horizon_verdicts = (LATE, ON_TIME)
                result.caveats.append(item4_unknown)
                results.append(result)
                continue
            elif past_horizon and settled > dl.due:
                result.verdict = UNKNOWN
                result.horizon_verdicts = (LATE, ON_TIME)
                result.caveats.append(horizon_unknown)
                results.append(result)
                continue
            else:
                result.verdict = ON_TIME if settled <= dl.due else LATE
        elif remitted is not None:
            if (
                item4_uncertain
                and possible_item4_due is not None
                and dl.due < remitted <= possible_item4_due
            ):
                result.verdict = UNKNOWN
                result.horizon_verdicts = (LATE, AT_RISK)
                result.caveats.append(item4_unknown)
                results.append(result)
                continue
            if past_horizon and remitted > dl.due:
                result.verdict = UNKNOWN
                result.horizon_verdicts = (LATE, AT_RISK)
                result.caveats.append(horizon_unknown)
                results.append(result)
                continue
            result.verdict = AT_RISK if remitted <= dl.due else LATE
        elif dl.due < as_at:
            # Nothing recorded and the supported deadline has passed. This is
            # the largest exposure the tool can see, so it must not be silent.
            # Past the calendar horizon, or while a possible item 4 deadline
            # has not passed, the tool cannot establish that an unfunded row
            # is due yet. Those rows remain attention-driving UNKNOWN with no
            # exposure until the missing deadline facts are reconciled.
            if (
                past_horizon
                or (
                    item4_uncertain
                    and possible_item4_due is not None
                    and as_at <= possible_item4_due
                )
            ):
                result.verdict = UNKNOWN
                result.horizon_verdicts = (UNPAID, "NOT_YET_DUE")
                if past_horizon:
                    result.caveats.append(
                        "no fund receipt is established for this payday, but the "
                        f"deadline shown ({dl.due.isoformat()}) runs past the calendar's "
                        "coverage and may not have passed. The row is left unassessed "
                        "with no exposure until the missing whole-of-jurisdiction "
                        "holiday facts are supplied"
                    )
                if item4_uncertain:
                    result.caveats.append(item4_unknown)
                results.append(result)
                continue
            result.verdict = UNPAID
            # A date may exist and simply post-date the as-at filter, in which
            # case saying none is recorded contradicts the caveat added above
            # and sends the reader to fix an export that is already correct.
            # The AT_RISK branch already varies its wording this way.
            _ignored = sorted(
                d for d in (line.remitted, line.received)
                if d is not None and d > as_at
            )
            _none_recorded = (
                "no remittance or fund-receipt date is recorded"
                if not _ignored
                else "the only remittance or fund-receipt date on record ("
                + ", ".join(d.isoformat() for d in _ignored)
                + ") is after the as-at date and is ignored here"
            )
            if past_horizon:
                result.caveats.append(
                    f"{_none_recorded}, and the deadline "
                    f"shown ({dl.due.isoformat()}) runs past the calendar's coverage, so "
                    "it may fall later than shown and may not have passed yet. Figures "
                    "assume the contribution is still unpaid; if your export has no date "
                    "columns, supply them before relying on this"
                )
            else:
                result.caveats.append(
                    f"the deadline passed on {dl.due.isoformat()} and {_none_recorded}. "
                    "Figures assume the contribution is "
                    "still unpaid; if your export has no date columns, supply them "
                    "before relying on this"
                )
        else:
            _ignored = sorted(
                d for d in (line.remitted, line.received)
                if d is not None and d > as_at
            )
            result.caveats.append(
                ("no remittance or fund-receipt date supplied"
                 if not _ignored
                 else "the only remittance or fund-receipt date on record ("
                      + ", ".join(d.isoformat() for d in _ignored)
                      + ") is after the as-at date and is ignored here")
                + ", and the deadline has not passed: nothing to assess yet"
            )
            results.append(result)
            continue

        if result.verdict in EXPOSED:
            base_shortfall = line.sg_amount
            landed = settled if settled is not None else remitted

            # Notional earnings compound on the base shortfall until the fund
            # receives money that counts for this payday (s 19A). Where none
            # has, they run to the as-at date, and they stop the day before an
            # assessment, after which GIC on the assessment takes over.
            if settled is not None and not stale_prepayment:
                nec_end = settled
                result.lateness_basis = "fund receipt"
            elif landed is not None and not stale_prepayment:
                nec_end = as_at
                result.lateness_basis = "as-at date (no fund receipt recorded)"
                result.notes.append(
                    "treated as still unpaid at the as-at date: notional earnings keep "
                    "accruing until the fund receives the contribution"
                )
            else:
                nec_end = as_at
                result.lateness_basis = "as-at date (nothing applied to this payday)"

            outstanding_to = nec_end
            if assessment_date is not None and nec_end >= assessment_date:
                nec_end = assessment_date - timedelta(days=1)
                result.caveats.append(
                    f"notional earnings stop {nec_end.isoformat()}, the day before the "
                    "assessment. Interest on the unpaid charge after that is general "
                    "interest charge, which this tool does not estimate"
                )

            # A row still exposed past the calendar's coverage got there
            # without comparing a date against the deadline (an unpaid payday,
            # or a receipt outside the 12-month pre-payment window), so the
            # verdict holds. The arithmetic hanging off the deadline does not:
            # printing a whole number of days late from a date the row's own
            # caveat says cannot be pinned down states more than is known.
            result.days_late = (
                None if past_horizon else max((outstanding_to - dl.due).days, 0)
            )
            if past_horizon:
                result.caveats.append(horizon_figures)
            result.nec = (
                notional_earnings(base_shortfall, dl.due, nec_end, gic)
                if nec_end > dl.due
                else Decimal("0")
            )

            # s 18D: a late contribution received in the late period, before
            # the ATO assesses the charge, reduces the final shortfall. A
            # payment made before the deadline is not a late-period payment,
            # so a stale pre-payment cannot offset anything.
            offset = (
                settled is not None
                and settled > dl.due
                and (assessment_date is None or settled < assessment_date)
            )
            if offset:
                result.final_shortfall = Decimal("0")
                assumption = (
                    f"before the assessment on {assessment_date.isoformat()}"
                    if assessment_date is not None
                    else "and no SG charge assessment had issued for this payday by then"
                )
                result.notes.append(
                    f"contribution received {settled.isoformat()} {assumption}: the final "
                    "shortfall is nil under s 18D, leaving notional earnings and uplift"
                )
            else:
                result.final_shortfall = base_shortfall

            result.offset_s18d = offset
            result.base_shortfall = base_shortfall
            result.uplift = uplift_scenarios(result.final_shortfall, result.nec)
            result.sgc_low, result.sgc_high = exposure_range(
                result.final_shortfall, result.nec
            )

            # A missed new-starter flag is the most likely reason a line is
            # wrongly late, and the operator cannot tell which rows to check.
            if (
                dl.pathway == USUAL_7BD
                and landed is not None
                and not stale_prepayment
                and landed >= line.qe_day
            ):
                extended = cal.add_business_days(line.qe_day, 20)
                if landed <= extended:
                    becomes = (
                        "the line becomes on time"
                        if settled is not None
                        else "the line stops being late, though it stays at risk until "
                        "you supply a fund-receipt date"
                    )
                    result.caveats.append(
                        "this assumes the contribution is not the first to this fund. If "
                        "it is a new starter or a fund switch, set "
                        f"first_contribution_to_fund=yes and {becomes} "
                        f"(due {extended.isoformat()})"
                    )

            stale = gic.staleness(nec_end)
            if stale:
                result.caveats.append(stale)

        results.append(result)

    return results


def horizon_indeterminate(results: list[Result]) -> list[Result]:
    """Rows whose verdict could not be decided from the supplied deadline facts.

    This includes calendar-horizon gaps and an unevidenced item 4 extension.
    These drive the same non-zero exit code LATE does. A run that cannot tell
    whether a 9,000 shortfall exists has not found nothing."""
    return [r for r in results if r.horizon_verdicts is not None]


def needs_attention(results: list[Result]) -> bool:
    """True where the run must not exit 0: real exposure, or a line the
    supplied deadline facts could not decide."""
    return any(r.verdict in EXPOSED for r in results) or bool(
        horizon_indeterminate(results)
    )


CSV_HEADER = [
    "row",
    "employee_id",
    "qe_day",
    "pathway",
    "due_date",
    "verdict",
    "days_late",
    "lateness_measured_to",
    "sg_amount",
    "final_shortfall",
    "notional_earnings",
    "uplift_best_case",
    "uplift_worst_case",
    "sgc_estimate_low",
    "sgc_estimate_high",
    "caveats",
    "notes",
    # Appended, never inserted: a positional consumer keeps its column
    # numbers. Blank on every row except the ones the calendar cannot settle,
    # where it holds the two candidate verdicts as "WORSE or BETTER". Without
    # it the CSV wrote UNKNOWN for a 9,000 contribution nobody can assess and
    # UNKNOWN for a nil row with nothing to assess, with the same blank
    # shortfall on both, so anyone reading the file rather than the console or
    # the exit code could not tell real exposure from nothing at all.
    "unassessable_between",
]


def _rounded_figures(r: Result) -> dict[str, Decimal | None]:
    """Round each component once, then build the totals from the rounded
    parts so the columns of a row always add up."""
    if r.uplift is None:
        return {k: None for k in ("shortfall", "nec", "up_low", "up_high", "low", "high")}
    shortfall = cents(r.final_shortfall)
    nec = cents(r.nec)
    up_low = cents(r.uplift["clean_history"]["vds_within_30d"])
    up_high = cents(r.uplift["prior_history"]["no_vds"])
    return {
        "shortfall": shortfall,
        "nec": nec,
        "up_low": up_low,
        "up_high": up_high,
        "low": shortfall + nec + up_low,
        "high": shortfall + nec + up_high,
    }


def write_csv(
    results: list[Result],
    path: str | Path,
    as_at: date,
    law_date: str,
    assessment_date: date | None = None,
    source: str | Path | None = None,
    gic_provenance: str = "",
) -> None:
    # utf-8-sig, not utf-8: Excel on a cp1252 Windows box reads a BOM-less
    # CSV in the locale code page, so a non-ASCII employee id comes out
    # mojibake and stops joining back to the payroll export. parse_rows
    # already reads with utf-8-sig, so a report fed back in still parses.
    with atomic_text_output(path, encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for r in results:
            figures = _rounded_figures(r)
            writer.writerow(
                [
                    r.line.row,
                    csv_safe(r.line.employee_id),
                    r.line.qe_day.isoformat(),
                    r.deadline.pathway,
                    r.deadline.due.isoformat() if r.deadline.due else "",
                    r.verdict,
                    "" if r.days_late is None else r.days_late,
                    r.lateness_basis,
                    money(r.line.sg_amount),
                    money(figures["shortfall"]),
                    money(figures["nec"]),
                    money(figures["up_low"]),
                    money(figures["up_high"]),
                    money(figures["low"]),
                    money(figures["high"]),
                    " | ".join(r.caveats),
                    " | ".join(r.notes),
                    " or ".join(r.horizon_verdicts) if r.horizon_verdicts else "",
                ]
            )

        # Trailing note, full width so the file stays a clean table: a
        # one-field title row makes Power Query infer the wrong column count.
        note = [""] * len(CSV_HEADER)
        note[1] = "NOTE"
        assessment_text = (
            f"Assessment date {assessment_date.isoformat()}. "
            if assessment_date is not None
            else "No assessment date given, so contributions received late are assumed "
            "to have reached the fund before any assessment. "
        )
        # By name, not by position: the trailing note belongs in "notes", and
        # note[-1] silently moved it into whatever column was appended last.
        note[CSV_HEADER.index("notes")] = (
            f"payday-super-checker {__version__}"
            + (f", source {source}" if source else "")
            + f", as at {as_at.isoformat()}. {assessment_text}"
            + (f"{gic_provenance}. " if gic_provenance else "")
            + f"Legal content current at {law_date}. EXPERIMENTAL ESTIMATES: monetary "
            "components are displayed to cents with ROUND_HALF_UP, while TAA 1953 "
            "s 16B only rounds the Commissioner's final assessed SG charge down to "
            "the nearest 5 cents. The low estimate assumes a "
            "voluntary disclosure lodged within 30 days of the payday and a clean "
            "24-month history; the high estimate assumes neither. Estimates exclude "
            "choice loading, the maximum contributions base and post-assessment "
            "penalties. Educational tool, not advice: the ATO assesses the charge."
        )
        writer.writerow(note)


def console_summary(
    results: list[Result],
    as_at: date,
    csv_path: str | Path,
    law_date: str,
    rates: dict,
    assessment_date: date | None = None,
) -> str:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1

    lines = [
        f"payday-super-checker: {len(results)} contribution lines, as at {as_at.isoformat()}",
        "",
        "  " + "  ".join(f"{v}: {counts.get(v, 0)}" for v in VERDICTS),
        "",
    ]

    exposed = [r for r in results if r.verdict in EXPOSED]
    if exposed:
        exposed.sort(key=lambda r: r.sgc_high or Decimal(0), reverse=True)
        lines.append("Lines with exposure (experimental estimates, largest first):")
        for r in exposed[:10]:
            figures = _rounded_figures(r)
            # Standard output is commonly retained by task runners and CI logs.
            # The report CSV is the private, row-level artifact; retain the source
            # row here so an operator can locate the result without leaking an
            # employee identifier into those logs. Days late is left unset where
            # the deadline runs past the calendar's coverage, so never print
            # "None days late" in that case.
            lateness = (
                f"{r.days_late} days late to {r.lateness_basis}"
                if r.days_late is not None
                else f"days late not pinned down, measured to {r.lateness_basis}"
            )
            lines.append(
                f"  row {r.line.row}  QE day {r.line.qe_day.isoformat()}"
                f"  due {r.deadline.due.isoformat()}  {r.verdict}, {lateness}"
            )
            shortfall_text = (
                f"super ${money(r.line.sg_amount)} (received, so the shortfall is nil)"
                if r.offset_s18d
                else f"shortfall ${money(figures['shortfall'])}"
            )
            at_most = "" if r.days_late is not None else "at most "
            lines.append(
                f"      {shortfall_text}  notional earnings {at_most}"
                f"${money(figures['nec'])}  experimental SG charge estimate {at_most}"
                f"${money(figures['low'])} - ${money(figures['high'])}"
            )
            for caveat in r.caveats:
                lines.append(f"      note: {caveat}")
        if len(exposed) > 10:
            lines.append(f"  ... and {len(exposed) - 10} more (see {csv_path})")

        total_shortfall = sum((_rounded_figures(r)["shortfall"] for r in exposed), Decimal("0"))
        total_nec = sum((_rounded_figures(r)["nec"] for r in exposed), Decimal("0"))
        total_low = sum((_rounded_figures(r)["low"] for r in exposed), Decimal("0"))
        total_high = sum((_rounded_figures(r)["high"] for r in exposed), Decimal("0"))
        lines += [
            "",
            f"  Total across {len(exposed)} line(s): shortfall ${money(total_shortfall)}, "
            f"notional earnings ${money(total_nec)},",
            f"  experimental estimated SG charge ${money(total_low)} - "
            f"${money(total_high)}.",
            "",
        ]

    at_risk = [r for r in results if r.verdict == AT_RISK]
    if at_risk:
        lines.append(
            f"{len(at_risk)} line(s) remitted by the deadline but with no fund-receipt "
            "date. The statutory timing test turns on receipt by the fund, not the "
            "day you paid, and clearing-house transit time is the employer's risk."
        )
        # An at-risk line is in neither the exposure listing nor the unflagged
        # count, so without this its caveats never reached the console at all
        # -- including the one saying two rows are identical and the payday is
        # counted twice, which is the data-quality warning most worth reading.
        #
        # The no-fund-receipt caveat is excluded because EVERY at-risk row
        # carries it and the header above already says it. Listed, it filled
        # the ten-row cap with rows whose only note repeated the header, and
        # truncated away the rows that had something of their own to say.
        flagged = [
            (r, [c for c in r.caveats if c != NO_RECEIPT_CAVEAT]) for r in at_risk
        ]
        flagged = [(r, others) for r, others in flagged if others]
        for r, others in flagged[:10]:
            lines.append(
                f"  row {r.line.row}  QE day {r.line.qe_day.isoformat()}  "
                f"due {r.deadline.due.isoformat()}"
            )
            for caveat in others:
                lines.append(f"      note: {caveat}")
        if len(flagged) > 10:
            lines.append(
                f"  ... and {len(flagged) - 10} more at-risk line(s) with notes "
                f"(see {csv_path})"
            )
        lines.append("")

    # A row left UNKNOWN because a material deadline fact is unresolved is
    # not a data-quality footnote. It may carry the whole shortfall, so it is
    # listed explicitly and drives a non-zero exit.
    indeterminate = horizon_indeterminate(results)
    if indeterminate:
        lines.append(
            f"{len(indeterminate)} line(s) cannot be assessed from the supplied "
            "deadline facts. Each one is between the two verdicts below and needs "
            "reconciliation before it can be treated as clear."
        )
        for r in indeterminate[:10]:
            worse, better = r.horizon_verdicts
            lines.append(
                f"  row {r.line.row}  QE day {r.line.qe_day.isoformat()}  "
                f"due {r.deadline.due.isoformat()}"
                f"  super ${money(r.line.sg_amount)}  {worse} or {better}"
            )
            for caveat in r.caveats:
                lines.append(f"      note: {caveat}")
        if len(indeterminate) > 10:
            lines.append(
                f"  ... and {len(indeterminate) - 10} more unassessable line(s) "
                f"(see {csv_path})"
            )
        lines.append("")

    unflagged = [
        r
        for r in results
        if r.verdict not in EXPOSED
        and r.verdict != AT_RISK
        and r.horizon_verdicts is None
        and r.caveats
    ]
    if unflagged:
        lines.append(
            f"{len(unflagged)} other line(s) carry data-quality notes; see the caveats "
            f"column in {csv_path}."
        )
        lines.append("")

    fy = rates.get("financial_years", {})
    qe_days = [r.line.qe_day for r in results]
    fy_labels = sorted({financial_year(d) for d in qe_days}) if qe_days else []
    fy_label = fy_labels[0] if fy_labels else financial_year(as_at)
    entry = fy.get(fy_label)
    mcb = (entry or {}).get("max_contributions_base")
    try:
        mcb_text = f"${int(mcb):,} for {fy_label}"
    except (TypeError, ValueError):
        mcb_text = "the annual cap"
    if len(fy_labels) > 1:
        mcb_text += f" (this file spans {', '.join(fy_labels)})"

    assessment_line = (
        f"  - Assessment date {assessment_date.isoformat()}: only contributions received "
        "before it clear the shortfall, and notional earnings stop the day before."
        if assessment_date is not None
        else "  - No assessment date given, so a late contribution that reached the fund "
        "is assumed to have done so before any assessment (s 18D)."
    )

    lines += [
        "Assumptions and limits:",
        f"  - Legal content current at {law_date}. LCR 2026/1, LCR 2026/2 and "
        "LCR 2026/3 were issued on 5 Aug 2026. LCR 2026/D1 remains a draft "
        "pending the appeal from Department of Education v Commissioner of "
        "Taxation [2026] FCA 898.",
        "  - The amount column must be the operator-determined super guarantee amount "
        "after applying the employee/payment boundaries in regulations 11 and 12, "
        "qualifying earnings and other applicable limits. Salary sacrifice and "
        "additional contributions must be filtered out. This tool does not make those "
        "classifications; LCR 2026/D1 also remains draft.",
        "  - Deadlines use the national business-day calendar in SGAA s 6(1): "
        "weekends plus holidays applying to the whole of any State, the ACT or the NT.",
        assessment_line,
        "  - Deadline alignment under s 18C(2) item 4 is applied only where an "
        "earlier row evidences an eligible contribution received by the fund, "
        "allocated to that QE day and on time. Include each employee's earlier "
        "paydays and reconcile the statutory allocation before treating an item 4 "
        "extension as settled.",
        "  - The low estimate assumes a voluntary disclosure lodged within 30 days of "
        "the payday and a clean 24-month history; the high estimate assumes neither. "
        "Choice loading, the late payment penalty and interest on an unpaid assessment "
        "are not included. The ATO assesses the charge.",
        "  - Exposure figures are EXPERIMENTAL ESTIMATES. This tool displays each "
        "component to cents with ROUND_HALF_UP so report columns add up. LCR 2026/3 "
        "confirms only that TAA 1953 s 16B reduces the Commissioner's final assessed "
        "SG charge to the nearest 5 cents; it does not authorise per-line cents "
        "rounding here.",
        f"  - Maximum contributions base ({mcb_text}, annual per employer) is "
        "not applied: it needs each employee's cumulative earnings for the year. "
        "High earners may show a larger shortfall here than the law requires.",
        "  - PCG 2026/1 sets the ATO's compliance approach for QE days to 30 Jun 2027. "
        "Fixing a late contribution promptly lowers ATO review risk; it does not "
        "remove the liability.",
        "  - This tool tests the SG charge only. Fund deeds, enterprise agreements and "
        "awards can require earlier payment.",
        "",
        f"Full detail written to {csv_path}",
        "",
        "Educational tool, not advice. Check anything material against the ATO's own "
        "guidance and calculators.",
    ]
    return "\n".join(lines)
