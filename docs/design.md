# payday-super-checker: design

Design as implemented. Legal content researched 2 August 2026 and refreshed
against current primary sources on 15 August 2026. The maintained source record
is `primary-source-review-2026-08-15.md`.

## Purpose

Experimental CLI review aid that reads a pay-run/contribution CSV and, for each super contribution line, computes a payday-super deadline supported by the supplied facts, gives a verdict or an attention-driving indeterminate result, and produces an experimental SG-charge exposure estimate for established late lines. Audience: Australian accountants and employers. Not a payroll system, compliance determination or legal advice.

## Legal basis (current 2026-08-15)

The current pass read the Federal Register, the ATO legal database, direct ATO rate guidance and all eight official jurisdiction holiday sources. F2026L00784, SGAR regulations 11 to 13D, the $270,830 maximum contribution base and LCR 2026/1 to 3 are verified directly. LCR 2026/D1 remains draft pending appeal, so qualifying-earnings classification remains outside the runtime. Full source links, runtime comparisons and residuals are in `primary-source-review-2026-08-15.md`.

LCR 2026/1, LCR 2026/2 and LCR 2026/3 were issued on 5 August 2026;
LCR 2026/D1 is the only one of the original four drafts that remains draft.

- Treasury Laws Amendment (Payday Superannuation) Act 2025 (No. 57 of 2025), assent 6 Nov 2025; SGC Amendment Act 2025 (No. 58 of 2025); Payday Superannuation Regulations 2026 (F2026L00133). Applies to QE days from 1 Jul 2026.
- Deadline: contribution must be **received by the fund** (and allocatable) by end of the 7th business day after the QE day (SGAA s 6(1) "usual period", s 18C(1)(c)(i)). QE day = day earnings actually paid (s 17A(1)). Pre-payments within prior 12 months also count (s 18C(1)(c)(ii)).
- Business day (s 6(1)): not Sat/Sun, not a public holiday applying to the **whole of any** State/ACT/NT. One national calendar. Regional holidays (e.g. Royal Queensland Show) are business days.
- Extended deadline, 20 business days (s 18C(2) item 1): first eligible contribution to a particular fund (new/recommenced employee, or fund switch). Item 4 extends a later QE day only from an earlier eligible contribution evidenced as received, applied to that earlier QE day and on time. A positive amount or remittance alone produces a possible upper bound, never an extension; if that changes the result, the row is attention-driving `UNKNOWN`.
- Out-of-cycle QE (s 18C(2) item 2; F2026L00784): deadline = end of the usual period of the actual subsequent non-out-of-cycle QE payment made on the next schedule-consistent day. The earlier review's “LI 2026/20” shorthand is not displayed on the Federal Register as-made page, so the project pins the controlling registered identifier and text. A flagged row without that actual payment is rejected. There is no fallback.
- Exceptional circumstances (s 18C(2) item 3; reg 13): not auto-detected. The ordinary result is conservative where a determination applies.
- SGC on lateness (s 16B(2)): final shortfall + notional earnings component + administrative uplift (+ choice loading, out of scope). NEC: daily compounding at GIC rate on base shortfall, from the day **after** the last on-time day, until final shortfall nil or day before assessment (s 19A; final LCR 2026/3). Uplift: 60% of (shortfalls + NEC), reduced 20pp clean-history (reg 13C, transitional lookback from 1 Jul 2026) and 40/35/30/15pp by voluntary-disclosure timing (reg 13D). Floor 0%.
- Transition: LCR 2026/1 applies pre-1 July contributions only to the extent they are unused old-regime excess, and applies 1 to 28 July contributions first against the employee's June-quarter shortfall. The CSV cannot hold those balances, so the operator must reconcile and pass `--confirm-transition-allocation`; the confirmation is recorded per affected row.
- Allocation: LCR 2026/2 paragraphs 31 to 33 apply contributions in fund-receipt order to the earliest QE day with a base/final shortfall, subject to assessment facts. The importer has vendor paid dates and periods, not those facts. Multiple positive in-scope paydays for one employee therefore fail closed until `--confirm-statutory-allocation`; within confirmed coverage, short payments allocate oldest outstanding QE day first.
- Regulations 11 and 12 are not applied to raw pay. `sg_amount` is an operator-determined amount after those employee/payment boundaries, qualifying-earnings classification and relevant limits.
- SG rate 12% (s 17A(2)). MCB annual, $270,830 for 2026-27 (s 10A(5)-(6)) - warning only, needs cumulative FY data.
- GIC 11.43% p.a. for Jul-Sep 2026; quarterly reset -> dated rate table. Daily rate = the quarter's annual rate divided by the number of days in the **calendar year of that day** (TAA 1953 s 8AAD): 365 in 2026 and 2027, 366 in 2028. Not a fixed /365.

## Architecture

`paydaysuper/` package, Python >=3.10, **stdlib-only runtime**. Money is `Decimal` dollars everywhere - never floats, never integer cents - and is rounded to cents only where a module says so below. Units:

