# Payroll export importers

Design, 3 August 2026.

## Why

Today the tool reads one CSV whose columns you either name in `mapping.json` or match by hand. Every user starts by translating their payroll export into a shape the tool accepts. That translation is the barrier to using it at all.

An importer removes the translation. You point it at the two reports your payroll system already produces and it writes the contributions CSV for you.

## What the vendors actually give you

Verified 3 August 2026 against vendor documentation. None of the three publish a full column list, so the column names below are candidates, not confirmed headers.

| Vendor | Report | Fields named in the docs |
| --- | --- | --- |
| Xero Payroll | Payroll Activity Details | none published; docs say only "all columns appear by default" |
| Xero Payroll | Superannuation Payments | super payment date set within the pay run; for automatic super, the date the payment was sent to the fund, plus the transaction reference; groups by Employee or **Contribution Type**, so a contribution-type column exists |
| MYOB AccountRight | Superannuation Payments by Employee | Employee Name, Superannuation Category, Employee Membership #, Period From, Period To, Paid Date, Amount |
| MYOB AccountRight | Payroll Activity [Detail] | none published |
| Employment Hero / KeyPay | Super Contributions | payments CSV carries a Status column at the far right; accruals CSV carries Batch id; filters run on employee name, employee Id, external Id and payroll Id |

Two consequences follow.

**No vendor exports a fund receipt date.** MYOB gives "Paid Date". Xero gives the date the payment was sent to the fund. Employment Hero runs a Beam status ladder: Created, Submission accepted, Awaiting payment, Awaiting clearance, Sent to fund, Reconciled. The deadline in s 18C tests receipt by the fund, and clearing-house transit is the employer's risk. So a vendor date is a remittance date and nothing more.

**Column names ship unverified.** Each profile carries `"verified": false` until someone runs it against a real export. The importer prints that status on every run.

## Scope

In scope: reading a payroll export and a super payments export, joining them, writing the canonical contributions CSV, and reporting what did not join.

Out of scope: clearing-house confirmation files, API integrations, and any change to the deadline or charge calculation.

## Architecture

The importer is a front end that writes the existing canonical CSV. It does not touch `csv_io.py`, `deadlines.py`, `sgc.py` or `report.py`, so the audited calculation path stays as it is. The CSV it writes is also the workpaper: an accountant can read it, correct a receipt date, and run the check on the corrected file.

```
payroll export ─┐
                ├─> importers.py ─> contributions.csv ─> existing check path
super export   ─┘        │
                    profiles.py
                         │
                 data/profiles/*.json
```

### paydaysuper/profiles.py

Loads and validates profile JSON, and scores a header row against every profile of a given role.

```python
@dataclass(frozen=True)
class Profile:
    key: str            # "xero-super"
    name: str           # "Xero Payroll - Superannuation Payments"
    role: str           # "payroll" or "super"
    verified: bool
    signature: list[str]        # headers that must be present
    columns: dict[str, list[str]]   # canonical field -> accepted headings
    date_formats: list[str]
    sg_filter: SgFilter | None
    notes: str
```

Header normalisation strips whitespace including NBSP, casefolds, collapses internal runs of space, and drops punctuation. `Employee Membership #` and `employee membership` normalise to the same key.

Scoring counts how many of a profile's signature headers appear, then how many of its column synonyms appear. A profile wins only when it has every signature header and a strictly higher total than the runner-up. A tie or a zero score raises, and the message lists each candidate with the headers it wanted and did not find. `--vendor xero` skips detection.

A profile whose JSON is malformed, whose role is unknown, or whose `columns` name a canonical field the importer does not know raises at load time rather than at match time.

### paydaysuper/importers.py

Reads both files through their profiles, filters to super guarantee, joins, and emits rows.

**Super guarantee only.** The existing error text already tells users the amount column must hold super guarantee alone, not salary sacrifice or additional contributions. The importer enforces that: it filters the super export on the contribution-type column using the profile's include list. When the export has no contribution-type column, the importer refuses. Summing every contribution type would overstate the SG figure and understate the shortfall, and a silent overstatement is worse than a stop.

**Employee key.** An id column wins where both files have one. Falling back to employee name emits a warning naming the fallback, because two employees can share a name and a name can change mid-year. Name keys normalise the same way headers do.

**Period match.** A super row matches a payroll row when the super row's Period From to Period To brackets the payroll row's pay period end. Where a payroll export gives no period end, the payday stands in for it.

**Remittance date.** Where several super rows match one payroll row, `remitted` takes the latest paid date among them. A contribution split across two payments is not complete until the last part goes, so the earliest date would flatter the result.

**Amount reconciliation.** Matched super amounts are summed and compared to the payroll SG amount to the cent.

