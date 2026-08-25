"""Per-line payday-super verdicts and exposure figures.

Extracted from report.py so the file-level assess() path and the CSV/console
renderers stay readable. Public names are re-exported from report.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from .calendar import BusinessCalendar
from .csv_io import cents, money, remitted_credit
from .deadlines import (
    SKIP_DB,
    USUAL_7BD,
    ContribLine,
    Deadline,
    earliest_prepayment_day,
    receipt_amount_cap,
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

# CENTS, FORMULA_LEAD, money, cents and csv_safe live in csv_io and are
# re-exported here unchanged, so report.money and friends keep working for
# every existing importer.

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
    # contribution could trigger item 4. Holds the conservative outer
    # verdicts, attention-driving outcome first; a caveat may retain an
    # intermediate third outcome for a partial receipt. The historical
    # attribute name is retained for report-CSV and API compatibility.
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


def _received_credit(line: ContribLine, received_as_at: date | None) -> Decimal:
    """Amount tied to an evidenced fund receipt on this as-at date.

    ``matched_amount`` preserves the contribution amount associated by an
    importer even where no vendor date exists. A ten-column partial row falls
    back to ``remitted_amount``; a legacy row with neither appended amount
    continues to mean the whole SG amount. Eligibility and timing are applied
    separately when base and final shortfalls are calculated.
    """
    if received_as_at is None:
        return Decimal("0")
    owed = cents(line.sg_amount)
    return min(cents(receipt_amount_cap(line)), owed)


def _amount_problem(line: ContribLine) -> str | None:
    """Apply the canonical amount invariants before item 4 can consume a row."""
    if line.sg_amount < 0:
        return f"row {line.row}: sg_amount cannot be negative"
    if line.remitted_amount is not None:
        if line.remitted_amount < 0 or line.remitted_amount > line.sg_amount:
            return (
                f"row {line.row}: remitted_amount must be between zero and "
                "sg_amount"
            )
        if line.remitted is None:
            return f"row {line.row}: remitted_amount requires remitted_date"
    if line.matched_amount is not None:
        if line.matched_amount < 0 or line.matched_amount > line.sg_amount:
            return (
                f"row {line.row}: matched_amount must be between zero and "
                "sg_amount"
            )
        if (
            line.remitted_amount is not None
            and line.remitted_amount > line.matched_amount
        ):
            return (
                f"row {line.row}: remitted_amount cannot exceed matched_amount"
            )
        if (
            line.matched_amount < line.sg_amount
            and line.remitted is not None
            and line.remitted_amount is None
        ):
            return (
                f"row {line.row}: matched_amount below sg_amount requires "
                "remitted_amount when remitted_date is present"
            )
    return None


def _flag_duplicates(lines: list[ContribLine]) -> None:
    """Two identical rows are double-counted, and a re-exported pay run is a
    common way to get them. They can also be legitimate (one payday split
    across two funds), so this warns rather than refuses."""
    groups: dict[tuple, list[ContribLine]] = {}
    for line in lines:
        # The appended amount columns preserve nine- and ten-column files:
        # a dated legacy row with no explicit remitted amount means the whole
        # SG amount was remitted, while a blank matched amount falls back to
        # that dated subtotal and then to the whole legacy liability. Normalise
        # those representations before grouping so mixing old and new
        # canonical exports cannot hide a doubled row.
        effective_remitted_amount = (
            remitted_credit(line, line.remitted)
            if line.remitted is not None
            else None
        )
        effective_matched_amount = cents(receipt_amount_cap(line))
        key = (
            line.employee_id,
            line.qe_day,
            line.sg_amount,
            line.remitted,
            effective_remitted_amount,
            effective_matched_amount,
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


def _assess_line(
    line: ContribLine,
    dl: Deadline,
    cal: BusinessCalendar,
    gic: GicTable,
    as_at: date,
    assessment_date: date | None,
    transition_row_ids: set[int],
) -> Result:
    """Verdict, caveats and exposure figures for one contribution line.

    Runs after compute_due, apply_item4 and the annotate_* passes have
    settled the line's deadline, so everything here reads `dl` as final.
    The file-level checks (date problems, duplicate flagging, pre-regime
    rows, the transition gate) stay in assess: they are about the whole
    file, not any one line."""
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
        return result

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
        return result

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

    credit = remitted_credit(line, remitted)
    operational_unremitted = cents(line.sg_amount) - credit
    if operational_unremitted < 0:
        operational_unremitted = Decimal("0")
    fully_remitted = operational_unremitted == 0
    receipt_credit = _received_credit(line, settled)
    receipt_covers_all = receipt_credit >= cents(line.sg_amount)
    if credit > 0 and operational_unremitted > 0:
        result.notes.append(
            f"part-paid: ${money(credit)} of ${money(line.sg_amount)} is evidenced "
            f"as remitted, leaving ${money(operational_unremitted)} unremitted. "
            "Remittance does not establish statutory credit until the fund receipt "
            "and its timing are evidenced"
        )

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
    if item4_uncertain:
        assert possible_item4_due is not None
        item4_unknown = (
            "an earlier positive row could extend this deadline to "
            f"{possible_item4_due.isoformat()} under s 18C(2) item 4, but the "
            "file does not evidence an eligible contribution received by the fund, "
            "applied to that earlier QE day and on time. The deadline shown is the "
            "latest one proved by the supplied facts; reconcile the fund receipt and "
            "statutory allocation before deciding between the candidate verdicts"
        )
    else:
        item4_unknown = ""
    item4_partial_unknown = (
        "because the evidenced fund receipt covers only part of the SG amount, "
        "the unresolved item 4 deadline also leaves UNPAID possible: that is "
        "the outcome if the actual deadline falls on or after the receipt date "
        "but on or before the as-at date"
    )
    horizon_partial_unknown = (
        "because the evidenced fund receipt covers only part of the SG amount, "
        "a missing holiday also leaves UNPAID possible: that is the outcome if "
        "the actual deadline falls on or after the receipt date but on or before "
        "the as-at date"
    )

    stale_prepayment = False
    on_time_receipt_credit = Decimal("0")
    if settled is not None:
        if settled < line.qe_day:
            # Pre-payments count only inside the 12-month window ending
            # the day before the QE day (s 18C(1)(c)(ii)).
            earliest = earliest_prepayment_day(line.qe_day)
            if settled >= earliest:
                on_time_receipt_credit = receipt_credit
                result.notes.append(
                    f"${money(receipt_credit)} received before the QE day: counted "
                    "as an on-time pre-payment under s 18C(1)(c)(ii)"
                )
                if receipt_covers_all:
                    result.verdict = ON_TIME
                elif dl.due >= as_at:
                    result.caveats.append(
                        "the eligible pre-payment covers only part of the SG amount, "
                        "but the deadline has not passed, so there is nothing to "
                        "assess yet"
                    )
                    return result
                elif (
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
                            "the eligible pre-payment covers only part of the SG "
                            "amount, but the deadline runs past the calendar's "
                            "coverage and may not have passed. No exposure is "
                            "calculated until the missing holiday facts are supplied"
                        )
                    if item4_uncertain:
                        result.caveats.append(item4_unknown)
                    return result
                else:
                    result.verdict = UNPAID
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
                    return result
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
                    return result
                result.verdict = LATE
        elif (
            item4_uncertain
            and possible_item4_due is not None
            and dl.due < settled <= possible_item4_due
        ):
            result.verdict = UNKNOWN
            partial_better = (
                "NOT_YET_DUE" if as_at <= possible_item4_due else UNPAID
            )
            result.horizon_verdicts = (
                LATE,
                ON_TIME if receipt_covers_all else partial_better,
            )
            result.caveats.append(item4_unknown)
            if not receipt_covers_all:
                if partial_better == "NOT_YET_DUE":
                    result.caveats.append(item4_partial_unknown)
                else:
                    result.caveats.append(
                        "the possible item 4 deadline has now passed. Because "
                        "the evidenced fund receipt covers only part of the SG "
                        "amount, the later-deadline outcome is UNPAID rather than "
                        "NOT_YET_DUE"
                    )
            return result
        elif past_horizon and settled > dl.due:
            result.verdict = UNKNOWN
            result.horizon_verdicts = (
                LATE,
                ON_TIME if receipt_covers_all else "NOT_YET_DUE",
            )
            result.caveats.append(horizon_unknown)
            if not receipt_covers_all:
                result.caveats.append(horizon_partial_unknown)
            return result
        elif settled <= dl.due:
            on_time_receipt_credit = receipt_credit
            if receipt_covers_all:
                result.verdict = ON_TIME
            elif (
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
                        "the fund receipt covers only part of the SG amount, but "
                        "the deadline runs past the calendar's coverage and may "
                        "not have passed. No exposure is calculated until the "
                        "missing holiday facts are supplied"
                    )
                if item4_uncertain:
                    result.caveats.append(item4_unknown)
                return result
            elif dl.due < as_at:
                result.verdict = UNPAID
            else:
                result.caveats.append(
                    "the fund receipt covers only part of the SG amount, but the "
                    "deadline has not passed, so there is nothing to assess yet"
                )
                return result
        else:
            result.verdict = LATE
    elif remitted is not None and fully_remitted:
        if (
            item4_uncertain
            and possible_item4_due is not None
            and dl.due < remitted <= possible_item4_due
        ):
            result.verdict = UNKNOWN
            result.horizon_verdicts = (LATE, AT_RISK)
            result.caveats.append(item4_unknown)
            return result
        if past_horizon and remitted > dl.due:
            result.verdict = UNKNOWN
            result.horizon_verdicts = (LATE, AT_RISK)
            result.caveats.append(horizon_unknown)
            return result
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
            return result
        result.verdict = UNPAID
        # A date may exist and simply post-date the as-at filter, in which
        # case saying none is recorded contradicts the caveat added above
        # and sends the reader to fix an export that is already correct.
        # The AT_RISK branch already varies its wording this way.
        _ignored = sorted(
            d for d in (line.remitted, line.received)
            if d is not None and d > as_at
        )
        if credit > 0:
            _none_recorded = (
                f"${money(credit)} is evidenced as remitted, leaving "
                f"${money(operational_unremitted)} unremitted, and no "
                "fund-receipt date is recorded "
                "for the remainder"
            )
        elif not _ignored:
            _none_recorded = "no remittance or fund-receipt date is recorded"
        else:
            _none_recorded = (
                "the only remittance or fund-receipt date on record ("
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
        return result

    if result.verdict in EXPOSED:
        owed = cents(line.sg_amount)
        base_shortfall = max(owed - on_time_receipt_credit, Decimal("0"))
        landed = settled if settled is not None else remitted

        if on_time_receipt_credit > 0 and base_shortfall > 0:
            result.notes.append(
                f"an eligible on-time fund receipt of "
                f"${money(on_time_receipt_credit)} reduces the base shortfall to "
                f"${money(base_shortfall)}; the remaining amount is unfunded"
            )

        # s 18D reduces the final shortfall only by an eligible contribution
        # received during the late period and before assessment. A remittance
        # date is operational evidence only; it cannot reduce either statutory
        # shortfall without a fund receipt.
        offset_credit = Decimal("0")
        if (
            settled is not None
            and not stale_prepayment
            and settled > dl.due
            and (assessment_date is None or settled < assessment_date)
        ):
            offset_credit = min(receipt_credit, base_shortfall)
        final_shortfall = max(base_shortfall - offset_credit, Decimal("0"))
        offset = offset_credit > 0

        if offset:
            assert settled is not None
            assumption = (
                f"before the assessment on {assessment_date.isoformat()}"
                if assessment_date is not None
                else "and no SG charge assessment had issued for this payday by then"
            )
            if final_shortfall == 0:
                result.notes.append(
                    f"contribution received {settled.isoformat()} {assumption}: "
                    "the final shortfall is nil under s 18D, leaving notional "
                    "earnings and uplift"
                )
            else:
                result.notes.append(
                    f"contribution received {settled.isoformat()} {assumption}: "
                    f"s 18D reduces the final shortfall by "
                    f"${money(offset_credit)} to ${money(final_shortfall)}; it "
                    "does not clear the remaining shortfall"
                )

        # Section 19A compounds on the base shortfall for every late-period
        # day on which the final shortfall remains positive. A full eligible
        # late receipt ends that period; a part receipt does not. Assessment
        # still caps this estimate at the preceding day, after which GIC on
        # the assessed charge is outside this tool.
        if (
            settled is not None
            and not stale_prepayment
            and receipt_covers_all
        ):
            outstanding_to = settled
            result.lateness_basis = "fund receipt"
            nec_end = settled if final_shortfall == 0 else as_at
        elif settled is not None and not stale_prepayment:
            nec_end = as_at
            outstanding_to = as_at
            result.lateness_basis = "as-at date (shortfall remains after part receipt)"
            result.notes.append(
                "the fund received only part of the liability: notional earnings "
                "continue on the base shortfall while the final shortfall remains "
                "greater than nil"
            )
        elif landed is not None and not stale_prepayment:
            nec_end = as_at
            outstanding_to = as_at
            result.lateness_basis = "as-at date (no fund receipt recorded)"
            result.notes.append(
                "treated as still unpaid at the as-at date: notional earnings keep "
                "accruing until the fund receives the contribution"
            )
        else:
            nec_end = as_at
            outstanding_to = as_at
            result.lateness_basis = "as-at date (nothing applied to this payday)"

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

        result.offset_s18d = offset
        result.base_shortfall = base_shortfall
        result.final_shortfall = final_shortfall
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

    return result
