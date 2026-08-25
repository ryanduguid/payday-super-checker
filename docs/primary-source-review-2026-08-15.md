# Primary-source implementation review, 15 August 2026

This review supersedes the earlier working notes of 2 August 2026. It checks the shipped rules against current
Commonwealth legislation, final ATO legal-database material and official
jurisdiction holiday publications. Secondary commentary was not used to settle
any rule.

## Review position

The bundled holiday table is complete through 31 August 2027, subject to the
input and statutory-fact limitations below. That is a calendar boundary, not a
claim that every deadline or compliance result in the period is established.
Monetary SG-charge output and this checker as a whole remain **experimental**;
the output is a review aid, not an assessment or compliance determination.
Qualifying-earnings classification remains a human decision because LCR
2026/D1 is still draft. The checker does not post a payroll transaction, pay
super, lodge a disclosure or SG statement, accept an assessment, or make an
accounting decision. This review does not itself authorise a release.

The fail-closed controls added from this review are:

- a contribution dated no later than 28 July 2026 cannot be assessed until the
  operator confirms the LCR 2026/1 transition allocation;
- the importer refuses an employee with multiple positive in-scope paydays
  until the operator confirms the LCR 2026/2 fund-receipt ordering,
  earliest-shortfall allocation and assessment facts;
- item 4 extends a later deadline only where an earlier canonical row
  evidences an eligible contribution received by the fund, applied to that QE
  day and on time; otherwise a verdict that depends on the extension is
  attention-driving `UNKNOWN`;
- `out_of_cycle=yes` is rejected without the subsequent standard QE day that
  the final determination requires;
- an unconfirmed holiday date is not used to extend a deadline;
- funded, unfunded and stale-prepayment rows after the official whole-of-
  jurisdiction calendar horizon can produce attention-driving `UNKNOWN` with
  no exposure rather than a false late/on-time or unpaid conclusion; and
- every exposure figure is labelled experimental and explains the unresolved
  per-line rounding boundary.

## Instrument and out-of-cycle payments

