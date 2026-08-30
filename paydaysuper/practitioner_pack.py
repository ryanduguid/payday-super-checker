"""Strict, privacy-conscious practitioner handoff for a checker report.

The source CSV remains the row-level workpaper.  This module produces a
deterministic Markdown index and checklist which refers to source row numbers,
never employee identifiers, and leaves every professional judgement and
consequential action to an appropriately authorised human.
"""
from __future__ import annotations

import csv
import os
import hashlib
import io
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .atomic_io import atomic_text_output, markdown_destination


# Deliberately duplicated from report.CSV_HEADER.  A producer change must fail
# a contract test until this consumer is consciously reviewed and updated.
EXPECTED_REPORT_HEADER = (
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
    "unassessable_between",
)

VERDICTS = ("ON_TIME", "AT_RISK", "LATE", "UNPAID", "UNKNOWN", "SKIPPED")
EXPOSURE_FIELDS = (
    "final_shortfall",
    "notional_earnings",
    "uplift_best_case",
    "uplift_worst_case",
    "sgc_estimate_low",
    "sgc_estimate_high",
)


class PractitionerPackError(ValueError):
    """The supplied checker report is not safe to turn into a review pack."""


@dataclass(frozen=True)
class ReportRow:
    source_row: int
    qe_day: date
    pathway: str
    due_date: date | None
    verdict: str
    days_late: int | None
    lateness_measured_to: str
    sg_amount: Decimal
    final_shortfall: Decimal | None
    notional_earnings: Decimal | None
    uplift_best_case: Decimal | None
    uplift_worst_case: Decimal | None
    sgc_estimate_low: Decimal | None
    sgc_estimate_high: Decimal | None
    caveats: str
    notes: str
    unassessable_between: str


@dataclass(frozen=True)
class ReportSnapshot:
    source_path: Path
    source_sha256: str
    rows: tuple[ReportRow, ...]
    provenance: str

    @property
    def needs_attention(self) -> bool:
        return any(row.verdict != "ON_TIME" for row in self.rows)


def _iso_date(value: str, *, field: str, source_row: str, optional: bool = False) -> date | None:
    if not value:
        if optional:
            return None
        raise PractitionerPackError(f"source row {source_row} has a blank {field}")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise PractitionerPackError(
            f"source row {source_row} {field} must be an ISO date, got {value!r}"
        ) from exc
    if parsed.isoformat() != value:
        raise PractitionerPackError(
            f"source row {source_row} {field} must be an ISO date, got {value!r}"
        )
    return parsed


def _amount(value: str, *, field: str, source_row: str, optional: bool) -> Decimal | None:
    if value == "":
        if optional:
            return None
        raise PractitionerPackError(f"source row {source_row} has a blank {field}")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise PractitionerPackError(
            f"source row {source_row} {field} must be a decimal amount, got {value!r}"
        ) from exc
    if not amount.is_finite():
        raise PractitionerPackError(
            f"source row {source_row} {field} must be a finite amount"
        )
    if amount < 0:
        raise PractitionerPackError(
            f"source row {source_row} {field} must not be negative"
        )
    if value != f"{amount:.2f}":
        raise PractitionerPackError(
            f"source row {source_row} {field} must use two decimal places"
        )
    return amount


