# Context

This repository is an experimental review aid for Australian payday-super
records. It helps an accountant or employer organise supplied contribution
facts; it does not make a compliance determination, legal conclusion, payment,
lodgment or accounting entry.

## Glossary

- **QE day**: the day qualifying earnings are actually paid. The checker uses
  it as the starting fact for the payday-super deadline.
- **SG amount**: the operator-determined super guarantee amount for a QE day.
  It is not inferred from raw payroll, employee classification or cumulative
  limits.
- **Remittance date**: evidence that an employer sent a contribution. It is not
  evidence that the fund received it.
- **Fund receipt date**: the date the fund received an allocatable
  contribution. The statutory timing test depends on this date.
- **Supported deadline**: the latest contribution deadline established by the
  supplied facts and implemented statutory pathways. A possible but unevidenced
  item 4 extension is not treated as a supported deadline.
- **Attention-driving `UNKNOWN`**: an indeterminate result where missing
  calendar or allocation facts could change the outcome. It requires
  reconciliation and produces a non-zero attention result rather than a pass.
- **Experimental SG-charge estimate**: a displayed, per-line estimate for
  `LATE` and `UNPAID` outcomes. It is not an ATO assessment and excludes
  matters the tool cannot establish.
- **Practitioner review pack**: a deterministic Markdown workpaper derived from
  a validated report snapshot. It omits employee identifiers, queues every
  non-`ON_TIME` row for human review and does not change a verdict.
- **Review-aid boundary**: the tool can calculate, flag, document and preserve
  uncertainty. A suitably authorised human must reconcile evidence, decide
  legal and payroll classifications, and approve any consequential action.

See [`docs/design.md`](docs/design.md) for the implemented statutory pathways,
data model and output behaviour.
