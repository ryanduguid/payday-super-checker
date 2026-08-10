# payday-super-checker: design

Design as implemented. Legal content researched 2 August 2026; see
`research-notes-2026-08-02.md` for the sources behind every figure.

## Purpose

CLI that reads a pay-run/contribution CSV and, for each super contribution line, computes the statutory payday-super deadline, gives an on-time/late verdict, and estimates SG charge exposure for late lines. Audience: Australian accountants and employers. Not a payroll system, not legal advice.

## Legal basis (researched 2026-08-02, adversarially cross-checked)

The rules below were researched against primary sources and then re-checked by an independent verification pass. Most were read from the Act, the regulations or PCG 2026/1 directly. Some rest on secondary commentary because ato.gov.au and the ATO legal database block automated fetching: the GIC rate, the maximum contributions base, the text of LI 2026/20, and the finalisation status of LCR 2026/D1 to D4. Those need a browser check before release. Full citations, confidence ratings and open ambiguities in `docs/research-notes-2026-08-02.md`.

- Treasury Laws Amendment (Payday Superannuation) Act 2025 (No. 57 of 2025), assent 6 Nov 2025; SGC Amendment Act 2025 (No. 58 of 2025); Payday Superannuation Regulations 2026 (F2026L00133). Applies to QE days from 1 Jul 2026.
- Deadline: contribution must be **received by the fund** (and allocatable) by end of the 7th business day after the QE day (SGAA s 6(1) "usual period", s 18C(1)(c)(i)). QE day = day earnings actually paid (s 17A(1)). Pre-payments within prior 12 months also count (s 18C(1)(c)(ii)).
- Business day (s 6(1)): not Sat/Sun, not a public holiday applying to the **whole of any** State/ACT/NT. One national calendar. Regional holidays (e.g. Royal Queensland Show) are business days.
- Extended deadline, 20 business days (s 18C(2) item 1): first eligible contribution to a particular fund (new/recommenced employee, or fund switch). Item 4: later QE days inside an earlier extended window inherit its end date (deadline = max of own usual period end, earlier latest due day).
- Out-of-cycle QE (s 18C(2) item 2, LI 2026/20): deadline = end of the usual period of the first later standard QE day; fallback to own 7-business-day period when none exists.
- Exceptional circumstances (s 18C(2) item 3): supported via config flag only, not auto-detected.
- SGC on lateness (s 16B(2)): final shortfall + notional earnings component + administrative uplift (+ choice loading, out of scope). NEC: daily compounding at GIC rate on base shortfall, from the day **after** the last on-time day, until final shortfall nil or day before assessment (s 19A; LCR 2026/D3 example). Uplift: 60% of (shortfalls + NEC), reduced 20pp clean-history (reg 13C, transitional lookback from 1 Jul 2026) and 40/35/30/15pp by voluntary-disclosure timing (reg 13D). Floor 0%.
- SG rate 12% (s 17A(2)). MCB annual, $270,830 for 2026-27 (s 10A(5)-(6)) - warning only, needs cumulative FY data.
- GIC 11.43% p.a. for Jul-Sep 2026; quarterly reset -> dated rate table. Daily rate = the quarter's annual rate divided by the number of days in the **calendar year of that day** (TAA 1953 s 8AAD): 365 in 2026 and 2027, 366 in 2028. Not a fixed /365.

## Architecture

`paydaysuper/` package, Python >=3.10, **stdlib-only runtime**. Units:

- `calendar.py` - loads bundled `paydaysuper/data/business_days.json` (+ optional user override JSON), `is_business_day(date)`, `add_business_days(date, n)`, horizon warning when computation leaves the range the table covers. `coverage_until` is that range's end: the bundled `verified_until`, raised only by an override's own `verified_until`, so a user who enters the missing years and says how far they went gets real verdicts. Holding a holiday is not evidence of completeness and never raises it - inferring coverage from the latest date present let one added Christmas silence the warning for the whole preceding year. Past the coverage end the table may be missing holidays and a deadline computed across it can only be too early, which decides one side and not the other: a date on or before that deadline is provably on time, and only a date after it is left `UNKNOWN`.
- `deadlines.py` - pure functions implementing the four s 18C pathways; input = line facts, output = `Deadline(due, pathway, notes, caveats)`, where notes explain which rule applied and caveats mean the answer itself may be wrong. Item 4 alignment is applied per employee after per-line computation, and calendar caveats are attached after that so they describe the final date.
- `sgc.py` - pure functions: `notional_earnings(shortfall, due, end, gic)` compounding daily GIC over `[due + 1 day, end]` inclusive, across quarter boundaries in the `GicTable` loaded from `paydaysuper/data/gic_rates.json`; `uplift_scenarios(...)` returning the reg 13C/13D matrix. Money is `Decimal` dollars everywhere - never floats, never integer cents. Accrual runs at full `Decimal` precision and is rounded to cents only at a boundary, `ROUND_HALF_UP` at each: `importers._amount` quantises an amount as it reads it (through `report.cents`, so the canonical file it writes and the figure the checker reads back are one rounding of the input rather than two), and `report.money`/`report.cents` quantise on the way out, where `_rounded_figures` rounds each component once and builds the totals from the rounded parts so a row's columns add up. `csv_io._parse_amount` does not round: a checker input keeps the scale it arrived with.
- `csv_io.py` - column mapping (CLI flags or JSON config), date parsing (ISO + DD/MM/YYYY), validation with loud errors. Payroll exports vary too much to guess at: a value the parser cannot read is named, never coerced.
- `report.py` - console summary + `report.csv` (verdict, due date, pathway, days late and the date it was measured to, shortfall, NEC, uplift range low/high, caveats and notes per line), plus totals across every exposed line.
- `cli.py` - argparse entry (`payday-super-check pay.csv --map field=column ...`), `--as-at` for the interest end date (default: today) and `--assessment-date` for the s 18D cut-off, exits non-zero (`report.needs_attention`) when LATE or UNPAID lines exist **or** when any line was left horizon-indeterminate `UNKNOWN`, which the verdict list below explains (scheduling-friendly).

Verdicts:

- `ON_TIME` - received by the due date, or a valid pre-payment inside the 12-month window.
- `LATE` - received or remitted after the due date, or funded only by a pre-payment too old to apply.
- `AT_RISK` - remitted by the due date with no fund-receipt date. The statutory test is receipt, so this is not a pass.
- `UNPAID` - the due date has passed and nothing at all is recorded. Carries the full shortfall plus interest.
- `UNKNOWN` - three ways in. Two mean nothing to assess: nothing recorded and not yet due, and a row carrying no SG amount, so no dates on it can put anything at risk. The third means the opposite. The deadline runs past the calendar's coverage AND the date on the row is after it, so the line is late on this calendar and could be on time on the real one. That case names both candidate verdicts in its own console block and drives the same non-zero exit code `LATE` does, because a run that cannot tell whether a shortfall exists has not found nothing.
- `SKIPPED` - defined-benefit interests, where the contribution is notional (s 18A(3)).

`LATE` and `UNPAID` carry exposure figures. Remittance-based results always carry the assumed-receipt caveat.

Pre-1 Jul 2026 QE days: hard error (old quarterly law, out of scope).

## Data files

- `data/business_days.json` - non-business days 2026-07-01 -> 2028-12-31: national union of whole-of-jurisdiction holidays. Generated by `tools/generate_calendar.py` (dev-time only, python-holidays pinned, PUBLIC category, Ekka and other sub-state entries filtered), then hand-curated. Each entry: date, name, jurisdictions, `provisional: true` for rule-derived unproclaimed dates (VIC Grand Final Friday, WA King's Birthday futures). CLI warns when a deadline depends on a provisional date. Part-day holidays counted as business days (documented ambiguity, override file available). Melbourne Cup: non-business day by default, documented caveat.
- `data/gic_rates.json` - dated quarterly GIC annual rates, source URL + seen-date per entry; staleness warning when as-at date beyond last entry's quarter.
- `data/rates.json` - SG rate, MCB, concessional cap per FY, dated.

## Testing

pytest, stdlib `unittest`-free. Anchor cases:
- ATO example: first QE day 9 Jul 2026 -> extended due 7 Aug 2026.
- LCR 2026/D3 example: QE day 8 Jun 2027, usual period ends 18 Jun 2027, NEC starts 19 Jun 2027.
- Ekka 12 Aug 2026 counted as business day; WA Day / whole-of-state holidays not.
- Item 4 overlap: payday 2 inside a 20-day window inherits its end.
- Out-of-cycle roll-forward + no-later-standard-QE-day fallback.
- NEC across a GIC quarter boundary; uplift matrix values.
- MCB warning trigger; pre-1-Jul-2026 error; malformed CSV loud failure.
Synthetic fixtures only; no client data.

## Non-goals / guardrails

Out of scope v1: choice loading (user-visible note), defined-benefit interests (lines flagged and skipped), LPP (mentioned in README as post-assessment risk), old regime, fund-deed/EBA obligations (PCG 2026/1 para 3 note). Wording: "low ATO review risk", never "no liability" (PCG 2026/1 para 11). README date-stamps legal content, cites LCR drafts as drafts, states the fund-receipt assumption prominently. Disclaimer: educational tool, verify against ATO calculators, no professional advice.