- `calendar.py` - loads bundled `paydaysuper/data/business_days.json` (+ optional user override JSON), `is_business_day(date)`, `add_business_days(date, n)`, horizon warning when computation leaves the range the table covers. `coverage_until` is that range's end: the bundled `verified_until`, raised only by an override's own `verified_until`. Holding one later holiday is not evidence of completeness and never raises it. Past the coverage end a computed deadline can only be too early: a receipt on or before it is provably on time; a later receipt/remittance, an unfunded row whose shown deadline has passed, and a stale pre-payment whose shown deadline has passed are attention-driving `UNKNOWN` with no exposure. Provisional entries are advisory only and are treated as business days until an official-source override confirms them.
- `deadlines.py` - pure functions implementing the four s 18C pathways; input = line facts, output = `Deadline(due, pathway, notes, caveats, possible_item4_due)`. `due` is the evidenced deadline. Item 4 is applied per employee only from an on-time fund receipt associated with the earlier canonical row; unevidenced rows propagate only the possible upper bound. Calendar caveats are attached after that so they describe the evidenced date.
- `sgc.py` - pure functions: `notional_earnings(shortfall, due, end, gic)` compounding daily GIC over `[due + 1 day, end]` inclusive, across quarter boundaries in the `GicTable` loaded from `paydaysuper/data/gic_rates.json`; `uplift_scenarios(...)` returning the reg 13C/13D matrix. Rounds nothing: the accrual runs at full `Decimal` precision and every figure returned is exact, so the caller rounds once at the boundary it owns.
- `profiles.py` - vendor export profiles held as data in `data/profiles/*.json`, heading normalisation, per-file profile scoring and `detect`. Supporting a payroll system is a JSON file, not code, and correcting a renamed column is a one-line edit.
- `importers.py` - the `payday-super-check import` half: reads payroll and super-payment exports through those profiles and writes the canonical contributions CSV via `atomic_io`. It rejects multiple positive in-scope paydays for one employee until LCR 2026/2 allocation is explicitly reconciled. Confirmed shared payments allocate oldest outstanding covered QE day first; vendor period end has no priority. No vendor export carries a fund receipt date, so every vendor date lands in `remitted` and `fund_received_date` is left blank. The appended `matched_amount` records the contribution amount associated with the payday independently of any vendor payment date: zero for no match, the partial amount for a short match, and the SG liability for a full or over match. It caps a later operator-supplied receipt without presenting the vendor association as receipt proof. Where a profile classifies a vendor status column (`remitted_status`; Employment Hero's Beam ladder), a date reaches `remitted` only when the status shows the payment left the employer: a batch at Created, Submission accepted or Awaiting payment gets no remitted date and the payday reads as unfunded, and a status outside the classified ladder is refused rather than guessed either way. `_amount` quantises an amount as it reads it, through `report.cents`, so the canonical file it writes and the figure the checker reads back are one rounding of the input rather than two.
- `csv_io.py` - column mapping (CLI flags or JSON config), date parsing (ISO + DD/MM/YYYY), and validation with loud errors. Payroll exports vary too much to guess at: a value the parser cannot read is named, never coerced. Explicit amounts must be non-negative and no greater than `sg_amount`; `remitted_amount` also requires `remitted_date` and cannot exceed `matched_amount` where both are supplied. If an eleven-column row supplies a partial `matched_amount` and a `remitted_date`, it must also state `remitted_amount`; otherwise the legacy blank-amount fallback would over-credit the remittance. Ten-column part-payment files remain compatible by falling back from blank `matched_amount` to `remitted_amount`; older files with neither appended amount retain whole-liability receipt semantics. A zone-less time component is dropped (the law tests whole days); a date-time carrying a Z or UTC-offset marker is refused loudly, because its as-written day belongs to that zone and reading it can move a fund receipt one day early against the Australian calendar. `_parse_amount` quantises to cents with `ROUND_HALF_UP`, matching the importer and reporting boundaries.
- `report.py` - console summary + `report.csv` (verdict, due date, pathway, days late and the date it was measured to, shortfall, NEC, uplift range low/high, caveats and notes per line), plus totals across every exposed line. This is the checker's display-rounding boundary: `money`/`cents` quantise to cents with `ROUND_HALF_UP` and `_rounded_figures` builds totals from those displayed parts so a row adds up. LCR 2026/3 footnote 86 confirms only that TAA 1953 s 16B reduces the Commissioner's **final assessed charge** to the nearest multiple of five cents. It does not settle per-line display rounding, so every exposure figure is labelled an experimental estimate and the choice is recorded in the console and trailing CSV note.
- `practitioner_pack.py` - strict consumer of the exact 18-column report contract. It reads and hashes one immutable byte snapshot, validates the terminal provenance row and displayed exposure arithmetic, then produces a deterministic Markdown index and sign-off checklist. The Markdown names source row numbers but omits employee identifiers. Every non-`ON_TIME` row is queued for a human; the module neither changes a checker verdict nor makes a professional decision.
- `atomic_io.py` - generated-output boundary for all three paths: an explicit `.csv` destination for contribution/report files or `.md` for the practitioner pack, staged in that destination's own directory and moved into place with `os.replace`, so an existing symlink at the destination is replaced rather than followed and a failed write leaves no partial file at the chosen name.
- `cli.py` - argparse entry (`payday-super-check pay.csv --map field=column ...`), `--as-at` for the interest end date (default: today), `--assessment-date` for the s 18D cut-off, the explicit LCR 2026/1 transition confirmation, `--confirm-remittance-only` for a file with no fund-receipt dates, the importer's separate LCR 2026/2 allocation confirmation, and `review-pack` for the human-only Markdown handoff. The checker exits non-zero (`report.needs_attention`) for LATE/UNPAID, any attention-driving indeterminate row, or a remittance-only file that has not been confirmed. The pack command exits 2 whenever it queues any non-`ON_TIME` row and 1 for an invalid source or output.

Verdicts:

- `ON_TIME` - received by the due date, or a valid pre-payment inside the 12-month window.
- `LATE` - received or remitted after the due date, or, once the due date has passed, funded only by a pre-payment too old to apply.
- `AT_RISK` - remitted by the due date with no fund-receipt date. The statutory test is receipt, so this is not a pass.
- `UNPAID` - the supported due date has passed and the eligible receipt credit is less than the SG amount, including a partial receipt. Carries the remaining shortfall plus interest.
- `UNKNOWN` - quiet where a supported deadline has not passed or the row carries no SG. Attention-driving where missing holiday facts or unevidenced item 4 facts change the outcome. This includes post-horizon later dates, unfunded rows and stale pre-payments, plus a later row between its evidenced deadline and a possible item 4 upper bound. The console/CSV names conservative outer outcomes; a caveat can retain an intermediate third outcome for a partial receipt. Once the possible item 4 deadline has passed, a partial receipt cannot retain `NOT_YET_DUE`. These rows carry no exposure and drive exit code 2.
- `SKIPPED` - defined-benefit interests, where the contribution is notional (s 18A(3)).

`LATE` and `UNPAID` carry experimental exposure figures. Remittance-based results always carry the assumed-receipt caveat.

Pre-1 Jul 2026 QE days: hard error (old quarterly law, out of scope).

## Data files

- `data/business_days.json` - official-source-complete non-business days from 2026-07-01 through 2027-08-31, plus reference dates after the horizon. Generated by `tools/generate_calendar.py` (dev-time only, python-holidays pinned), checked against all eight official jurisdiction sources and shipped with those URLs/check date. Regional, part-day and locally substitutable dates are excluded, including WA King's Birthday and Melbourne Cup Day. Business Victoria still lists the exact 2027 grand-final holiday as subject to the AFL schedule, so later dates sit beyond the completeness horizon. Unconfirmed future grand-final dates are retained as provisional reference entries and do not extend deadlines.
- `data/gic_rates.json` - dated quarterly GIC annual rates, source URL + seen-date per entry; staleness warning when as-at date beyond last entry's quarter.
- `data/rates.json` - SG rate, MCB, concessional cap per FY, dated.

## Testing

pytest, stdlib `unittest`-free. Anchor cases:
- ATO example: first QE day 9 Jul 2026 -> extended due 7 Aug 2026.
- LCR 2026/3 example: QE day 8 Jun 2027, usual period ends 18 Jun 2027, NEC starts 19 Jun 2027.
- Ekka 12 Aug 2026 counted as business day; WA Day / whole-of-state holidays not.
- Item 4 overlap: a positive, evidenced on-time earlier contribution extends payday 2; a zero-dollar receipt, missing/remittance-only/late evidence does not. Material uncertainty is non-zero `UNKNOWN`, with a partial receipt bounded by `UNPAID` after the possible deadline.
- LCR 2026/2 import gate and earliest-shortfall allocation; vendor period end never wins over an earlier shortfall.
- Out-of-cycle roll-forward + hard rejection where the required subsequent standard QE day is absent.
- LCR 2026/1 transition rejection, explicit confirmation and audit note.
- WA King's Birthday/Melbourne Cup exclusion and provisional-date non-application.
- NEC across a GIC quarter boundary; uplift matrix values.
- MCB warning trigger; pre-1-Jul-2026 error; malformed CSV loud failure.
Synthetic fixtures only; no client data.

## Non-goals / guardrails

Out of scope v1: applying regulations 11 and 12 to raw pay; qualifying-earnings and termination classification while LCR 2026/D1 remains draft; choice loading; maximum-contribution-base application without cumulative earnings; defined-benefit interests (lines flagged and skipped); LPP and post-assessment GIC; old regime calculation; fund-deed/EBA obligations; exceptional-circumstances discovery; and the Commissioner's final assessment rounding. Wording: "low ATO review risk", never "no liability" (PCG 2026/1 para 11). No automated payroll payment, lodgment or accounting decision. Experimental review aid, verify against current ATO material/calculators, no professional advice.
