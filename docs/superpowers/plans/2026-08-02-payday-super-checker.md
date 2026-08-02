# payday-super-checker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CLI that computes payday-super deadlines from a contribution CSV, gives on-time/late verdicts, and estimates SG-charge exposure for late lines.

**Architecture:** Pure-function core (`calendar` → `deadlines` → `sgc`) fed by `csv_io`, surfaced by `report`/`cli`. All legal constants live in dated JSON data files, never in code. Money in `Decimal` cents.

**Tech Stack:** Python ≥3.10, stdlib-only runtime, pytest dev-only, python-holidays pinned dev-only (calendar generator).

## Global Constraints

- Stdlib-only at runtime; `pyproject.toml` declares zero dependencies.
- All money as `Decimal`; quantize to cents only at display, `ROUND_HALF_UP`, stated as assumption (no statutory rounding rule verified).
- QE day < 2026-07-01 → hard error (old quarterly law).
- Every legal number sourced from `data/*.json` with `source` + `seen` fields.
- Output wording: "low ATO review risk", never "no liability"; remittance-based verdicts always carry assumed-receipt caveat.
- Synthetic data only; `.gitignore` blocks real pay data (`*.aba`, `pay*.csv` outside `tests/fixtures/` and `examples/`).
- No AI attribution in commits; Conventional Commits.

---

### Task 1: Calendar data + generator

**Files:** Create `tools/generate_calendar.py`, `data/business_days.json`.
**Produces:** JSON schema `{"verified_from": "2026-07-01", "verified_until": "2028-12-31", "non_business_days": [{"date": "2026-08-03", "name": "...", "jurisdictions": ["NSW"], "provisional": false}]}` (weekends NOT included — computed).

- [ ] Generator: venv-install `holidays` (pinned), union PUBLIC-category holidays for ACT/NSW/NT/QLD/SA/TAS/VIC/WA, years 2026-2028; drop `The Royal Queensland Show` (Brisbane-area only — NOT whole-of-state, SGAA s 6(1)); print any name not in a reviewed allowlist for manual curation; mark provisional: VIC Grand Final Friday (rule-derived), WA King's Birthday 2027+ (proclaimed annually).
- [ ] Run, hand-review output list line-by-line, write JSON. Commit.

### Task 2: `paydaysuper/calendar.py`

**Test:** `tests/test_calendar.py`.
**Produces:** `load_calendar(override_path: str|None) -> BusinessCalendar`; `BusinessCalendar.is_business_day(d: date) -> bool`; `.add_business_days(d: date, n: int) -> date` (returns the n-th business day after d, d itself never counted); `.provisional_hits(a: date, b: date) -> list[str]`; `.check_horizon(d: date) -> str|None`.

- [ ] Failing tests: Sat/Sun false; 2026-08-03 (NSW Bank Holiday? — no: BANK category, business day) TRUE; WA Day 2027-06-07 false nationally; Ekka 2026-08-12 TRUE; `add_business_days(date(2026,7,9), 20) == date(2026,8,7)` (ATO worked example, adjust to bundled calendar); horizon warning past 2028-12-31; override file adds/removes a date.
- [ ] Implement; tests pass; commit.

### Task 3: Rates data + loader

**Files:** `data/gic_rates.json` (`[{"from": "2026-07-01", "to": "2026-09-30", "annual_pct": "11.43", "source": "...", "seen": "2026-08-02"}]`, plus Apr-Jun 2026 10.96 for completeness), `data/rates.json` (sg_rate 12, mcb 270830, cap 32500 for FY2026-27), `paydaysuper/rates.py`.
**Produces:** `GicTable.daily_rate(d: date) -> Decimal` (annual/365, exact Decimal); `GicTable.staleness(d) -> str|None`; `load_rates()`.

- [ ] Failing tests: daily rate for 2026-08-15 == Decimal("11.43")/100/365; date past table → staleness message; commit.

### Task 4: `paydaysuper/deadlines.py`

**Test:** `tests/test_deadlines.py`.
**Consumes:** `BusinessCalendar`.
**Produces:** `ContribLine` dataclass (employee_id, qe_day, sg_cents, remitted, received, first_to_fund, out_of_cycle, next_standard_qe_day, db_interest); `compute_due(line, cal) -> Deadline(due, pathway, notes)`; `apply_item4(lines_with_deadlines) -> None` (per-employee, mutates due to max(own, earlier extended latest-due)); pathways: `USUAL_7BD`, `EXTENDED_20BD`, `OUT_OF_CYCLE`, `ITEM4_ALIGNED`.

