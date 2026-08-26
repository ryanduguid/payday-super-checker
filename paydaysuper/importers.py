"""Read a payroll export and a super payments export, join them, and write
the canonical contributions CSV.

No vendor export carries a fund receipt date. Xero gives the date a payment
was sent to the fund, MYOB gives a Paid Date, Employment Hero gives a Beam
status. The deadline in s 18C tests receipt, and clearing-house transit is
the employer's risk, so every vendor date lands in `remitted` and the receipt
column is left empty. Where a profile classifies a status column
(`Profile.remitted_status`), a vendor date only lands in `remitted` when the
row's status shows the payment actually left the employer: a Beam batch
still at Created, Submission accepted or Awaiting payment carries a Payment
Date for money that was never sent, and writing that date as a remittance
would read a wholly unfunded payday as remitted by the deadline.

Duplicate headers: `profiles._index` normalises headings and silently keeps
the first of two that collide, because column *matching* only needs one
usable candidate. Reading a real file is different: two columns that both
normalise to "amount" mean the tool cannot tell which one is the real
figure, and every amount it reports becomes a guess. `csv_io.py` already
refuses a file outright over duplicate column names for the same reason.
This module carries that same refusal for the general case (headings equal
once case, punctuation and spacing are folded, not only when they are
byte-for-byte identical), checked once here rather than by changing
`_index`, because `_index`'s silent-first behaviour is still correct for
`detect`/`resolve_columns` scoring a header row that was never going to be
read as data.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from .atomic_io import atomic_text_output
from .csv_io import (
    AMOUNT_TEXT,
    LATEST_SANE_YEAR,
    MISSING,
    CsvError,
    cents,
    csv_safe,
    malformed_row_problem,
    money,
    parse_date_text,
    raise_problems,
)
from .deadlines import REGIME_START
from .profiles import (
    Profile,
    detect,
    normalise_header,
    resolve_columns,
)

# A separator is allowed only where a thousands separator belongs. Stripping
# every comma turns the European decimal 612,00 into 61200. The pattern
# lives in csv_io so this module and the checker's own reader cannot drift
# apart on what an amount is; see csv_io.AMOUNT_TEXT.
_AMOUNT = AMOUNT_TEXT


@dataclass(frozen=True)
class PayrollRow:
    employee_id: str | None
    employee_name: str | None
    payday: date
    period_end: date | None
    sg_amount: Decimal
    row: int

    @property
    def effective_period_end(self) -> date:
        return self.period_end or self.payday


@dataclass(frozen=True)
class SuperRow:
    employee_id: str | None
    employee_name: str | None
    period_start: date | None
    period_end: date | None
    paid_date: date | None
    amount: Decimal
    row: int
    # The vendor status that showed this payment never left the employer
    # (whitespace-collapsed, as written otherwise), set only where a
    # profile's `remitted_status` classified the row as not sent. Such a
    # row always carries `paid_date=None`, whatever its date cell said:
    # the date belongs to a payment that was not made. None everywhere
    # else, including for rows whose status shows the payment WAS sent.
    unpaid_status: str | None = None


def _check_duplicate_headers(headers: list[str], path: str | Path) -> None:
    """Refuse a file where two headings normalise to the same field.

    `resolve_columns` (via `profiles._index`) would silently read whichever
    one of them happened to come first, and there is no way for the rest of
    this module to tell that happened. See the module docstring."""
    groups: dict[str, list[str]] = {}
    for h in headers:
        # A heading that folds away to nothing -- "###", say -- is still a
        # heading, and csv_io refuses two byte-identical ones. Skipping the
        # falsy key here made this module's refusal narrower than csv_io's
        # for exactly those files, contradicting the module docstring's
        # claim that it is a superset. Such a heading falls back to its own
        # collapsed text, so two identical ones still collide and two
        # different ones still do not.
        key = normalise_header(h) or " ".join(h.split()).casefold()
        groups.setdefault(key, []).append(h)
    duplicates = {k: v for k, v in groups.items() if len(v) > 1}
    if duplicates:
        detail = "; ".join(
            f"{sorted(headings)} all read as {key!r}"
            for key, headings in sorted(duplicates.items())
        )
        raise CsvError(
            f"{path} has two or more columns that normalise to the same heading: "
            f"{detail}. Only one of them would be read and there is no reliable way "
            "to tell which, so no figure from this file can be trusted. Rename the "
            "columns so each heading is unique."
        )


def _read_dicts(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, restval=cast(Any, MISSING))
            if reader.fieldnames is None:
                raise CsvError(f"{path} has no header row")
            headers = [h for h in reader.fieldnames if h and h.strip()]
            raw_rows = list(reader)
    except UnicodeDecodeError as exc:
        raise CsvError(
            f"{path} is not UTF-8 text (byte {exc.object[exc.start]:#04x} at position "
            f"{exc.start}). Excel's plain 'CSV' export uses the Windows code page: "
            "re-save it as 'CSV UTF-8 (Comma delimited)' and run again."
        )
    _check_duplicate_headers(headers, path)

    # A row with the wrong number of fields is never read as data: a
    # misaligned row (an unescaped comma inside a name, say) shifts every
    # later column one place left, so an amount this tool reports could
    # actually be a different column's value read under the wrong name.
    # csv_io.py's _parse_rows refuses exactly this, and the refusal is now
    # written once as csv_io.malformed_row_problem (fed by the same restval
    # sentinel above), so the checker and the importer cannot drift on what
    # a malformed row is.
    problems: list[str] = []
    rows: list[dict[str, str]] = []
    for i, raw in enumerate(raw_rows, start=2):  # row 1 is the header
        malformed = malformed_row_problem(raw, i)
        if malformed is not None:
            problems.append(malformed)
            continue
        rows.append({k: (v or "") for k, v in raw.items() if k is not None})

    if problems:
        raise_problems(problems, path)
    if not rows:
        raise CsvError(f"{path} has a header but no data rows")
    return headers, rows


def _date(value: str, field: str, row: int, formats: tuple[str, ...]) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    parsed: date | None = None
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        # The profile's own formats first, then every format the checker
        # accepts. A vendor that writes one column ISO and another
        # day-first still reads, instead of failing on a date a human can
        # see is a date.
        try:
            parsed = parse_date_text(text)
        except CsvError as exc:
            # The offset refusal carries no row context of its own; name
            # the cell the way every other message here does.
            raise CsvError(f"row {row}: {field} {exc}")
    if parsed is None:
        raise CsvError(f"row {row}: cannot read {field} value {value!r} as a date")
    if parsed.year > LATEST_SANE_YEAR:
        # The same ceiling csv_io._parse_date applies, for the same reason
        # _amount's magnitude guard mirrors csv_io's: a value this module
        # accepts and the checker would refuse must be refused HERE, at the
        # point closest to the bad input. Without it, an ERP sentinel of
        # 31/12/9999 imported with exit 0 and "matched 2", and the very
        # next command refused the file this one had just written.
        raise CsvError(
            f"row {row}: {field} value {value!r} is not a real date. Leave placeholder "
            "dates such as 9999-12-31 blank instead"
        )
    return parsed


def _amount(value: str, field: str, row: int) -> Decimal:
    """Read one amount cell, to the cent.

    Every figure that leaves this module is a cent figure: `write_canonical`
    writes `money(...)`, the checker reads the file back at that precision,
    and the report it produces is in dollars and cents. Quantising HERE, at
    the read boundary, is what makes `PayrollRow.sg_amount` and
    `SuperRow.amount` cent-clean by construction, so no arithmetic
    downstream can leave a sub-cent residue for the allocator to spend.

    A payroll row of 540.004 settled by a super payment of 540.00 used to
    leave `_unmet` holding 0.004. The next super row whose period reached
    that payday spent the 0.004 on it, and its own later payment date then
    became the payday's remittance date: a payday whose every payable cent
    arrived five days inside the deadline reported LATE with the full
    540.00 as a shortfall and an SG-charge estimate on top, or, where that
    second payment carried no date, UNPAID for the same 540.00. Comparing
    to the cent at the point of the verdict fixed the verdict and left the
    residue in place to move a date; there is no residue to move now.

    ROUND_HALF_UP through `report.cents`, the same rounding `money()`
    applies on the way out, so the figure this reads and the figure it
    writes are the same number rather than two roundings of one input.

    Rounding is per row, and a row is the unit of obligation: one payroll
    row is one payday's liability for one employee, one super row is one
    payment. Nothing here is ever summed across rows to reach a verdict, so
    quantising each row on its own is the same granularity the law and the
    report already work at. What it costs is under half a cent per row, and
    the alternative is the defect above.

    A value that is not zero in the file but rounds to zero is refused
    rather than rounded, because that is the one case where quantising
    would destroy the row instead of trimming it: a payment worth 0.004
    would become a 0.00 payment that still carries a date and still matches
    a payday, and a 0.004 liability would become a payday owing nothing. An
    exact 0 in the file is untouched -- a payday that genuinely owes no
    super guarantee is ordinary, and already has its own outcome."""
    text = (value or "").strip().replace("$", "").strip()
    if text.startswith("(") and text.endswith(")"):
        # Stripped inside the parens too, mirroring _parse_amount: Excel's
        # accounting format writes a negative as "($ 612.00)", and without
        # this strip the space the "$" left behind broke the pattern match,
        # so the refusal blamed a comma for a space instead of naming the
        # negative the way the checker's reader does.
        text = "-" + text[1:-1].strip()
    if not text:
        raise CsvError(f"row {row}: {field} is empty")
    if not _AMOUNT.match(text):
        raise CsvError(
            f"row {row}: cannot read {field} value {value!r} as an amount. A comma or "
            "space is only read as a thousands separator, so 612,00 is refused rather "
            "than read as 61200."
        )
    try:
        amount = Decimal(text.replace(",", "").replace(" ", ""))
    except InvalidOperation:
        raise CsvError(f"row {row}: cannot read {field} value {value!r} as an amount")
    if not amount.is_finite():
        raise CsvError(f"row {row}: cannot read {field} value {value!r} as an amount")
    if amount.adjusted() > 15:
        # Mirrors csv_io._parse_amount's own guard: beyond this the value
        # cannot be rounded to cents under the default decimal context (28
        # significant digits), and no super contribution is this large.
        # Without this check here, `write_canonical`'s `money()` call is
        # the first place such a value would be quantized, raising a raw
        # decimal.InvalidOperation that is not a CsvError and so escapes
        # the CLI's `except (CsvError, ..., ValueError)` -- a value this
        # module accepted and the checker itself would refuse must be
        # refused here, at the point closest to the bad input, not left to
        # fail unpredictably downstream.
        raise CsvError(f"row {row}: {field} value {value!r} is too large to be a real amount")
    if amount < 0:
        raise CsvError(f"row {row}: {field} is negative ({value!r})")
    rounded = cents(amount)
    if rounded == 0 and amount != 0:
        raise CsvError(
            f"row {row}: {field} value {value!r} is under half a cent, so reading it "
            "to the cent leaves the row carrying no money at all. Every figure this "
            "tool matches, writes and reports is a cent figure. Round it yourself, or "
            "take the row out."
        )
    return rounded


def _cell(row: dict[str, str], resolved: dict[str, str], field: str) -> str:
    heading = resolved.get(field)
    if heading is None:
        return ""
    return (row.get(heading) or "").strip()


def read_super(
    path: str | Path, vendor: str | None = None
) -> tuple[list[SuperRow], Profile, dict[str, str]]:
    """Read a super payments export.

    Returns the rows, the profile that matched, and the canonical-field-to-
    heading mapping `resolve_columns` found for THIS file's headers. The
    third element exists so a caller such as `import_files` can tell "this
    file's period_start/period_end columns are structurally absent" from
    "this row's period cell happened to be blank" -- `join`'s
    `super_has_period_start`/`super_has_period_end` need exactly that
    file-level fact, and it is gone once the rows below are built."""
    headers, raw_rows = _read_dicts(path)
    profile = detect(headers, "super", vendor)
    resolved = resolve_columns(profile, headers)
    if "amount" not in resolved:
        raise CsvError(f"{path}: no amount column found for profile {profile.key}")
    if profile.sg_filter is not None and profile.sg_filter.column not in resolved:
        raise CsvError(
            f"{path} has no contribution type column, so salary sacrifice and "
            "additional contributions cannot be told apart from super guarantee. "
            "Re-run the report with that column included, or map the file by hand."
        )
    status_rule = profile.remitted_status
    if status_rule is not None and status_rule.column not in resolved:
        raise CsvError(
            f"{path} has no payment status column, so a batch whose money never "
            "left the employer cannot be told apart from one that was paid, and "
            "every payment date in the file would be read as a remittance. "
            "Re-run the report with that column included, or map the file by hand."
        )
    wanted = {normalise_header(v) for v in (profile.sg_filter.include if profile.sg_filter else ())}
    sent_statuses = {normalise_header(v) for v in (status_rule.sent if status_rule else ())}
    not_sent_statuses = {normalise_header(v) for v in (status_rule.not_sent if status_rule else ())}
    rows: list[SuperRow] = []
    for i, raw in enumerate(raw_rows, start=2):
        if profile.sg_filter is not None:
            kind = normalise_header(_cell(raw, resolved, profile.sg_filter.column))
            if kind not in wanted:
                continue
        paid_date = _date(_cell(raw, resolved, "paid_date"), "paid date", i, profile.date_formats)
        unpaid_status = None
        if status_rule is not None:
            status_text = _cell(raw, resolved, status_rule.column)
            status_key = normalise_header(status_text)
            if status_key in not_sent_statuses:
                # The date cell belongs to a payment the status says was
                # never made. Written through as a remittance, it would read
                # a wholly unfunded payday as remitted by the deadline --
                # the same rule `join` applies to an undated row: no
                # evidence the money went is a blank date, not a date.
                unpaid_status = " ".join(status_text.split())
                paid_date = None
            elif status_key not in sent_statuses:
                raise CsvError(
                    f"row {i}: status {status_text!r} is not one this tool knows "
                    f"for profile {profile.key} (payment left the employer: "
                    f"{list(status_rule.sent)}; money not yet sent: "
                    f"{list(status_rule.not_sent)}), so there is no way to tell "
                    "whether this payment was made. Correct the status column, "
                    "or map the file by hand."
                )
        rows.append(
            SuperRow(
                employee_id=_cell(raw, resolved, "employee_id") or None,
                employee_name=_cell(raw, resolved, "employee_name") or None,
                period_start=_date(_cell(raw, resolved, "period_start"), "period start", i, profile.date_formats),
                period_end=_date(_cell(raw, resolved, "period_end"), "period end", i, profile.date_formats),
                paid_date=paid_date,
                amount=_amount(_cell(raw, resolved, "amount"), "amount", i),
                row=i,
                unpaid_status=unpaid_status,
            )
        )
    if not rows:
        raise CsvError(
            f"{path} has rows but none of them is super guarantee. Check the "
            f"contribution types against {list(profile.sg_filter.include)}"
            if profile.sg_filter
            else f"{path} has no usable rows"
        )
    return rows, profile, resolved


def read_payroll(
    path: str | Path, vendor: str | None = None
) -> tuple[list[PayrollRow], Profile, dict[str, str]]:
    """Read a payroll export. Returns the rows, the matched profile, and the
    canonical-field-to-heading mapping `resolve_columns` found for this
    file's headers -- see `read_super`'s docstring for why the third
    element exists."""
    headers, raw_rows = _read_dicts(path)
    profile = detect(headers, "payroll", vendor)
    resolved = resolve_columns(profile, headers)
    for required in ("payday", "amount"):
        if required not in resolved:
            raise CsvError(
                f"{path}: no {required} column found for profile {profile.key}. "
                f"Columns found: {headers}"
            )
    rows: list[PayrollRow] = []
    for i, raw in enumerate(raw_rows, start=2):
        payday = _date(_cell(raw, resolved, "payday"), "payday", i, profile.date_formats)
        if payday is None:
            raise CsvError(f"row {i}: payday is empty")
        rows.append(
            PayrollRow(
                employee_id=_cell(raw, resolved, "employee_id") or None,
                employee_name=_cell(raw, resolved, "employee_name") or None,
                payday=payday,
                period_end=_date(_cell(raw, resolved, "period_end"), "period end", i, profile.date_formats),
                sg_amount=_amount(_cell(raw, resolved, "amount"), "sg amount", i),
                row=i,
            )
        )
    return rows, profile, resolved




from .join import (  # noqa: E402,F401
    ORPHAN_NO_AMOUNT,
    ORPHAN_NO_PAYDAY,
    ORPHAN_NOTHING_OWED,
    ORPHAN_PAYDAYS_SETTLED,
    JoinResult,
    MatchOutcome,
    OrphanReason,
    _allocate,
    _check_defensible,
    _check_reversed_periods,
    _covers,
    _coverage,
    _key,
    _super_order,
    _unmet,
    _why_orphaned,
    join,
)

CANONICAL_HEADER = [
    "employee_id",
    "payment_date",
    "sg_amount",
    "remitted_date",
    "fund_received_date",
    "first_contribution_to_fund",
    "out_of_cycle",
    "next_standard_payday",
    "defined_benefit",
    "remitted_amount",
    "matched_amount",
]


def _iso(value: date | None) -> str:
    return value.isoformat() if value else ""


# How one PAYROLL row's join outcome is classified, both for
# `ImportReport`'s counts and (see `write_canonical`) for deciding what is
# safe to write into the canonical CSV. Deliberately separate from the
# ORPHAN_* constants above: those classify an unused SUPER row, these
# classify a payroll row, and the two answer different questions for
# different readers. Plain strings, not an enum, to match ORPHAN_*'s own
# style and stay trivially printable.
OUTCOME_MATCHED = "matched"
OUTCOME_OWES_NOTHING = "owes nothing"
# "no remittance date", not "no fund-receipt evidence": fund_received_date
# is blank on EVERY row this module writes, so naming a fund receipt here
# described the one thing that is never true of one row and not another.
# What this bucket means is that no matched amount carries a usable vendor
# payment date. A mixed match with a dated subtotal is classified PARTIAL,
# because only that subtotal is evidenced as remitted.
OUTCOME_UNDATED = "matched, no remittance date"
OUTCOME_PARTIAL = "partial"
OUTCOME_OVER = "over"
OUTCOME_UNMATCHED = "unmatched"


def _classify_outcome(outcome: MatchOutcome) -> str:
    """Bucket one payroll row's join outcome.

    Order matters: more than one bucket can be literally true of the same
    outcome (a partial match can also be missing a remittance date on the
    portion that did arrive), and the more specific, more actionable
    classification must win. A short payment is reported as partial even
    though part of what it did receive has no receipt evidence either --
    "you are short" is the more urgent fact than "and also go find dates
    for the rest"."""
    row = outcome.payroll
    if row.sg_amount == 0:
        return OUTCOME_OWES_NOTHING
    if outcome.flag == "no super payment found":
        return OUTCOME_UNMATCHED
    if outcome.flag.startswith("partial: "):
        return OUTCOME_PARTIAL
    if outcome.flag.startswith("over: "):
        return OUTCOME_OVER
    if (
        outcome.remitted_amount is not None
        and cents(outcome.remitted_amount) < cents(row.sg_amount)
    ):
        return OUTCOME_PARTIAL
    if outcome.remitted is None:
        return OUTCOME_UNDATED
    return OUTCOME_MATCHED