| Case | Emitted | Flag |
| --- | --- | --- |
| sum equals payroll SG | `remitted` set | none |
| sum is short | `remitted` set | `partial: $X of $Y matched` |
| sum exceeds payroll SG | `remitted` set | `over: $X against $Y, check for salary sacrifice` |
| no super row matches | `remitted` blank | `no super payment found` |
| super row matches nothing | not emitted | `orphan super payment` |

**Ambiguity stops the run.** Two payroll rows for one employee with overlapping periods and equal amounts cannot be assigned to super rows without guessing, so the importer refuses and names the rows. Guessing here would move a real exposure onto the wrong payday and change its deadline.

### Canonical output

The nine existing columns: `employee_id`, `payment_date`, `sg_amount`, `remitted_date`, `fund_received_date`, `first_contribution_to_fund`, `out_of_cycle`, `next_standard_payday`, `defined_benefit`.

`fund_received_date` is always blank. The importer cannot know it. The report already handles an unknown receipt, and the run prints one line saying so.

`first_contribution_to_fund`, `out_of_cycle`, `next_standard_payday` and `defined_benefit` are also blank. No vendor export carries them, and inventing a value would silently change a deadline.

Every written field passes through `csv_safe` from `report.py:55`. That guard fires on `=` always and on `+`, `-` or `@` only when the rest of the field is not alphanumeric, so an employee code such as `-00123` survives intact and still joins back to payroll.

### CLI

```
payday-super-check import --payroll PAYROLL.csv --super SUPER.csv -o contributions.csv
                          [--vendor auto|xero|myob-accountright|myob-business|employment-hero]
                          [--match-report matches.csv]
```

`sys.argv[1] == "import"` dispatches to the import parser. Every existing invocation keeps working unchanged.

Exit codes: 0 for a clean import, 2 when rows are partial, unmatched or orphaned, 1 for an error. The 2 mirrors the existing "something needs your attention" code so a scheduled run can branch on it.

Reading uses `utf-8-sig` and raises the existing code-page message on a decode failure. Dates parse day-first through the profile's format list, falling back to `parse_date_text` from `csv_io.py`.

Errors raise `CsvError`. No new exception subclass: `CsvError` already subclasses `ValueError`, and adding another layer invites the swallowing bug this repo has already hit once.

### Profile files

`paydaysuper/data/profiles/*.json`, shipped as package data so `pip install .` carries them.

```json
{
  "key": "myob-ar-super",
  "name": "MYOB AccountRight - Superannuation Payments by Employee",
  "role": "super",
  "verified": false,
  "signature": ["Employee Name", "Paid Date", "Amount"],
  "columns": {
    "employee_name": ["Employee Name", "Employee", "Name"],
    "employee_id": ["Card ID", "Employee ID"],
    "period_start": ["Period From"],
    "period_end": ["Period To"],
    "paid_date": ["Paid Date"],
    "amount": ["Amount"],
    "contribution_type": ["Superannuation Category"]
  },
  "date_formats": ["%d/%m/%Y", "%d/%m/%y"],
  "sg_filter": {
    "column": "contribution_type",
    "include": ["Superannuation Guarantee", "SGC", "SG"]
  },
  "notes": "Column names come from MYOB help text, not a real export. Paid Date is when MYOB recorded the payment, not when the fund received it."
}
```

Eight files ship: payroll and super for Xero, MYOB AccountRight, MYOB Business and Employment Hero. Adding Reckon or QuickBooks later means writing a ninth file, not changing code.

## Testing

Fixtures are synthetic and labelled as such in the file header. No client data.

Detection: each profile wins against its own fixture; a header set matching two profiles equally raises and names both; an unrecognised header set raises and lists what each candidate wanted; `--vendor` overrides a wrong detection.

Join: exact match; contribution split across two payments taking the later date; short payment flagged partial; payroll row with no super payment flagged and left blank; orphan super row reported; overlapping equal-amount rows refused.

Filtering: a salary sacrifice row is excluded from the SG total; a super export without a contribution-type column is refused.

Parsing: `09/07/2026` reads as 9 July; a BOM, CRLF line endings and an NBSP inside an employee name all survive; a cp1252 file raises the existing re-save message.

Output: `=cmd()` in an employee name is guarded; `-00123` is not mangled; every emitted row survives a round trip through the normal check and produces the expected verdict.

Each regression test is proved to fail against the code as it stands before the change. A test that passes both ways is testing nothing, which this repo has already been caught by once.

## Risks

The column names are unverified, so the first real export may match nothing. The refusal message is therefore part of the deliverable: it prints the headers found, the profile that came closest, and the exact headings that profile wanted.

A vendor can rename a report column in any release. Profiles being data rather than code means a rename is a one-line fix in JSON.

Employment Hero renames its OTE report to OTE/QE and adds a QE column for pay runs paid on or after 1 July 2026. Where a payroll export carries both, the profile prefers the QE column, because qualifying earnings replace ordinary time earnings as the SG base under the new regime.