def _positive_integer(value: str, *, field: str, source_row: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise PractitionerPackError(
            f"source row {source_row} {field} must be a positive integer"
        ) from exc
    if parsed < 1 or str(parsed) != value:
        raise PractitionerPackError(
            f"source row {source_row} {field} must be a positive integer"
        )
    return parsed


def _optional_nonnegative_integer(value: str, *, field: str, source_row: str) -> int | None:
    if value == "":
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise PractitionerPackError(
            f"source row {source_row} {field} must be a non-negative integer"
        ) from exc
    if parsed < 0 or str(parsed) != value:
        raise PractitionerPackError(
            f"source row {source_row} {field} must be a non-negative integer"
        )
    return parsed


def _parse_data_row(values: list[str], seen_rows: set[int]) -> ReportRow:
    record = dict(zip(EXPECTED_REPORT_HEADER, values, strict=True))
    source_row_text = record["row"]
    source_row = _positive_integer(source_row_text, field="row", source_row=source_row_text)
    if source_row in seen_rows:
        raise PractitionerPackError(f"duplicate source row {source_row}")
    seen_rows.add(source_row)

    if not record["employee_id"]:
        raise PractitionerPackError(f"source row {source_row} has a blank employee_id")
    if not record["pathway"]:
        raise PractitionerPackError(f"source row {source_row} has a blank pathway")
    verdict = record["verdict"]
    if verdict not in VERDICTS:
        raise PractitionerPackError(
            f"source row {source_row} has unsupported verdict {verdict!r}"
        )

    qe_day = _iso_date(record["qe_day"], field="qe_day", source_row=str(source_row))
    assert qe_day is not None
    sg_amount = _amount(
        record["sg_amount"], field="sg_amount", source_row=str(source_row), optional=False
    )
    assert sg_amount is not None
    amounts = {
        field: _amount(record[field], field=field, source_row=str(source_row), optional=True)
        for field in EXPOSURE_FIELDS
    }

    exposure = [amounts[field] for field in EXPOSURE_FIELDS]
    if verdict in {"LATE", "UNPAID"}:
        if any(value is None for value in exposure):
            raise PractitionerPackError(
                f"source row {source_row} exposed verdict has incomplete exposure amounts"
            )
        shortfall, nec, uplift_low, uplift_high, estimate_low, estimate_high = exposure
        assert shortfall is not None
        assert nec is not None
        assert uplift_low is not None
        assert uplift_high is not None
        assert estimate_low is not None
        assert estimate_high is not None
        if estimate_low != shortfall + nec + uplift_low:
            raise PractitionerPackError(
                f"source row {source_row} low SG-charge estimate does not add up"
            )
        if estimate_high != shortfall + nec + uplift_high:
            raise PractitionerPackError(
                f"source row {source_row} high SG-charge estimate does not add up"
            )
        if uplift_low > uplift_high or estimate_low > estimate_high:
            raise PractitionerPackError(
                f"source row {source_row} exposure range is reversed"
            )
    elif any(value is not None for value in exposure):
        raise PractitionerPackError(
            f"source row {source_row} non-exposed verdict carries exposure amounts"
        )

    candidates = record["unassessable_between"]
    if candidates and verdict != "UNKNOWN":
        raise PractitionerPackError(
            f"source row {source_row} carries candidate verdicts but is not UNKNOWN"
        )
    if candidates:
        parts = candidates.split(" or ")
        allowed = set(VERDICTS) | {"NOT_YET_DUE"}
        if len(parts) != 2 or any(part not in allowed for part in parts):
            raise PractitionerPackError(
                f"source row {source_row} has malformed candidate verdicts"
            )

    days_late = _optional_nonnegative_integer(
        record["days_late"], field="days_late", source_row=str(source_row)
    )
    if verdict in {"LATE", "UNPAID"} and days_late is None:
        raise PractitionerPackError(
            f"source row {source_row} exposed verdict has no days_late"
        )

    return ReportRow(
        source_row=source_row,
        qe_day=qe_day,
        pathway=record["pathway"],
        due_date=_iso_date(
            record["due_date"],
            field="due_date",
            source_row=str(source_row),
            optional=True,
        ),
        verdict=verdict,
        days_late=days_late,
        lateness_measured_to=record["lateness_measured_to"],
        sg_amount=sg_amount,
        final_shortfall=amounts["final_shortfall"],
        notional_earnings=amounts["notional_earnings"],
        uplift_best_case=amounts["uplift_best_case"],
        uplift_worst_case=amounts["uplift_worst_case"],
        sgc_estimate_low=amounts["sgc_estimate_low"],
        sgc_estimate_high=amounts["sgc_estimate_high"],
        caveats=record["caveats"],
        notes=record["notes"],
        unassessable_between=candidates,
    )



def load_report_snapshot(path: str | Path) -> ReportSnapshot:
    """Read and validate one immutable byte snapshot of a checker report."""
    raw = os.fspath(path)
    if "\x00" in raw:
        raise PractitionerPackError("path contains a NUL byte")
    name = Path(raw).name
    if name != raw:
        raise PractitionerPackError(
            "report path must be a .csv filename in the working directory, with no "
            f"directory part: cd to the directory holding {name}, or copy it here, "
            "and pass the bare filename"
        )
    if os.path.splitext(name)[1].lower() != ".csv":
        raise PractitionerPackError(f"{path} must be a .csv checker report")
    root = os.path.abspath(os.getcwd())
    candidate = os.path.join(root, name)
    with open(candidate, "rb") as handle:  # codeql[py/path-injection]
        data = handle.read()
    source = Path(candidate)
    digest = hashlib.sha256(data).hexdigest()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PractitionerPackError(f"{source} is not UTF-8 CSV") from exc
    try:
        table = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        raise PractitionerPackError(f"{source} is malformed CSV: {exc}") from exc
    if not table or tuple(table[0]) != EXPECTED_REPORT_HEADER:
        raise PractitionerPackError(
            f"{source} must use the exact 18-column payday-super-checker report header"
        )

    body = table[1:]
    for csv_row, values in enumerate(body, start=2):
        if len(values) != len(EXPECTED_REPORT_HEADER):
            raise PractitionerPackError(
                f"CSV row {csv_row} has {len(values)} fields; expected 18"
            )

    def is_terminal_note(values: list[str]) -> bool:
        record = dict(zip(EXPECTED_REPORT_HEADER, values, strict=True))
        return (
            record["row"] == ""
            and record["employee_id"] == "NOTE"
            and all(
                not value
                for field, value in record.items()
                if field not in {"employee_id", "notes"}
            )
        )

    note_rows = [index for index, values in enumerate(body) if is_terminal_note(values)]
    if not note_rows:
        raise PractitionerPackError(f"{source} must end with one terminal NOTE row")
    if len(note_rows) != 1:
        raise PractitionerPackError(f"{source} must contain exactly one NOTE row")
    if note_rows[0] != len(body) - 1:
        raise PractitionerPackError(f"{source} NOTE row must be the terminal NOTE row")

    note_record = dict(zip(EXPECTED_REPORT_HEADER, body[-1], strict=True))
    unexpected_note_values = [
        field
        for field, value in note_record.items()
        if field not in {"employee_id", "notes"} and value
    ]
    if unexpected_note_values or not note_record["notes"].strip():
        raise PractitionerPackError(
            f"{source} has a malformed terminal NOTE row"
        )

    seen_rows: set[int] = set()
    data_rows = body[:-1]
    if not data_rows:
        raise PractitionerPackError(
            f"{source} must contain at least one contribution row"
        )
    rows = tuple(_parse_data_row(values, seen_rows) for values in data_rows)
    return ReportSnapshot(
        source_path=source,
        source_sha256=digest,
        rows=rows,
        provenance=note_record["notes"],
    )


def _markdown(value: object) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    for character in ("\\", "`", "[", "]", "|", "<", ">"):
        text = text.replace(character, f"\\{character}")
    return text


def _money(value: Decimal) -> str:
    return f"${value:,.2f}"


def _review_task(row: ReportRow) -> str:
    if row.verdict == "UNPAID":
        return (
            "Confirm the payday, SG amount, receipt and remittance evidence, and any "
            "assessment facts; an authorised practitioner decides any remediation or lodgment."
        )
    if row.verdict == "LATE":
        return (
            "Verify the receipt date, allocation and assessment facts, then have an "
            "authorised practitioner decide any correction, advice or lodgment."
        )
    if row.verdict == "AT_RISK":
        return (
            "Obtain and verify the fund receipt date; remittance alone is not proof of "
            "on-time receipt."
        )
    if row.verdict == "UNKNOWN":
        if row.unassessable_between:
            return (
                "Resolve the missing calendar or allocation facts before deciding between "
                f"{row.unassessable_between}."
            )
        return (
            "Confirm whether this is genuinely nil or not yet due; do not infer a pass "
            "from UNKNOWN."
        )
    if row.verdict == "SKIPPED":
        return "Assess the defined-benefit interest outside this tool."
    raise AssertionError(f"no review task for {row.verdict}")


def render_practitioner_pack(snapshot: ReportSnapshot) -> str:
    """Render a deterministic review index without employee identifiers."""
    counts = Counter(row.verdict for row in snapshot.rows)
    exposed = [row for row in snapshot.rows if row.verdict in {"LATE", "UNPAID"}]
    total_low = sum(
        (row.sgc_estimate_low for row in exposed if row.sgc_estimate_low is not None),
        Decimal("0.00"),
    )
    total_high = sum(
        (row.sgc_estimate_high for row in exposed if row.sgc_estimate_high is not None),
        Decimal("0.00"),
    )
    status = "ATTENTION REQUIRED" if snapshot.needs_attention else "NO EXCEPTION INDICATORS"

    lines = [
        "# Payday Super Practitioner Review Pack",
        "",
        f"**Status: {status}.**",
        "",
        (
            "Private workpaper. This pack indexes the checker report; it does not lodge, "
            "pay, post or make a compliance determination. An appropriately authorised "
            "human remains responsible for every professional judgement and consequential action."
        ),
        "",
        "## Source and provenance",
        "",
        f"- Source report: {_markdown(snapshot.source_path.name)}",
        f"- Source SHA-256: `{snapshot.source_sha256}`",
        f"- Contribution rows: {len(snapshot.rows)}",
        f"- Producer NOTE: {_markdown(snapshot.provenance)}",
        "",
        "## Verdict summary",
        "",
        "| Verdict | Rows |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {verdict} | {counts.get(verdict, 0)} |" for verdict in VERDICTS)
    lines += [
        "",
        "The displayed experimental SG-charge range across LATE and UNPAID rows is "
        f"**{_money(total_low)} to {_money(total_high)}**. Reconcile it to the source "
        "report; it is not an ATO assessment.",
        "",
        "## Review queue",
        "",
    ]

    attention = [row for row in snapshot.rows if row.verdict != "ON_TIME"]
    priority = {"UNPAID": 0, "LATE": 1, "UNKNOWN": 2, "AT_RISK": 3, "SKIPPED": 4}
    attention.sort(key=lambda row: (priority[row.verdict], row.source_row))
    if not attention:
        lines += [
            "No non-ON_TIME rows were produced. Practitioner sign-off is still required; "
            "verify the source evidence and the checker assumptions before relying on the report.",
            "",
        ]
    else:
        lines += [
            "The identifiers stay in the private source CSV. Use the original `row` value below "
            "to locate each employee record.",
            "",
            "| Done | Source reference | QE day | Due | Verdict | Displayed range | Human review task |",
            "| --- | --- | --- | --- | --- | ---: | --- |",
        ]
        for row in attention:
            due = row.due_date.isoformat() if row.due_date else "not established"
            verdict = row.verdict
            if row.unassessable_between:
                verdict += f" ({row.unassessable_between})"
            exposure_range = "—"
            if row.sgc_estimate_low is not None and row.sgc_estimate_high is not None:
                exposure_range = (
                    f"{_money(row.sgc_estimate_low)} to {_money(row.sgc_estimate_high)}"
                )
            task = _review_task(row)
            if row.caveats:
                task += f" Checker caveat: {row.caveats}"
            lines.append(
                "| [ ] | "
                f"source row {row.source_row} | {row.qe_day.isoformat()} | {_markdown(due)} | "
                f"{_markdown(verdict)} | {_markdown(exposure_range)} | {_markdown(task)} |"
            )
        lines.append("")

    lines += [
        "## Practitioner sign-off",
        "",
        "- [ ] The source report SHA-256 above matches the file reviewed.",
        "- [ ] The payroll, clearing-house and fund evidence has been reconciled for every queued row.",
        "- [ ] Missing calendar, allocation, assessment and classification facts have been resolved or escalated.",
        "- [ ] Any advice, correction, payment, lodgment or disclosure was decided and performed by an appropriately authorised human.",
        "",
        "Reviewer: ______________________________",
        "",
        "Review date (Australia): ______________________________",
        "",
        "Conclusion and workpaper reference: ______________________________",
        "",
    ]
    return "\n".join(lines)


def write_practitioner_pack(snapshot: ReportSnapshot, path: str | Path) -> None:
    """Atomically write a Markdown pack at the caller-selected destination."""
    with atomic_text_output(
        path,
        encoding="utf-8",
        destination_validator=markdown_destination,
    ) as stream:
        stream.write(render_practitioner_pack(snapshot))
