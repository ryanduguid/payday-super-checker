# Payday Super evidence boundary evaluation

## Accounting problem

This evaluation isolates the difference between an employer's operational
remittance evidence and evidence that an eligible contribution reached the
fund. Four fabricated rows hold the QE day, SG amount and as-at date constant
while changing the remittance and fund-receipt facts. The production checker
calculates a supported due date of 17 August 2026 for each row.

## Intended reviewer

This pack is for an accountant, payroll reviewer or assurance reviewer who can
reconcile the supplied records and decide the facts that the checker cannot.
It demonstrates the evidence boundary; it does not replace professional
judgement or an ATO assessment.

## Fabricated inputs

Every fixture uses synthetic employee identifier `SYN001`, QE day 6 August
2026 and operator-supplied SG amount `$120.00`.

| Fixture | Evidence varied |
| --- | --- |
| `timely_remittance_no_receipt.csv` | Remitted 14 August; no fund receipt recorded |
| `late_remittance_no_receipt.csv` | Remitted 18 August; no fund receipt recorded |
| `receipt_on_due_date.csv` | Remitted 14 August; fund receipt recorded on 17 August |
| `receipt_after_due_date.csv` | Remitted 14 August; fund receipt recorded on 18 August |

No client, employee or live payroll data is included.

## Reproduce the result

Run these commands from the repository root. Exit code 2 is the expected
attention result for the `AT_RISK` and `LATE` scenarios.

```bash
uv run --locked --extra dev --python 3.12 payday-super-check evaluation/payday_super_evidence/fixtures/timely_remittance_no_receipt.csv --as-at 2026-08-20 -o timely-report.csv
uv run --locked --extra dev --python 3.12 payday-super-check evaluation/payday_super_evidence/fixtures/late_remittance_no_receipt.csv --as-at 2026-08-20 -o late-remittance-report.csv
uv run --locked --extra dev --python 3.12 payday-super-check evaluation/payday_super_evidence/fixtures/receipt_on_due_date.csv --as-at 2026-08-20 -o on-time-report.csv
uv run --locked --extra dev --python 3.12 payday-super-check evaluation/payday_super_evidence/fixtures/receipt_after_due_date.csv --as-at 2026-08-20 -o late-receipt-report.csv
uv run --locked --extra dev --python 3.12 pytest tests/test_evaluation_pack.py -q
```

The generated CSV reports include the contribution row followed by the
checker's terminal `NOTE` provenance row. The machine-readable expectations
are in [`expected_results.json`](expected_results.json).

## Expected result

All four rows have the supported due date 17 August 2026.

- Timely remittance with no receipt remains `AT_RISK` and cannot prove on-time.
- Remittance after the due date can establish lateness even without a receipt,
  so the result is `LATE`.
- Eligible receipt on the due date can produce `ON_TIME` for the supplied facts.
- Receipt after the due date produces `LATE`.

## Controls and refusal boundary

The commands call the production CLI against only the four declared fabricated
fixtures. The repository's CSV deny rule remains in force, with exact
allow-list entries for these files and no wildcard evaluation exception.
Remittance is not substituted for fund receipt. An `AT_RISK` or `LATE` result
drives exit code 2, and no result authorises payment, lodgment, disclosure,
accounting entry or a compliance conclusion.

## Primary sources and review date

The source position was reviewed on 15 August 2026 against the
[Superannuation Guarantee (Administration) Act 1992](https://www.legislation.gov.au/C2004A04402/latest/text)
on the Federal Register of Legislation and the ATO's
[LCR 2026/2 eligible contributions](https://www.ato.gov.au/law/view/document?DocID=COG%2FLCR20262%2FNAT%2FATO%2F00001).
The repository's [primary-source implementation review](../../docs/primary-source-review-2026-08-15.md)
records the wider source trail and residual limits.

## Product and fixture version

`v0.1.2` is the latest published product prerelease. That release tag does not
contain this new evaluation directory. After this pull request is merged, the
evaluation will be protected by the permanent link to its merge commit. The
fixture version is `1`, and the results use an as-at date of 20 August 2026.

## Human decision

Remittance evidence can show operational timing but cannot prove on-time; a human must establish eligible fund receipt, allocation and the other assessment facts before relying on a statutory conclusion.

## Limitations and non-claims

These four rows do not establish fund eligibility, statutory allocation,
qualifying-earnings classification, assessments or final ATO amounts. They do
not test transition allocation, item 4 extensions, out-of-cycle payments,
exceptional-circumstances determinations, maximum-contribution-base limits or
fund-deed, award and enterprise-agreement obligations. The checker and its
monetary output remain experimental review aids, not tax, legal or financial
advice, an ATO assessment or a compliance determination.
