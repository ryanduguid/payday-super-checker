# payday-super-checker

Check Australian super contributions against the payday-super deadlines and estimate the SG charge on anything late.

Since 1 July 2026, super is due within 7 business days of each payday instead of quarterly. Miss it and the SG charge applies automatically: daily-compounding notional earnings, an administrative uplift of up to 60%, and the shortfall itself until the money reaches the fund. This reads a CSV out of your payroll or clearing-house records and tells you, line by line, which contributions landed in time.

Built by Ryan Duguid, a provisional member of Chartered Accountants ANZ working in Australian public practice. Written independently, in his own time and on his own equipment.

## Install

Python 3.10 or later. No runtime dependencies.

```bash
pip install git+https://github.com/ryanduguid/payday-super-checker.git
```

Or clone it and run from the source tree with `python -m paydaysuper.cli`.

## Use

```bash
payday-super-check examples/sample_payrun.csv --as-at 2026-08-10
```

```
payday-super-checker: 10 contribution lines, as at 2026-08-10

  ON_TIME: 5  AT_RISK: 1  LATE: 2  UNKNOWN: 1  SKIPPED: 1

Late lines (largest estimated exposure first):
  row 3  EMP002  QE day 2026-07-09  due 2026-07-20  15 days late
      super $540.00 (received, so the shortfall is nil)  notional earnings $2.54  SG charge estimate $2.54 - $4.07
```

Full detail goes to `report.csv`: due date, which deadline rule applied, days late, the final shortfall after any offset, notional earnings, best and worst case uplift, and every warning that applies to that line.

The exit code is 0 when nothing is late, 2 when something is, and 1 on an error, so you can run it from a scheduled job.

### Options

| Option | What it does |
| --- | --- |
| `-o, --output` | Where to write the report CSV (default `report.csv`) |
| `--as-at DATE` | Measures notional earnings on still-unpaid contributions to this date (default: today) |
| `--assessment-date DATE` | The day the ATO assessed the charge for these paydays. Only contributions received before it clear the shortfall. Omit if no assessment has issued |
| `--map FIELD=COLUMN` | Point one field at your column name; repeatable |
| `--mapping-file FILE` | Same thing as JSON, see `examples/mapping.example.json` |
| `--holidays-override FILE` | Add or remove public holidays from the bundled calendar |

### Input columns

Required: `employee_id`, `payment_date`, `sg_amount`. Everything else is optional but sharpens the answer.

| Field | Column in the sample | Meaning |
| --- | --- | --- |
| `employee_id` | `employee_id` | Anything that identifies the employee consistently |
| `qe_day` | `payment_date` | The day you actually paid the wages, not the period end or payslip date |
| `sg_amount` | `sg_amount` | Super guarantee for that payment |
| `remitted` | `remitted_date` | Day you sent the money |
| `received` | `fund_received_date` | Day the fund received it: the only date that settles compliance |
| `first_to_fund` | `first_contribution_to_fund` | Yes for the first contribution to that fund (new starter, or a fund switch) |
| `out_of_cycle` | `out_of_cycle` | Yes for bonuses, back pay and other payments outside your normal cycle |
| `next_standard_qe_day` | `next_standard_payday` | The next regular payday, needed to date an out-of-cycle deadline |
| `db_interest` | `defined_benefit` | Yes for defined-benefit interests, which are skipped |

Dates read as `YYYY-MM-DD` or day-first `DD/MM/YYYY`. Amounts accept `$` and thousands separators. Anything unreadable stops the run and names the row, and so does a truncated row, a duplicated column heading, or a mapping that points at a column your file does not have. A compliance tool that guesses is worse than one that refuses.

## The rules it applies

All of this is enacted law: the Treasury Laws Amendment (Payday Superannuation) Act 2025 (No. 57 of 2025, assent 6 November 2025), the Superannuation Guarantee Charge Amendment Act 2025 (No. 58 of 2025), and the regulations registered as F2026L00133, which amend the Superannuation Guarantee (Administration) Regulations 2018. It applies to paydays from 1 July 2026. Legal content here was verified on **2 August 2026**; `docs/research-notes-2026-08-02.md` records every source and, just as usefully, the points that rest on secondary commentary because the primary source blocks automated access.

**The deadline.** A contribution is on time only if the fund *receives* it, with enough information to allocate it, by the end of the seventh business day after the payday (SGAA 1992 s 6(1) "usual period", s 18C(1)(c)). Paying a clearing house by the deadline does not count, and the ATO's small business clearing house closed on 30 June 2026, so transit time is now the employer's risk. That is why a line with a remittance date but no fund receipt date comes back `AT_RISK` rather than `ON_TIME`.

