"""Verdicts, exposure figures, console summary and report.csv."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .calendar import BusinessCalendar
from .deadlines import ContribLine, Deadline, SKIP_DB, apply_item4, compute_due
from .rates import GicTable
from .sgc import exposure_range, notional_earnings, uplift_scenarios

ON_TIME = "ON_TIME"
LATE = "LATE"
AT_RISK = "AT_RISK"
UNKNOWN = "UNKNOWN"
SKIPPED = "SKIPPED"

CENTS = Decimal("0.01")


def money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return str(value.quantize(CENTS, rounding=ROUND_HALF_UP))


@dataclass
class Result:
    line: ContribLine
    deadline: Deadline
    verdict: str
    days_late: int | None = None
    shortfall: Decimal | None = None
    nec: Decimal | None = None
    sgc_low: Decimal | None = None
    sgc_high: Decimal | None = None
    uplift: dict[str, dict[str, Decimal]] | None = None
    warnings: list[str] = field(default_factory=list)


def assess(
    lines: list[ContribLine], cal: BusinessCalendar, gic: GicTable, as_at: date
) -> list[Result]:
    pairs = [(line, compute_due(line, cal)) for line in lines]
    apply_item4(pairs)

    results: list[Result] = []
    for line, dl in pairs:
        warnings = list(dl.notes)

        if dl.pathway == SKIP_DB or dl.due is None:
            results.append(Result(line, dl, SKIPPED, warnings=warnings))
            continue

        settled = line.received
        if settled is None and line.remitted is not None:
            warnings.append(
                "no fund-receipt date supplied: the statutory test is receipt by the "
                "fund (SGAA s 18C(1)), so a remittance date alone cannot show the "
                "contribution was on time"
            )

        if settled is not None:
            verdict = ON_TIME if settled <= dl.due else LATE
        elif line.remitted is not None:
            verdict = AT_RISK if line.remitted <= dl.due else LATE
        else:
            results.append(
                Result(
                    line,
                    dl,
                    UNKNOWN,
                    warnings=warnings
                    + ["no remittance or fund-receipt date supplied: cannot assess"],
                )
            )
            continue

        result = Result(line, dl, verdict, warnings=warnings)

        if verdict == LATE:
            landed = settled if settled is not None else line.remitted
            result.days_late = (landed - dl.due).days
            shortfall = line.sg_amount
            # NEC runs from the day after the deadline until the shortfall is
            # cleared (day before receipt) or, while unpaid, to the as-at date.
            if settled is not None and settled <= as_at:
                nec_end = settled - timedelta(days=1)
            else:
                nec_end = as_at
                result.warnings.append(
                    "treated as still unpaid at the as-at date: notional earnings keep "
                    "accruing until the fund receives the contribution"
                )
            result.nec = notional_earnings(shortfall, dl.due, nec_end, gic)
            result.shortfall = shortfall
            result.uplift = uplift_scenarios(shortfall, result.nec)
            result.sgc_low, result.sgc_high = exposure_range(shortfall, result.nec)
            stale = gic.staleness(nec_end)
            if stale:
                result.warnings.append(stale)

        results.append(result)

    return results


def write_csv(results: list[Result], path: str | Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "row",
                "employee_id",
                "qe_day",
                "pathway",
                "due_date",
                "verdict",
                "days_late",
                "sg_amount",
                "notional_earnings",
                "uplift_best_case",
                "uplift_worst_case",
                "sgc_estimate_low",
                "sgc_estimate_high",
                "warnings",
            ]
        )
        for r in results:
            uplift_low = uplift_high = None
            if r.uplift is not None:
                uplift_low = r.uplift["clean_history"]["vds_within_30d"]
                uplift_high = r.uplift["prior_history"]["no_vds"]
            writer.writerow(
                [
                    r.line.row,
                    r.line.employee_id,
                    r.line.qe_day.isoformat(),
                    r.deadline.pathway,
                    r.deadline.due.isoformat() if r.deadline.due else "",
                    r.verdict,
                    "" if r.days_late is None else r.days_late,
                    money(r.line.sg_amount),
                    money(r.nec),
                    money(uplift_low),
                    money(uplift_high),
                    money(r.sgc_low),
                    money(r.sgc_high),
                    " | ".join(r.warnings),
                ]
            )


def console_summary(
    results: list[Result], as_at: date, csv_path: str | Path, law_date: str
) -> str:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1

    lines = [
        f"payday-super-checker: {len(results)} contribution lines, as at {as_at.isoformat()}",
        "",
        "  " + "  ".join(f"{v}: {counts.get(v, 0)}" for v in (ON_TIME, AT_RISK, LATE, UNKNOWN, SKIPPED)),
        "",
    ]

    late = [r for r in results if r.verdict == LATE]
    if late:
        late.sort(key=lambda r: r.sgc_high or Decimal(0), reverse=True)
        lines.append("Late lines (largest estimated exposure first):")
        for r in late[:10]:
            lines.append(
                f"  row {r.line.row}  {r.line.employee_id}  QE day {r.line.qe_day.isoformat()}"
                f"  due {r.deadline.due.isoformat()}  {r.days_late} days late"
            )
            lines.append(
                f"      shortfall ${money(r.line.sg_amount)}  notional earnings "
                f"${money(r.nec)}  SG charge estimate ${money(r.sgc_low)}"
                f" - ${money(r.sgc_high)}"
            )
        if len(late) > 10:
            lines.append(f"  ... and {len(late) - 10} more (see {csv_path})")
        lines.append("")

    at_risk = [r for r in results if r.verdict == AT_RISK]
    if at_risk:
        lines.append(
            f"{len(at_risk)} line(s) remitted by the deadline but with no fund-receipt "
            "date. Compliance turns on receipt by the fund, not the day you paid, and "
            "clearing-house transit time is the employer's risk."
        )
        lines.append("")

    lines += [
        "Assumptions and limits:",
        f"  - Legal content current at {law_date}; ATO law companion rulings "
        "LCR 2026/D1-D4 were still drafts at that date.",
        "  - Deadlines use the national business-day calendar in SGAA s 6(1): "
        "weekends plus holidays applying to the whole of any State, the ACT or the NT.",
        "  - Exposure figures are estimates of shortfall, notional earnings and "
        "administrative uplift only. Choice loading, the late payment penalty and "
        "interest on an unpaid assessment are not included. The ATO assesses the charge.",
        "  - Maximum contributions base ($270,830 for 2026-27, annual per employer) is "
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