The controlling instrument is the
[Superannuation Guarantee (Administration)(Out-of-Cycle Qualifying Earnings)
Determination 2026](https://www.legislation.gov.au/F2026L00784/asmade/text),
Federal Register identifier **F2026L00784**, made 22 June, registered 24 June
and commencing 1 July 2026. The earlier review called it “LI 2026/20”, but the
Federal Register's as-made page does not display that shorthand. No current
primary source found in this review was used to elevate the shorthand into an
identifier. The registered identifier and text control and are used throughout
the runtime and current guidance.

Section 5 has a closed list: allowances, bonuses, commissions, loadings,
payments in advance and back payments. The employer must have an established
timing, pattern or schedule and the payment must fall outside it. Most
importantly, subsection 5(3) requires the employer to actually make a later,
non-out-of-cycle QE payment on the next day consistent with that schedule.

Runtime result: `out_of_cycle=yes` now requires `next_standard_payday` as an
assertion of the actual subsequent non-out-of-cycle QE payment and rejects the
row if it is missing or is not later than the first payment. A planned payday
does not satisfy the field. A termination or final payment is not granted item
2 treatment merely because it contains one of the six listed payment kinds:
without the required subsequent payment the operator must set
`out_of_cycle=no` and apply the ordinary rules. This is tested both with and
without the separate first-to-fund rule.

## ATO ruling status and the July transition

The ATO legal database was read directly on 15 August 2026:

- [LCR 2026/1: application, savings and transitional
  provisions](https://www.ato.gov.au/law/view/document?DocID=COG%2FLCR20261%2FNAT%2FATO%2F00001),
  issued 5 August 2026;
- [LCR 2026/2: eligible
  contributions](https://www.ato.gov.au/law/view/document?DocID=COG%2FLCR20262%2FNAT%2FATO%2F00001),
  issued 5 August 2026;
- [LCR 2026/3: calculation and assessment of the SG
  charge](https://www.ato.gov.au/law/view/document?DocID=COG%2FLCR20263%2FNAT%2FATO%2F00001),
  issued 5 August 2026; and
- [LCR 2026/D1: qualifying
  earnings](https://www.ato.gov.au/law/view/document?DocID=COD%2FLCR2026D1%2FNAT%2FATO%2F00001),
  still draft. The ATO says finalisation is pending the appeal from
  *Department of Education v Commissioner of Taxation* [2026] FCA 898.

The final rulings identify their previous drafts as LCR 2026/D2, LCR 2026/D3
and LCR 2026/D4 respectively. Any statement that all four rulings remain draft
is out of date; only LCR 2026/D1 remains draft in this series as at the review
date.

LCR 2026/1 paragraphs 15 to 21 allow a pre-1 July contribution to carry into the
new regime only to the extent it is unused excess after the old regime. Its
paragraphs 25 to 29 require contributions made from 1 to 28 July 2026 to reduce
any employee shortfall for the quarter ended 30 June 2026 before a remainder
can be applied to a new-regime QE day. The canonical CSV has no old-quarter
balance and cannot calculate that allocation.

Runtime result: by default, a row using a known fund receipt no later than 28
July 2026 is rejected. If receipt is unknown, a remittance no later than that
date is also rejected because the checker cannot prove the contribution fell
outside the overlap. The operator must first reconcile each affected
employee, then pass `--confirm-transition-allocation`. The confirmation and
its basis are written into each affected report row. A known receipt after 28
July needs no confirmation.

LCR 2026/2 paragraphs 31 to 33 state that an on-time or late eligible
contribution is applied automatically under the law, first to the earliest QE
day with a base or final shortfall (assuming no assessment), with contributions
ordered by receipt at the fund. A vendor pay-period end is not an allocation
instruction. The importer has employer payment dates, not fund-receipt order,
and does not know whether an assessment altered the available shortfalls.

Runtime result: a shared payment is allocated oldest outstanding covered QE
day first; the former period-end priority was removed. Where an employee has
multiple positive in-scope paydays, the importer writes no canonical file
until the operator reconciles all relevant paydays, fund receipts and
assessments and passes `--confirm-statutory-allocation`. That flag asserts that
the export periods plus payment-date/row order reproduce the statutory
allocation. The confirmation is printed in the import record. Without that
reconciliation, the operator must prepare the canonical row association from
fund records rather than rely on the importer.

SGAA s 18C(2) item 4 also requires the earlier eligible contribution to have
been made and applied under s 18C(1). A positive SG amount or an employer
remittance is not proof. The deadline engine now extends item 4 only from an
on-time fund receipt associated with the earlier canonical row. Where an
earlier row could qualify but does not prove those facts, the later row keeps
the evidenced deadline and, only if the alternative deadline changes the
outcome, reports both candidate verdicts as attention-driving `UNKNOWN` with no
exposure.

LCR 2026/D1 discusses termination payments, including payment in lieu of
notice and unused annual leave, but those views remain draft. The checker does
not classify raw earnings. `sg_amount` remains an operator-provided SG amount,
and the console now states that termination and other qualifying-earnings
classification is human-only while D1 is unresolved.

## Regulations 11 to 13D

The current official compilation is the
[Superannuation Guarantee (Administration) Regulations 2018, compilation 8
from 1 July 2026](https://www.legislation.gov.au/F2018L01289/2026-07-01/2026-07-01/text/original/epub/OEBPS/document_1/document_1.html)
(F2026C00535).

- Regulation 11 prescribes kinds of employees for the SGAA provisions,
  including the under-18/part-time category in paragraph 11(f).
- Regulation 12 prescribes excluded payments.
- Regulation 13 concerns natural disasters and widespread ICT or other
  contribution-platform outages for exceptional-circumstances
  determinations. The checker does not detect these determinations and says
  so; its ordinary deadline is conservative where one applies.
- Regulation 13A sets the 60% administrative-uplift starting point and
  outlines the reductions.
- Regulation 13B permits reductions to apply separately or cumulatively but
  not below nil.
- Regulation 13C supplies the 20-percentage-point clean-history reduction.
  For QE days from 1 July 2026 through 30 June 2028, the lookback starts at 1
  July 2026.
- Regulation 13D supplies the voluntary-disclosure reductions: 40 points
  before the end of the 30-day period starting on the QE day, 35 points
  through 60 days, 30 points through 120 days and 15 points after 120 days,
  provided disclosure precedes assessment.

The runtime does not apply regulations 11 or 12 to raw payroll data. The
operator-provided `sg_amount` must already reflect those employee and payment
boundaries, qualifying earnings and other applicable limits; the checker does
not represent their omission as resolved.

The `sgc.py` matrix matches regulations 13A to 13D. Regulation 13C(3) shortens the
historical period tested during the transition; it does not prove that most or
any particular employer meets the clean-history conditions. The report still
presents a range because the CSV does not establish disclosure and prior-
history facts; an assessment date can be supplied separately, but the ATO
determines the assessment and applicable reductions.

## Maximum contribution base

The ATO's [Maximum contribution
base](https://www.ato.gov.au/businesses-and-organisations/super-for-employers/paying-super-on-payday/what-payments-are-qualifying-earnings/maximum-contributions-base)
page, updated 10 August 2026, gives **$270,830 annual per employer for
2026-27**. It states the formula: the $32,500 concessional contributions cap
multiplied by 100/12, rounded down to the nearest $10. This was cross-checked
against the ATO's [Super guarantee rates and thresholds
table](https://www.ato.gov.au/tax-rates-and-codes/key-superannuation-rates-and-thresholds/super-guarantee).

`rates.json` now records both direct ATO URLs and the 15 August check date. The
checker deliberately does not apply the base because its input does not hold
cumulative financial-year qualifying earnings per employee and employer.
High-earner exposure can therefore be overstated; the warning remains in the
CSV and console instead of inventing a cumulative balance.

## Rounding authority

LCR 2026/3 calculates the individual SG amount from total qualifying earnings
for an employee on a QE day multiplied by 12%. It does not establish a
per-line cents-rounding rule for this checker's intermediate values. Footnote
86 confirms that TAA 1953 s 16B ([Taxation Administration Act
1953](https://www.legislation.gov.au/C1953A00001/2026-07-01/2026-07-01/text/original/epub/OEBPS/document_1/document_1.html)) reduces the
Commissioner's final assessed SG charge to the nearest multiple of five cents.
That is an assessment-level rule, not authority to round every employee,
payday, shortfall, interest or uplift component first.

Runtime result: calculations continue at full `Decimal` precision and report
components are displayed to cents with `ROUND_HALF_UP` so each report row adds
up. That display boundary is an implementation choice. It is now disclosed in
the console and trailing CSV note, and every monetary result is labelled an
**experimental estimate**. The checker does not pretend to reproduce the
Commissioner's final five-cent assessment rounding.

## Whole-of-jurisdiction holiday calendar

SGAA s 6(1) uses one national calendar: weekends and any public holiday for
the whole of a State, the ACT or the NT. The ATO's [Business days
decoded](https://www.ato.gov.au/tax-and-super-professionals/for-superannuation-professionals/super-funds-newsroom/business-days-decoded-why-it-matters-for-your-fund)
guidance confirms that a regional holiday is not enough.

The bundled dates were checked against each official jurisdiction source:

- [ACT](https://www.act.gov.au/living-in-the-act/public-holidays-school-terms-and-daylight-saving)
- [NSW](https://www.nsw.gov.au/about-nsw/public-holidays)
- [NT](https://nt.gov.au/nt-public-holidays)
- [Queensland](https://www.qld.gov.au/recreation/travel/holidays/public)
- [South Australia](https://safework.sa.gov.au/resources/public-holidays)
- [Tasmania](https://worksafe.tas.gov.au/topics/laws-and-compliance/public-holidays)
- [Victoria](https://business.vic.gov.au/business-information/public-holidays/victorian-public-holidays-2027)
- [Western Australia](https://www.wa.gov.au/service/employment/workplace-arrangements/public-holidays-western-australia)

The source registry and check date now ship inside `business_days.json`.
Regional and part-day holidays remain excluded. The review also corrected two
dates that were unsafe to include:

- WA's official page says some regional areas observe an alternative King's
  Birthday date, so the default date is not a holiday throughout WA; and
- Victoria says non-metro councils may arrange an alternative to Melbourne
  Cup Day, so the default date is not a holiday throughout Victoria.

Both are now business days for this national SG definition. Business Victoria
confirms Friday 25 September 2026 as the whole-of-Victoria grand-final holiday,
so it is no longer provisional. The exact 2027 and 2028 dates remain
fixture-dependent and are not used to extend a deadline unless confirmed by an
override.

Business Victoria says the exact 2027 grand-final holiday remains subject to
the AFL schedule. A guessed reference date cannot make the calendar complete,
so the bundled completeness horizon is **31 August 2027**. Later deadlines
fail closed until the exact date is officially published or supplied through
a reviewed override.

The WA Government says its 2028 dates will be published when confirmed, and
the [Public and Bank Holidays Amendment Bill 2025 remains at Legislative
Council second reading](https://www.parliament.wa.gov.au/parliament/bills.nsf/BillProgressPopup?ParentUNID=BBE2E54905F318A948258D08002E4F0C&openForm=).
Reference entries after the horizon do not make the period complete. A user
may extend the horizon only with an override that supplies the missing
official dates and an explicit `verified_until` declaration.

## Residual limitations

These are deliberate, visible limits rather than unverified claims:

- LCR 2026/D1 remains draft, so raw-pay classification, including termination
  treatment, remains outside the checker and human-approved.
- Regulations 11 and 12 are not applied to raw exports; `sg_amount` is an
  operator-determined input after those boundaries.
- Canonical contribution-to-QE allocation is an operator assertion. The
  importer requires explicit LCR 2026/2 reconciliation when one employee has
  multiple positive in-scope paydays.
- Item 4 needs evidenced receipt, allocation and on-time status; unresolved
  alternatives remain attention-driving rather than treated as extensions.
- The maximum contribution base is warning-only because cumulative employee
  earnings are absent.
- Choice loading, late-payment penalty, post-assessment GIC, fund deeds,
  awards and enterprise agreements remain outside the estimate.
- Exceptional-circumstances determinations are not discovered automatically.
- Monetary output is experimental because the Commissioner assesses the
  charge and the tool cannot reproduce every assessment fact or final rounding
  boundary.
- Official whole-of-jurisdiction calendar coverage ends on 31 August 2027,
  before the still-unconfirmed 2027 Victorian grand-final holiday.

No release should describe these limits as resolved calculations. A future
change may implement them only with the missing data, a current primary source
and focused adverse-branch tests.