**Business days.** SGAA s 6(1) defines a business day as any day that is not a Saturday, a Sunday, or a public holiday for the whole of any State, the ACT or the NT. One national calendar applies to every employer: WA Day stops the clock for a Sydney employer. Regional holidays do not, so the Brisbane Ekka is still a business day even in Brisbane. The bundled calendar covers July 2026 to December 2028.

**20 business days instead of 7** for the first contribution to a particular fund, whether that is a new starter or an existing employee switching funds (s 18C(2) item 1). Later paydays that fall inside that window inherit its end date (item 4), applied per employee.

**Out-of-cycle payments** (bonuses, commissions, back pay) ride the next regular payday's window rather than their own (s 18C(2) item 2, and the Commissioner's determination LI 2026/20). Give the tool `next_standard_payday` or it falls back to the stricter 7-day test. Where both this rule and the new-fund rule apply to the same payment, the later deadline governs.

**When it is late,** notional earnings compound daily at the general interest charge rate from the day after the deadline until the fund receives the money (s 19A), and an administrative uplift of up to 60% applies on top. A late contribution that reaches the fund before the ATO assesses the charge clears the shortfall itself (s 18D), which is why a paid-but-late line shows a small estimate rather than the whole contribution. Pass `--assessment-date` if an assessment has already issued, and the shortfall stays in the figure.

The uplift starts at 60% and falls 20 points for a clean 24-month history, which almost every employer has until 30 June 2028 under the transitional rule, and another 40, 35, 30 or 15 points for a voluntary disclosure lodged within 30, 60, 120 or more than 120 days of the payday. Best case it is nil, worst case 60%. The report shows both ends because the ATO, not this tool, decides which applies.

## What it does not do

- **Choice loading** (25% of contributions paid in breach of choice of fund, capped at $1,200) is not estimated. You cannot see a choice breach in a pay run.
- **The maximum contributions base** ($270,830 a year per employer for 2026-27) is not applied, because it needs each employee's cumulative earnings for the year. Contributions for people earning above it may show a larger shortfall than the law requires.
- **The late payment penalty** and interest on an unpaid assessment sit after assessment and are out of scope.
- **Exceptional circumstances determinations** under s 18C(2) item 3 are not detected. If one covers you, your deadline is later than what you see here.
- **Paydays before 1 July 2026** stop the run. Those are governed by the old quarterly law and this tool does not model it.
- **Fund deeds, enterprise agreements and awards** can require payment earlier than the SG rules. This tool only tests the SG charge.

PCG 2026/1 sets out how the ATO will allocate compliance resources for paydays up to 30 June 2027. Fixing a late contribution quickly lowers the chance of review. It does not remove the liability: the Commissioner has no discretion to waive the charge once a shortfall is known (PCG 2026/1 paragraph 11).

## Keeping it current

Everything that goes stale lives in `paydaysuper/data/`.

- `gic_rates.json` : the general interest charge rate, which the ATO resets every quarter. Each entry records where the figure came from and when that was checked. Update it each quarter or the notional earnings estimate drifts; the tool warns when a calculation runs past the last quarter it knows.
- `rates.json` : SG rate, concessional cap, maximum contributions base, per financial year, with the same source and checked-date fields.
- `business_days.json` : national non-business days, carrying a generation date for the file as a whole rather than per entry. Regenerate with `python tools/generate_calendar.py > paydaysuper/data/business_days.json`, which uses `holidays==0.101` as a development dependency and filters out sub-state holidays, then check every line against the eight state and territory government pages before shipping. Dates for holidays proclaimed annually, such as the Victorian grand final Friday and the WA King's Birthday, are marked provisional and the tool says so when a deadline depends on one.

Two calendar questions have no clear answer in the Act, and the override file exists for both. Part-day holidays, like Christmas Eve evening in South Australia, Queensland and the Northern Territory, are treated here as business days because they are not holidays for the whole of the day. Melbourne Cup Day is treated as a non-business day, though Victorian regional districts can substitute a local holiday for it.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The suite pins the ATO's own worked examples: a first payday of 9 July 2026 falling due 7 August 2026, and notional earnings on a payday whose usual period ends 18 June 2027 starting to accrue on 19 June 2027. It also pins the traps that make this hard, including the Ekka staying a business day, deadlines that must not change when you reorder rows in the CSV, and the leap-year divisor in the interest calculation. Test data is synthetic. Never commit client payroll data to this repository; `.gitignore` blocks the usual formats, case-insensitively.

## Disclaimer

This is an educational tool, not tax, legal or financial advice, and using it creates no professional relationship. The ATO assesses the SG charge; figures here are estimates that exclude components listed above. ATO law companion rulings LCR 2026/D1 to D4 were still in draft when this was written, so interpretations may shift when they are finalised. Check anything material against the ATO's own guidance and calculators, and get advice for your circumstances.

MIT licensed.
