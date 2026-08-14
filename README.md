# payday-super-checker

[![tests](https://github.com/ryanduguid/payday-super-checker/actions/workflows/ci.yml/badge.svg)](https://github.com/ryanduguid/payday-super-checker/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

Check Australian super contributions against the payday-super deadlines and produce an experimental SG-charge estimate for anything late.

Since 1 July 2026, super is due within 7 business days of each payday instead of quarterly. Miss it and the SG charge applies automatically: daily-compounding notional earnings, an administrative uplift of up to 60%, and the shortfall itself until the money reaches the fund. This reads a CSV out of your payroll or clearing-house records and tells you, line by line, which contributions landed in time.

Built by Ryan Duguid, a provisional member of Chartered Accountants ANZ. Written independently, in his own time and on his own equipment.

## Install

Python 3.10 or later. No runtime dependencies.

```bash
git clone https://github.com/ryanduguid/payday-super-checker.git
```

```bash
cd payday-super-checker && pip install .
```

Cloning first means you have the sample file the next command uses. To skip
the clone, `pip install git+https://github.com/ryanduguid/payday-super-checker.git`
installs the tool alone; point it at your own CSV.

## Use

```bash
payday-super-check examples/sample_payrun.csv --as-at 2026-08-10 --confirm-transition-allocation
```

```
payday-super-checker: 10 contribution lines, as at 2026-08-10

  ON_TIME: 5  AT_RISK: 1  LATE: 2  UNPAID: 1  UNKNOWN: 0  SKIPPED: 1

Lines with exposure (experimental estimates, largest first):
  row 5  QE day 2026-07-09  due 2026-07-20  UNPAID, 21 days late to as-at date (nothing applied to this payday)
      shortfall $780.00  notional earnings $5.15  experimental SG charge estimate $785.15 - $1256.24
      note: the deadline passed on 2026-07-20 and no remittance or fund-receipt date is recorded...
  row 3  QE day 2026-07-09  due 2026-07-20  LATE, 15 days late to fund receipt
      super $540.00 (received, so the shortfall is nil)  notional earnings $2.54  SG charge estimate $2.54 - $4.07

  Total across 3 line(s): shortfall $780.00, notional earnings $8.07,
  experimental estimated SG charge $788.07 - $1260.92.
```

The block above is abridged: the real run lists every exposed line and then a page
of assumptions. It deliberately identifies an exposed record by its input row
rather than its employee identifier, so redirected output does not place payroll
identifiers in process logs. Use that row number to find the full record in
`report.csv`.

Full detail goes to `report.csv`: due date, which deadline rule applied, days late, the final shortfall after any offset, notional earnings, best and worst case uplift, and every warning that applies to that line.

The sample contains contributions from the 1–28 July 2026 transition period,
so its command includes `--confirm-transition-allocation`. Do not copy that
flag mechanically. LCR 2026/1 applies those contributions first to any
employee shortfall for the quarter ended 30 June 2026. Use the flag only after
you have reconciled every affected employee; the confirmation is recorded in
the report. Without it the checker stops before writing a verdict.

Verdicts are `ON_TIME`, `AT_RISK` (remitted in time but no fund receipt recorded), `LATE`, `UNPAID` (the deadline has passed and nothing is recorded against it), `UNKNOWN` (the verdict is not available) and `SKIPPED` (defined-benefit interests). `LATE` and `UNPAID` both carry exposure figures.

`UNKNOWN` covers four cases. Three are quiet: nothing recorded and not yet due; a row carrying no SG amount; and a payday whose only recorded receipt falls outside the 12-month pre-payment window of s 18C(1)(c)(ii) while its deadline has not yet arrived, which is unfunded but not yet assessable. The fourth is not. Where the deadline runs past the last date the calendar's holiday table is complete to, and the date on the row is AFTER that deadline, the line could be late or could be on time, because a holiday the calendar does not hold would move the deadline later. Those lines get their own console block naming the row, the amount and both candidate verdicts (employee ids stay in `report.csv`), and the report CSV carries them in `unassessable_between` as `LATE or ON_TIME`. Read that column if you parse the file: the verdict alone says `UNKNOWN` for a nine-thousand-dollar contribution nobody can assess and `UNKNOWN` for a nil row with nothing to assess, with the same blank shortfall on both.

To get a real verdict, enter the missing holidays in a `--holidays-override` file and add `"verified_until": "YYYY-MM-DD"` naming the last date you entered them for. The holidays alone are not enough, and that is deliberate: a file holding one 2029 holiday is not a file that has 2029 covered, and treating it as one would silence the warning across every gap it left. Only you know how far you went.

```json
{
  "verified_until": "2029-12-31",
  "add": [
    {"date": "2029-03-30", "name": "Good Friday", "jurisdictions": ["ALL"]},
    {"date": "2029-04-02", "name": "Easter Monday", "jurisdictions": ["ALL"]}
  ],
  "remove": []
}
```

A date on or before a deadline that runs past the calendar's coverage still gets a verdict. A missing holiday can only push the real deadline later, so paying early is provably on time whatever the calendar is missing.

The exit code is 0 when nothing is exposed and nothing is left undecided, 2 when either is true, and 1 on a data or file error, so you can run it from a scheduled job. Argparse also uses 2 for a bad command line, so a wrapper should check stderr before raising an alarm.

### Options

| Option | What it does |
| --- | --- |
| `-o, --output` | Where to write the report CSV (default `report.csv`) |
| `--as-at DATE` | Measures notional earnings on still-unpaid contributions to this date (default: today) |
| `--assessment-date DATE` | The day the ATO assessed the charge for these paydays. Only contributions received before it clear the shortfall. Omit if no assessment has issued |
| `--map FIELD=COLUMN` | Point one field at your column name; repeatable |
| `--mapping-file FILE` | Same thing as JSON, see `examples/mapping.example.json` |
| `--holidays-override FILE` | Add or remove public holidays from the bundled calendar; its optional `verified_until` declares how far you have entered them |
| `--confirm-transition-allocation` | Confirm you reconciled LCR 2026/1 for every contribution dated no later than 28 July 2026: pre-1 July amounts are unused excess and 1–28 July amounts remain after any June-quarter employee shortfall |

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
| `out_of_cycle` | `out_of_cycle` | Yes only for an allowance, bonus, commission, loading, payment in advance or back payment made outside an established payment timing, pattern or schedule, where the statutory next-standard-payment conditions are met |
| `next_standard_qe_day` | `next_standard_payday` | The next regular payday, needed to date an out-of-cycle deadline |
| `db_interest` | `defined_benefit` | Yes for defined-benefit interests, which are skipped |

Dates read as `YYYY-MM-DD`, day-first `DD/MM/YYYY`, or `9 Jul 2026`, and a time component is ignored. Amounts accept `$` and thousands separators. Anything unreadable stops the run and names up to twenty bad cells at once, and so does a truncated row, a duplicated column heading, or a mapping that points at a column your file does not have. A compliance tool that guesses is worse than one that refuses.

**The amount column must hold super guarantee only.** Salary sacrifice and additional contributions have a different base and a different deadline, so filter them out of the export first or the shortfall will be overstated. The tool does not classify raw pay or decide whether a termination payment is qualifying earnings. LCR 2026/D1 remains draft, so that stays an operator decision.

**Where the fund receipt date comes from.** Payroll exports (Xero, MYOB, KeyPay, Employment Hero) give you the payday and the batch remittance date, which is what `remitted` is for and why those lines come back `AT_RISK`. A fund receipt date lives somewhere else: your clearing house's per-contribution settlement or status report, or the fund's own contribution history. Without it the tool tells you what you sent and when, not what the law tests.

## Import from your payroll system

Two commands turn a payroll export and a super payments export into a checked report, with no column mapping to write by hand:

```bash
payday-super-check import --payroll "Payroll Activity Details.csv" --super "Superannuation Payments.csv" -o contributions.csv
payday-super-check contributions.csv
```

The first command reads both exports, matches each super payment to the payday it settles, and writes the canonical CSV the second command already knows how to check.

Profiles ship for Xero Payroll, MYOB AccountRight, MYOB Business and Employment Hero / KeyPay, one profile each for the payroll-activity report and the super-payments report. The importer picks a profile per file by scoring column headings against what it knows. Force one with `--vendor xero`, `--vendor myob-ar`, `--vendor myob-business` or `--vendor employment-hero` when detection cannot pick, or to skip detection outright.

**Every shipped profile is unverified against a real export.** Each one's column names come from vendor help documentation, and Xero, MYOB and Employment Hero do not publish an actual column list for these reports, so the first real export you try may match no profile at all. When that happens the importer prints the column headings it found in your file next to the headings each candidate profile wanted. Send both lists back and fixing the profile is a one-line edit to its JSON file, not a rewrite.

**No payroll system or clearing house exports a fund receipt date.** Xero's report gives the date a payment was sent to the fund. MYOB gives a Paid Date. Employment Hero gives a Beam status (Sent to fund, Reconciled, and so on). None of these is the date the fund received the money. The legal deadline tests receipt by the fund, and time in transit through a clearing house is the employer's risk, not the fund's, so a vendor date is a remittance date and `fund_received_date` is left blank on every row. Fill that column in from your fund or clearing house before treating any verdict from the checker as final. `remitted_date` carries the vendor date only where every super row behind that payday's match has one; where any of them does not, it is blank, for the reason in the next paragraph.

**Two kinds of payday are written the same as a completely unpaid one.** The canonical CSV has one amount column and one remittance-date column per payday, with no room for "999.99 of 1000.00 arrived" and none for "1000.00 arrived, 600.00 of it on a date anyone recorded".

A part payment is written with `remitted_date` blank, the same as a payday nothing was paid against, so the checker reports the whole 1000.00 as a shortfall. So is a payday matched **in full** where any of the super rows behind the match carries no vendor date: writing the date that covers 600.00 of the 1000.00 would tell the checker the whole payday settled that day, which nothing on record supports.

Both figures survive in the importer's own warning lines, written as `row N: partial: 999.99 of 1000.00 matched` and `row N: 400.00 of 1000.00 matched has no payment date on record; latest known payment date 2026-07-15`. Neither line is ever truncated by the warning cap. Apply them by hand until the canonical format has columns for them.

**A full financial-year export needs trimming first.** The check refuses any file holding a payday before 1 July 2026, because the old quarterly law governs those and this tool does not model it. An export that starts at 1 July 2025 therefore imports fine and then fails the check outright. The import names those rows in a warning and writes them anyway; delete them from the canonical file, or re-export from 1 July 2026, before running the second command.

**A bare filename of `import` does not work.** `payday-super-check import`, run against a file that is genuinely named `import` with no extension, is read as the import subcommand and fails on the missing `--payroll`/`--super` arguments instead of checking the file. `payday-super-check import.csv` and `payday-super-check ./import` both check the file as expected; only the exact bare string `import` is swallowed.

## Local file boundary

This is a single-user command-line tool. Its positional input, importer input, mapping, calendar override and output arguments designate files the invoking operating-system account has chosen to read or write; they are not a sandbox. Do not expose the command as a web endpoint, multi-user service, or automation that accepts path values from a less-trusted caller without adding an appropriate safe-root boundary.

Generated outputs must have an explicit `.csv` filename. They are staged in the selected output directory and atomically replace the selected output name. This means an existing output symlink is replaced rather than followed, and a failed write does not leave a partial report at that name. Both commands still refuse an output path that resolves to any file they read: for the check, the contribution CSV, a `--mapping-file` and a `--holidays-override`; for the import, both exports. The `.csv` rule does not cover this on its own, because a mapping or override file is free to be named `.csv` too.

## The rules it applies

The enacted framework is the Treasury Laws Amendment (Payday Superannuation) Act 2025 (No. 57 of 2025, assent 6 November 2025), the Superannuation Guarantee Charge Amendment Act 2025 (No. 58 of 2025), and the regulations registered as F2026L00133, which amend the Superannuation Guarantee (Administration) Regulations 2018. It applies to paydays from 1 July 2026. A primary-source release review was completed on **15 August 2026**. [The review](docs/primary-source-review-2026-08-15.md) records the exact legislation, final ruling status, holiday authorities, runtime comparison and residual limits. The original 2 August research notes remain as a historical audit trail.

ATO LCR 2026/1, LCR 2026/2 and LCR 2026/3 were issued on 5 August 2026. LCR 2026/D1 remains draft pending the appeal from *Department of Education v Commissioner of Taxation* [2026] FCA 898. The tool therefore accepts an operator-provided SG amount and does not decide qualifying-earnings or termination classifications.

**The deadline.** A contribution is on time only if the fund *receives* it, with enough information to allocate it, by the end of the seventh business day after the payday (SGAA 1992 s 6(1) "usual period", s 18C(1)(c)). Paying a clearing house by the deadline does not count, and the ATO's small business clearing house closed on 30 June 2026, so transit time is now the employer's risk. That is why a line with a remittance date but no fund receipt date comes back `AT_RISK` rather than `ON_TIME`.

**Business days.** SGAA s 6(1) defines a business day as any day that is not a Saturday, a Sunday, or a public holiday for the whole of any State, the ACT or the NT. One national calendar applies to every employer: WA Day stops the clock for a Sydney employer. Regional and locally substitutable holidays do not. The Brisbane Ekka, WA's default King's Birthday date and Melbourne Cup Day are therefore business days for this definition. The bundled calendar is complete from July 2026 through **31 August 2027**. Business Victoria still lists the exact 2027 grand-final holiday as subject to the AFL schedule, so later deadlines fail closed until that date is officially published or supplied through a reviewed override. Unconfirmed dates do not extend a deadline.

**20 business days instead of 7** for the first contribution to a particular fund, whether that is a new starter or an existing employee switching funds (s 18C(2) item 1). Later paydays that fall inside that window inherit its end date (item 4), applied per employee. That alignment is tested only against rows present in the file, so a single pay run checked on its own cannot see an earlier payday's longer window: include each employee's paydays back through any 20-business-day window, or the tool will report lateness the law does not impose.

**Out-of-cycle payments** ride the next regular payday's window rather than their own (SGAA s 18C(2) item 2 and s 18C(3); final determination F2026L00784). The earlier review called this “LI 2026/20”, but that shorthand is not shown on the Federal Register's as-made page; this project uses the controlling registered identifier and text instead. The final determination covers six kinds of qualifying earnings: allowances, bonuses, commissions, loadings, payments in advance and back payments. The employer must have an established timing, pattern or schedule for qualifying-earnings payments, and the payment must fall outside it. It also requires a subsequent, non-out-of-cycle qualifying-earnings payment on the next day consistent with that schedule. A termination or final payment is not out of cycle merely because it belongs to one of the six kinds. `out_of_cycle=yes` without `next_standard_payday` is now a hard error; otherwise the tool would be inventing a condition the final instrument requires. Where both this rule and the new-fund rule apply, the later deadline governs.

**When it is late,** notional earnings compound daily at the general interest charge rate from the day after the deadline until the fund receives the money (s 19A), and an administrative uplift of up to 60% applies on top. A late contribution that reaches the fund before the ATO assesses the charge clears the shortfall itself (s 18D), which is why a paid-but-late line shows a small experimental estimate rather than the whole contribution. Pass `--assessment-date` if an assessment has already issued, and the shortfall stays in the figure.

The uplift starts at 60% and falls 20 points where the clean-history test is met, and another 40, 35, 30 or 15 points according to voluntary-disclosure timing. For QE days through 30 June 2028, the transitional clean-history lookback begins on 1 July 2026 rather than reaching back a full 24 months. The report shows both ends of the range because the ATO, not this tool, decides which reductions apply. Read the low figure carefully: it assumes both a clean history and a voluntary disclosure lodged within 30 days of the payday, so for an old payday with no disclosure already lodged the real floor is higher.

## What it does not do

- **Choice loading** (25% of contributions paid in breach of choice of fund, capped at $1,200) is not estimated. You cannot see a choice breach in a pay run.
- **The maximum contributions base** ($270,830 a year per employer for 2026-27) is not applied, because it needs each employee's cumulative earnings for the year. Contributions for people earning above it may show a larger shortfall than the law requires.
- **The late payment penalty** and interest on an unpaid assessment sit after assessment and are out of scope.
- **Exceptional circumstances determinations** under s 18C(2) item 3 are not detected. If one covers you, your deadline is later than what you see here.
- **Paydays before 1 July 2026** stop the run. Those are governed by the old quarterly law and this tool does not model it.
- **Fund deeds, enterprise agreements and awards** can require payment earlier than the SG rules. This tool only tests the SG charge.
- **Qualifying-earnings and termination classifications** are not decided. LCR 2026/D1 remains draft and the input contains an operator-provided SG amount, not raw pay components.
- **Assessment rounding** is not reproduced. The tool displays report components to cents with `ROUND_HALF_UP`; TAA 1953 s 16B applies a five-cent down-round only to the Commissioner's final assessed SG charge. Exposure figures are experimental estimates.

PCG 2026/1 sets out how the ATO will allocate compliance resources for paydays up to 30 June 2027. Fixing a late contribution quickly lowers the chance of review. It does not remove the liability: the Commissioner has no discretion to waive the charge once a shortfall is known (PCG 2026/1 paragraph 11).

## Keeping it current

Everything that goes stale lives in `paydaysuper/data/`.

- `gic_rates.json` : the general interest charge rate, which the ATO resets every quarter. Each entry records where the figure came from and when that was checked. Update it each quarter or the notional earnings estimate drifts; the tool warns when a calculation runs past the last quarter it knows.
- `rates.json` : SG rate, concessional cap, maximum contributions base, per financial year, with the same source and checked-date fields.
- `business_days.json` : national non-business days plus the eight official jurisdiction URLs and their check date. Regenerate with `python tools/generate_calendar.py > paydaysuper/data/business_days.json`, which uses `holidays==0.102` as a development dependency, then check every line against those official pages before shipping. Raw generator output deliberately sets `verified_until` to 1 July 2026 and `official_sources.checked` to null; a human reviewer must record the check date and raise the horizon only as far as every jurisdiction's official material supports. Regional, part-day and locally substitutable dates are excluded. Unconfirmed dates are reference-only and do not extend a deadline until an official override confirms them.

Part-day holidays, such as Christmas Eve evening in South Australia, Queensland and the Northern Territory, are treated as business days because applying them as a full day would extend the statutory deadline without authority. Melbourne Cup Day and WA's default King's Birthday date are also business days for this definition because the official pages permit regional substitution, so neither applies throughout its State. The override exists for newly proclaimed whole-of-jurisdiction dates and for an operator who has completed a later official calendar.

## Tests

```bash
pip install -e ".[dev]"
```

```bash
pytest
```

The suite pins the ATO's own worked examples: a first payday of 9 July 2026 falling due 7 August 2026, and notional earnings on a payday whose usual period ends 18 June 2027 starting to accrue on 19 June 2027. It also pins the traps that make this hard, including the Ekka staying a business day, deadlines that must not change when you reorder rows in the CSV, and the leap-year divisor in the interest calculation. Test data is synthetic. Never commit client payroll data to this repository; `.gitignore` blocks the usual formats, case-insensitively.

## Disclaimer

This is an educational tool, not tax, legal or financial advice, and using it creates no professional relationship. The ATO assesses the SG charge; figures here are experimental estimates that exclude components listed above. LCR 2026/1–3 are final, while LCR 2026/D1 remains draft and may change after the pending appeal. Check anything material against current ATO guidance and calculators, and get advice for your circumstances.

MIT licensed.
