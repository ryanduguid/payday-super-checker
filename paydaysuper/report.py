"""Verdicts, exposure figures, console summary and report.csv."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from . import __version__
from .calendar import BusinessCalendar
from .deadlines import (
    REGIME_START,
    SKIP_DB,
    USUAL_7BD,
    ContribLine,
    Deadline,
    PreRegimeError,
    annotate_calendar_risk,
    apply_item4,
    compute_due,
)
from .rates import GicTable
from .sgc import exposure_range, notional_earnings, uplift_scenarios

ON_TIME = "ON_TIME"
LATE = "LATE"
AT_RISK = "AT_RISK"
UNPAID = "UNPAID"
UNKNOWN = "UNKNOWN"
SKIPPED = "SKIPPED"

VERDICTS = (ON_TIME, AT_RISK, LATE, UNPAID, UNKNOWN, SKIPPED)
EXPOSED = (LATE, UNPAID)

CENTS = Decimal("0.01")

# Characters Excel and Sheets treat as the start of a formula.
FORMULA_LEAD = ("=", "+", "-", "@")


def money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return str(value.quantize(CENTS, rounding=ROUND_HALF_UP))


def cents(value: Decimal | None) -> Decimal:
    return Decimal("0") if value is None else value.quantize(CENTS, rounding=ROUND_HALF_UP)


def csv_safe(text: str) -> str:
    """Stop a spreadsheet treating a cell as a formula. Only employee ids
    come from the input, so only they can carry a payload."""
    if text[:1] in FORMULA_LEAD:
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


def _item4_seeded_by_unrecorded(
    line: ContribLine, dl: Deadline, pairs: list[tuple[ContribLine, Deadline]]
) -> str | None:
    """Item 4 needs an EARLIER ELIGIBLE CONTRIBUTION. The tool cannot see
    whether one was made, so where every earlier line it could have inherited
    from records no payment at all, say so rather than quietly extending."""
    donors = [
        other
        for other, other_dl in pairs
        if other.employee_id == line.employee_id
        and other.qe_day < line.qe_day
        and other_dl.due == dl.due
    ]
    if donors and all(d.received is None and d.remitted is None for d in donors):
        earlier = ", ".join(sorted({d.qe_day.isoformat() for d in donors}))
        return (
            f"this deadline is inherited from the QE day {earlier}, for which no payment "
            "is recorded. s 18C(2) item 4 needs an earlier eligible contribution, so if "
            "none was made the deadline for this line is its own period end"
        )
    return None


def assess(
    lines: list[ContribLine],
    cal: BusinessCalendar,
    gic: GicTable,
    as_at: date,
    assessment_date: date | None = None,
) -> list[Result]:
    """Assess each contribution line.

    `assessment_date` is the day the ATO made (or is assumed to make) an SG
    charge assessment for these QE days. Late contributions received before
    then reduce the final shortfall to nil (s 18D). Left as None, the tool
    assumes no assessment has issued, which is the usual case for an
    employer checking their own records."""
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

    pairs = [(line, compute_due(line, cal)) for line in lines]
    apply_item4(pairs)
    annotate_calendar_risk(pairs, cal)

    results: list[Result] = []
    for line, dl in pairs:
        result = Result(line, dl, UNKNOWN, notes=list(dl.notes), caveats=list(dl.caveats))
        if line.duplicate_note:
            result.caveats.append(line.duplicate_note)
        inherited = _item4_seeded_by_unrecorded(line, dl, pairs)
        if inherited:
            result.caveats.append(inherited)

        if dl.pathway == SKIP_DB or dl.due is None:
            result.verdict = SKIPPED
            results.append(result)
            continue

        settled = line.received
        if settled is None and line.remitted is not None:
            result.caveats.append(
                "no fund-receipt date supplied: the statutory test is receipt by the "
                "fund (SGAA s 18C(1)), so a remittance date alone cannot show the "
                "contribution was on time"
            )

        stale_prepayment = False
        if settled is not None:
            if settled < line.qe_day:
                # Pre-payments count only inside the 12-month window ending
                # the day before the QE day (s 18C(1)(c)(ii)).
                earliest = twelve_months_before(line.qe_day - timedelta(days=1)) + timedelta(days=1)
                if settled >= earliest:
                    result.verdict = ON_TIME
                    result.notes.append(
                        "received before the QE day: counted as an on-time pre-payment "
                        "under s 18C(1)(c)(ii)"
                    )
                else:
                    result.verdict = LATE
                    stale_prepayment = True
                    result.caveats.append(
                        f"received {settled.isoformat()}, before the 12-month pre-payment "
                        "window in s 18C(1)(c)(ii), so it cannot be applied to this payday. "
                        "The payday is treated as unfunded"
                    )
            else:
                result.verdict = ON_TIME if settled <= dl.due else LATE
        elif line.remitted is not None:
            result.verdict = AT_RISK if line.remitted <= dl.due else LATE
        elif dl.due < as_at:
            # Nothing recorded and the deadline has passed. This is the
            # largest exposure the tool can see, so it must not be silent.
            result.verdict = UNPAID
            result.caveats.append(
                f"the deadline passed on {dl.due.isoformat()} and no remittance or "
                "fund-receipt date is recorded. Figures assume the contribution is still "
                "unpaid; if your export has no date columns, supply them before relying "
                "on this"
            )
        else:
            result.caveats.append(
                "no remittance or fund-receipt date supplied, and the deadline has not "
                "passed: nothing to assess yet"
            )
            results.append(result)
            continue

        if result.verdict in EXPOSED:
            base_shortfall = line.sg_amount
            landed = settled if settled is not None else line.remitted

            if settled is not None and settled > as_at:
                result.caveats.append(
                    f"fund receipt date {settled.isoformat()} is after the as-at date "
                    f"{as_at.isoformat()}: check it is not a typo, since notional "
                    "earnings run to the receipt date"
                )

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

            if assessment_date is not None and nec_end >= assessment_date:
                nec_end = assessment_date - timedelta(days=1)
                result.notes.append(
                    f"notional earnings stop {nec_end.isoformat()}, the day before the "
                    "assessment. Interest on the unpaid charge after that is general "
                    "interest charge, which this tool does not estimate"
                )

            result.days_late = max((nec_end - dl.due).days, 0)
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
            if dl.pathway == USUAL_7BD and landed is not None:
                extended = cal.add_business_days(line.qe_day, 20)
                if landed <= extended:
                    result.caveats.append(
                        "this assumes the contribution is not the first to this fund. If "
                        "it is a new starter or a fund switch, set "
                        f"first_contribution_to_fund=yes and the line becomes on time "
                        f"(due {extended.isoformat()})"
                    )

            stale = gic.staleness(nec_end)
            if stale:
                result.caveats.append(stale)

        results.append(result)

    return results


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
    with open(path, "w", newline="", encoding="utf-8") as f:
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
        note[-1] = (
            f"payday-super-checker {__version__}"
            + (f", source {source}" if source else "")
            + f", as at {as_at.isoformat()}. {assessment_text}"
            + (f"{gic_provenance}. " if gic_provenance else "")
            + f"Legal content current at {law_date}. The low estimate assumes a "
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
        lines.append("Lines with exposure (largest first):")
        for r in exposed[:10]:
            figures = _rounded_figures(r)
            lines.append(
                f"  row {r.line.row}  {r.line.employee_id}  QE day {r.line.qe_day.isoformat()}"
                f"  due {r.deadline.due.isoformat()}  {r.verdict}, {r.days_late} days late"
                f" to {r.lateness_basis}"
            )
            shortfall_text = (
                f"super ${money(r.line.sg_amount)} (received, so the shortfall is nil)"
                if r.offset_s18d
                else f"shortfall ${money(figures['shortfall'])}"
            )
            lines.append(
                f"      {shortfall_text}  notional earnings ${money(figures['nec'])}"
                f"  SG charge estimate ${money(figures['low'])} - ${money(figures['high'])}"
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
            f"  estimated SG charge ${money(total_low)} - ${money(total_high)}.",
            "",
        ]

    at_risk = [r for r in results if r.verdict == AT_RISK]
    if at_risk:
        lines.append(
            f"{len(at_risk)} line(s) remitted by the deadline but with no fund-receipt "
            "date. Compliance turns on receipt by the fund, not the day you paid, and "
            "clearing-house transit time is the employer's risk."
        )
        lines.append("")

    unflagged = [r for r in results if r.verdict not in EXPOSED and r.caveats]
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
        f"  - Legal content current at {law_date}; ATO law companion rulings "
        "LCR 2026/D1-D4 were still drafts at that date.",
        "  - The amount column must be super guarantee only. Salary sacrifice and "
        "additional contributions have a different base and must be filtered out first.",
        "  - Deadlines use the national business-day calendar in SGAA s 6(1): "
        "weekends plus holidays applying to the whole of any State, the ACT or the NT.",
        assessment_line,
        "  - Deadline alignment under s 18C(2) item 4 is tested only against rows in "
        "this file, so include each employee's earlier paydays back through any "
        "20-business-day window.",
        "  - The low estimate assumes a voluntary disclosure lodged within 30 days of "
        "the payday and a clean 24-month history; the high estimate assumes neither. "
        "Choice loading, the late payment penalty and interest on an unpaid assessment "
        "are not included. The ATO assesses the charge.",
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
