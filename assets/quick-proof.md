# Fabricated Payday Super review

Command:

```bash
payday-super-check examples/sample_payrun_no_transition.csv --as-at 2026-09-10
```

Exit code: 2, review required.

```text
payday-super-checker: 7 contribution lines, as at 2026-09-10

  ON_TIME: 3  AT_RISK: 1  LATE: 1  UNPAID: 1  UNKNOWN: 0  SKIPPED: 1

Lines with exposure (experimental estimates, largest first):
  row 5  QE day 2026-08-06  due 2026-08-17  UNPAID, 24 days late to as-at date (nothing applied to this payday)
      shortfall $780.00  notional earnings $5.88  experimental SG charge estimate $785.88 - $1257.41
      note: the deadline passed on 2026-08-17 and no remittance or fund-receipt date is recorded. Figures assume the contribution is still unpaid; if your export has no date columns, supply them before relying on this
  row 3  QE day 2026-08-06  due 2026-08-17  LATE, 17 days late to fund receipt
      super $540.00 (received, so the shortfall is nil)  notional earnings $2.88  experimental SG charge estimate $2.88 - $4.61
      note: this assumes the contribution is not the first to this fund. If it is a new starter or a fund switch, set first_contribution_to_fund=yes and the line becomes on time (due 2026-09-03)

  Total across 2 line(s): shortfall $780.00, notional earnings $8.76,
  experimental estimated SG charge $788.76 - $1262.02.

1 line(s) remitted by the deadline but with no fund-receipt date. The statutory timing test turns on receipt by the fund, not the day you paid, and clearing-house transit time is the employer's risk.

Assumptions and limits:
  - Legal content current at 2026-08-15. LCR 2026/1, LCR 2026/2 and LCR 2026/3 were issued on 5 Aug 2026. LCR 2026/D1 remains a draft pending the appeal from Department of Education v Commissioner of Taxation [2026] FCA 898.
  - The amount column must be the operator-determined super guarantee amount after applying the employee/payment boundaries in regulations 11 and 12, qualifying earnings and other applicable limits. Salary sacrifice and additional contributions must be filtered out. This tool does not make those classifications; LCR 2026/D1 also remains draft.
  - Deadlines use the national business-day calendar in SGAA s 6(1): weekends plus holidays applying to the whole of any State, the ACT or the NT.
  - No assessment date given, so a late contribution that reached the fund is assumed to have done so before any assessment (s 18D).
  - Deadline alignment under s 18C(2) item 4 is applied only where an earlier row evidences an eligible contribution received by the fund, allocated to that QE day and on time. Include each employee's earlier paydays and reconcile the statutory allocation before treating an item 4 extension as settled.
  - The low estimate assumes a voluntary disclosure lodged within 30 days of the payday and a clean 24-month history; the high estimate assumes neither. Choice loading, the late payment penalty and interest on an unpaid assessment are not included. The ATO assesses the charge.
  - Exposure figures are EXPERIMENTAL ESTIMATES. This tool displays each component to cents with ROUND_HALF_UP so report columns add up. LCR 2026/3 confirms only that TAA 1953 s 16B reduces the Commissioner's final assessed SG charge to the nearest 5 cents; it does not authorise per-line cents rounding here.
  - Maximum contributions base ($270,830 for 2026-27, annual per employer) is not applied: it needs each employee's cumulative earnings for the year. High earners may show a larger shortfall here than the law requires.
  - PCG 2026/1 sets the ATO's compliance approach for QE days to 30 Jun 2027. Fixing a late contribution promptly lowers ATO review risk; it does not remove the liability.
  - This tool tests the SG charge only. Fund deeds, enterprise agreements and awards can require earlier payment.

Full detail written to report.csv

Educational tool, not advice. Check anything material against the ATO's own guidance and calculators.
```

The input is fabricated. No employer or employee data are used.