def write_canonical(result: JoinResult, path: str | Path) -> None:
    """Write the canonical contributions CSV that
    `paydaysuper.csv_io.parse_rows` reads unmodified with its default
    mapping: `CANONICAL_HEADER` is exactly the set of values in
    `csv_io.DEFAULT_MAPPING`, in the same field order.

    `sg_amount` is what was OWED, never shrunk to what arrived. A dated
    part payment writes `remitted_date` and `remitted_amount` so operational
    reporting can distinguish the dated subtotal from the full liability.
    For a mixed dated/undated match, `remitted_date` is the latest known date
    for the dated subtotal and `remitted_amount` is that subtotal only. The
    checker therefore takes no operational credit before that date and shows
    the undated remainder afterwards. `matched_amount` separately preserves
    the total contribution amount associated with the payday, even when the
    vendor supplied no date. It caps any receipt credit an operator later
    adds. An importer-generated unmatched row writes zero; blank retains the
    whole-liability meaning of older canonical files.

    The employee label is the key `join` matched on, not `employee_id or
    employee_name`: under name matching a file where only some rows carry
    an id would otherwise write the id for those rows and the name for the
    rest, splitting one person the join had already merged into two
    identities in the checker's own per-employee grouping. Every row
    sharing a key writes the same label, the first one seen for that key.

    `fund_received_date` and the four flag columns are always written
    blank. No payroll or clearing-house export this tool reads carries a
    fund receipt date or these flags (see the module docstring and
    `join`'s), and inventing any of them would silently move a deadline --
    the worst defect this feature could ship.

    Every field is passed through `csv_safe`, not only employee_id. Money
    and date fields built here cannot start with a formula-lead character
    today (amounts are never negative, dates are ISO, the flag columns are
    always blank), but running all of them through the one guard is one
    rule with no unstated exception, rather than a rule that only covers
    the field known to carry attacker-controlled text today."""
    labels: dict[str, str] = {}
    for outcome in result.outcomes:
        row = outcome.payroll
        preferred = (
            row.employee_id if result.key_mode == "id" else row.employee_name
        ) or row.employee_id or row.employee_name or ""
        labels.setdefault(_key(row, result.key_mode), preferred)

    with atomic_text_output(path, encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(CANONICAL_HEADER)
        for outcome in result.outcomes:
            row = outcome.payroll
            label = labels[_key(row, result.key_mode)]
            credited = outcome.remitted_amount
            if credited is not None and cents(credited) > cents(row.sg_amount):
                credited = row.sg_amount
            matched = outcome.matched_amount
            if matched is not None and cents(matched) > cents(row.sg_amount):
                matched = row.sg_amount
            values = [
                label,
                _iso(row.payday),
                money(row.sg_amount),
                _iso(outcome.remitted),
                "",  # fund_received_date: no vendor export carries a receipt date
                "",  # first_contribution_to_fund
                "",  # out_of_cycle
                "",  # next_standard_payday
                "",  # defined_benefit
                money(credited) if credited is not None else "",
                money(matched) if matched is not None else "",
            ]
            writer.writerow(csv_safe(v) for v in values)


def _pre_regime_warnings(payroll_rows: list[PayrollRow]) -> list[str]:
    """Warn about paydays the checker will refuse the whole file over.

    A payroll export spanning 30 June -- the normal shape of a
    financial-year export -- imports without complaint, and the check then
    dies with "N row(s) have a QE day before 1 Jul 2026 ... Remove them and
    run again" and writes no report at all. The README promises two
    commands turn an export into a checked report, and this is where that
    promise dead-ends, so the first command says it rather than leaving the
    second to.

    A warning, not a refusal: the rows are real payroll data and the file
    written here is still the workpaper the user edits. Naming the rows is
    the point -- they are what has to come out."""
    early = [r for r in payroll_rows if r.payday < REGIME_START]
    if not early:
        return []
    shown = ", ".join(str(r.row) for r in early[:20])
    more = f" and {len(early) - 20} more" if len(early) > 20 else ""
    earliest = min(r.payday for r in early).isoformat()
    return [
        f"{len(early)} payroll row(s) have a payday before "
        f"{REGIME_START.isoformat()} (row(s) {shown}{more}; earliest {earliest}), and "
        "the check refuses any file containing one: those paydays are governed by the "
        "old quarterly SG law, which this tool does not model. They are written to the "
        "output anyway, because they are real payroll rows -- delete them from it, or "
        "re-export from the start of the financial year in which payday super applies, "
        "before running the check."
    ]


@dataclass
class ImportReport:
    """What did and did not join, from one `import_files` run.

    `outcome_counts` is keyed by the `OUTCOME_*` constants above, one entry
    per payroll row. `orphan_reasons` is `JoinResult.orphan_reasons`
    unchanged -- the full detail behind every unused super payment, one
    entry per orphan, in the same order as the orphans themselves -- so
    nothing here collapses the four `ORPHAN_*` codes to a bare count: an
    overpayment on already-settled paydays (`ORPHAN_PAYDAYS_SETTLED`) and a
    payment that matched no payday at all (`ORPHAN_NO_PAYDAY`) read as
    opposite findings to an accountant and must stay tellable apart."""

    payroll_profile: Profile
    super_profile: Profile
    outcome_counts: dict[str, int]
    orphan_reasons: list[OrphanReason]
    key_mode: str
    warnings: list[str]

    @property
    def matched(self) -> int:
        return self.outcome_counts.get(OUTCOME_MATCHED, 0)

    @property
    def partial(self) -> int:
        return self.outcome_counts.get(OUTCOME_PARTIAL, 0)

    @property
    def unmatched(self) -> int:
        return self.outcome_counts.get(OUTCOME_UNMATCHED, 0)

    @property
    def orphans(self) -> int:
        """Total orphaned super payments, across all four ORPHAN_* codes.
        See `orphan_reasons` for the breakdown this number alone loses."""
        return len(self.orphan_reasons)

    @property
    def orphan_counts(self) -> dict[str, int]:
        """`orphan_reasons` tallied by ORPHAN_* code."""
        counts: dict[str, int] = {}
        for reason in self.orphan_reasons:
            counts[reason.code] = counts.get(reason.code, 0) + 1
        return counts

    @property
    def clean(self) -> bool:
        unclean_outcomes = (
            OUTCOME_UNDATED,
            OUTCOME_PARTIAL,
            OUTCOME_OVER,
            OUTCOME_UNMATCHED,
        )
        return not (
            any(self.outcome_counts.get(bucket) for bucket in unclean_outcomes)
            or self.orphan_reasons
        )


def import_files(
    payroll_path: str | Path,
    super_path: str | Path,
    out_path: str | Path,
    vendor: str | None = None,
    *,
    statutory_allocation_confirmed: bool = False,
) -> ImportReport:
    """Read a payroll export and a super payments export, join them, write
    the canonical contributions CSV to `out_path`, and return a summary of
    what did and did not join.

    `payroll_has_period_end`/`super_has_period_start`/`super_has_period_end`
    are derived here, not left to `join`'s defaults, from whether
    `resolve_columns` found that field in EACH file's own headers -- a
    file-level fact `read_payroll`/`read_super` surface via their third
    return value, because it is gone once the rows are built into
    `PayrollRow`/`SuperRow` objects (a `None` field on a row is then
    indistinguishable from "this file never had the column at all").

    ``statutory_allocation_confirmed`` is false by default. Where an
    employee has more than one positive payday and at least one contribution,
    the exports cannot prove LCR 2026/2's fund-receipt ordering, earliest-
    shortfall allocation or whether an assessment changed the ordering. The
    caller must reconcile those facts before this function writes a canonical
    file."""
    out = Path(out_path).resolve()
    for source in (payroll_path, super_path):
        if Path(source).resolve() == out:
            raise CsvError(
                f"the output would overwrite {source}. Choose a different path with -o."
            )

    payroll_rows, payroll_profile, payroll_resolved = read_payroll(payroll_path, vendor)
    super_rows, super_profile, super_resolved = read_super(super_path, vendor)

    both_have_ids = (
        bool(payroll_rows)
        and bool(super_rows)
        and all(r.employee_id for r in payroll_rows)
        and all(r.employee_id for r in super_rows)
    )
    key_mode = "id" if both_have_ids else "name"
    super_keys = {_key(row, key_mode) for row in super_rows if row.amount > 0}
    grouped_paydays: dict[str, list[PayrollRow]] = {}
    for row in payroll_rows:
        if (
            row.sg_amount > 0
            and row.payday >= REGIME_START
            and _key(row, key_mode) in super_keys
        ):
            grouped_paydays.setdefault(_key(row, key_mode), []).append(row)
    allocation_groups = [
        rows
        for rows in grouped_paydays.values()
        if len({row.payday for row in rows}) > 1
    ]
    if allocation_groups and not statutory_allocation_confirmed:
        affected_rows = sorted(row.row for rows in allocation_groups for row in rows)
        shown = ", ".join(str(row) for row in affected_rows[:20])
        more = f" and {len(affected_rows) - 20} more" if len(affected_rows) > 20 else ""
        raise CsvError(
            f"{len(allocation_groups)} employee allocation group(s) contain more than "
            f"one positive payday (payroll rows {shown}{more}). LCR 2026/2 "
            "paragraphs 31-33 apply contributions in fund-receipt order to the "
            "earliest QE day with a base or final shortfall. These exports contain "
            "employer payment dates and vendor periods, not fund-receipt order or "
            "assessment facts, so they cannot establish the canonical allocation. "
            "Reconcile every relevant payday, contribution receipt and assessment, "
            "then rerun with --confirm-statutory-allocation; no output was written"
        )
    result = join(
        payroll_rows,
        super_rows,
        payroll_has_period_end="period_end" in payroll_resolved,
        super_has_period_start="period_start" in super_resolved,
        super_has_period_end="period_end" in super_resolved,
    )
    # Keep the original selected path for the writer: it must replace an
    # existing output symlink, not follow it to its target.  ``out`` above is
    # only the canonical path used for the input/output alias check.
    write_canonical(result, out_path)

    outcome_counts: dict[str, int] = {}
    for outcome in result.outcomes:
        bucket = _classify_outcome(outcome)
        outcome_counts[bucket] = outcome_counts.get(bucket, 0) + 1

    warnings = _pre_regime_warnings(payroll_rows) + list(result.warnings)
    if allocation_groups:
        warnings.insert(
            0,
            "operator confirmed the LCR 2026/2 statutory allocation: all relevant "
            "paydays, fund receipts and assessments were reconciled, and the export "
            "periods plus payment-date/row order reproduce the fund-receipt order and "
            "earliest-shortfall application",
        )
    warnings.extend(f"row {o.payroll.row}: {o.flag}" for o in result.outcomes if o.flag)
    warnings.extend(
        f"super row {r.super_row.row}: {r.message}" for r in result.orphan_reasons
    )
    # Why an affected payday reads "no payment date": the row HAS a date in
    # the export, and the status is the reason it was not used. Without this
    # line, someone opens the super file, sees the date, and reads the
    # blank remitted_date as this tool's mistake instead of Beam's ladder.
    warnings.extend(
        f"super row {s.row}: status {s.unpaid_status!r} means the money never "
        "left the employer, so its payment date is not evidence of remittance "
        "and was not used"
        for s in super_rows
        if s.unpaid_status is not None
    )

    return ImportReport(
        payroll_profile=payroll_profile,
        super_profile=super_profile,
        outcome_counts=outcome_counts,
        orphan_reasons=result.orphan_reasons,
        key_mode=result.key_mode,
        warnings=warnings,
    )