- [ ] Failing tests: plain 7BD; first_to_fund → 20BD (9 Jul 2026 → 7 Aug 2026); out_of_cycle with next_standard_qe_day → that day's usual period end; out_of_cycle without → own 7BD + note; payday 2 during employee's 20BD window inherits later end (item 4); qe_day 2026-06-30 → `PreRegimeError`; db_interest → `SKIP_DB` pathway.
- [ ] Implement; pass; commit.

### Task 5: `paydaysuper/sgc.py`

**Test:** `tests/test_sgc.py`.
**Consumes:** `GicTable`.
**Produces:** `notional_earnings(shortfall: Decimal, due: date, as_at: date, gic: GicTable) -> Decimal` — accrues for each day d in [due+1 .. as_at], NEC += (shortfall + NEC) * daily_rate(d), i.e. daily compounding on base shortfall + accrued NEC (SGAA s 19A; starts day AFTER deadline per LCR 2026/D3 example); `uplift_scenarios(final_shortfall: Decimal, nec: Decimal) -> dict[str, Decimal]` with keys `vds_30d/vds_60d/vds_120d/vds_late/no_vds` × clean-history assumption (transitional reg 13C(3): clean = default), pcts clean {0,5,10,25,40}, prior-history row {20,25,30,45,60} included in output for completeness.

- [ ] Failing tests: due 2027-06-18 → accrual starts 2027-06-19 (LCR 2026/D3); 0 days late → NEC 0; single-day NEC == shortfall*rate; 92-day accrual crossing 30 Sep boundary uses two rates (construct expected by loop in test with independent arithmetic); uplift matrix exact pcts; all-Decimal (no float drift assert type).
- [ ] Implement; pass; commit.

### Task 6: `paydaysuper/csv_io.py`

**Test:** `tests/test_csv_io.py` + `tests/fixtures/sample_payrun.csv` (synthetic, ~10 lines covering every pathway).
**Produces:** `parse_rows(path, mapping: dict[str,str]) -> list[ContribLine]`; mapping keys = canonical names, values = CSV headers; dates ISO `YYYY-MM-DD` or `DD/MM/YYYY` (never US); amounts as dollars decimal in CSV → Decimal cents; loud `CsvError` with row number on: missing column, unparseable date/amount, negative amount, empty required field. No silent coercion, no zero-defaults.

- [ ] Failing tests: happy path; each error case raises with row number; `31/02/2026` rejected; commit.

### Task 7: `paydaysuper/report.py` + `paydaysuper/cli.py` + integration

**Test:** `tests/test_integration.py` (run CLI main() on fixture, assert report.csv rows + exit code).
**Produces:** verdicts `ON_TIME` (received ≤ due), `LATE`, `AT_RISK` (remitted ≤ due, no received date), `UNKNOWN`; report.csv columns: employee_id, qe_day, pathway, due_date, verdict, days_late, shortfall, nec, uplift_low, uplift_high, sgc_low, sgc_high, warnings. Console: summary counts, worst exposures, global caveats (fund-receipt assumption, provisional-date warning, GIC staleness, MCB note when cumulative QE data absent, PCG 2026/1 wording). `--as-at`, `--map k=v` repeatable, `--mapping-file`, `--holidays-override`, exit 2 when LATE, 1 on error, 0 clean.

- [ ] Failing integration test; implement; pass; commit.

### Task 8: Packaging + docs

**Files:** `pyproject.toml` (name payday-super-checker, requires-python >=3.10, zero deps, console script `payday-super-check`), `README.md`, `LICENSE` (MIT, Ryan Duguid), `.gitignore`, `examples/mapping.example.json`.

- [ ] README: what/why, 60-second usage, CSV schema table, the law in plain words WITH citations + date-stamp + draft-guidance caveats, exposure-estimate assumptions, out-of-scope list, disclaimer block, calendar maintenance note. Run full pytest; commit.

## Self-review notes

Spec coverage: all spec sections mapped to tasks 1-8. MCB: warning-only (report.py global caveat) per spec — no per-employee tracker in v1 (needs cumulative data the CSV won't reliably carry); README documents. Type consistency: `ContribLine`/`Deadline`/`BusinessCalendar`/`GicTable` names fixed above.
