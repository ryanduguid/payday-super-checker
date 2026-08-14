# Payday super: research notes, 2 August 2026

> **Historical snapshot — source gates re-checked 15 August 2026.** The
> statements below about LCR 2026/D1–D4 all being draft, the maximum
> contribution base resting on snippets, unread SGAR regulations, an unread
> out-of-cycle instrument, calendar coverage through 2028 and unresolved
> release-browser checks are superseded by
> [`primary-source-review-2026-08-15.md`](primary-source-review-2026-08-15.md).
> LCR 2026/1–3 are final; only LCR 2026/D1 remains draft. F2026L00784,
> regulations 11–13D, the $270,830 base and all eight official holiday sources
> were read directly. The old wording remains below to preserve the audit trail
> and must not be treated as current release status.

These are working research notes, not advice. They were produced by an automated
multi-agent research pass on 2 August 2026 and then cross-checked by a separate
verification agent, whose findings appear at the end. They record where each legal
constant in this tool came from so a reader can follow the citation and judge it.

Two limits worth knowing before relying on anything here. Several primary sources
block automated fetching, so a few points rest on secondary commentary rather than
the instrument itself, and those are marked. ATO law companion rulings LCR 2026/D1
to D4 were still drafts on that date, so interpretations sourced from them may shift.
The final out-of-cycle determination was subsequently read on the Federal Register
and the corresponding entry below was refreshed on 14 August 2026.
Confidence ratings and open ambiguities are the researchers' own.

The notes below include instructions the researchers wrote to themselves,
telling a publisher to re-check certain figures in a browser before release.
Those instructions stand, and the items they name are the same ones flagged
above: the GIC rate, the maximum contributions base,
and whether LCR 2026/D1 to D4 have since been finalised. Every figure the
tool actually uses carries its own source and check date in
`paydaysuper/data/`.

## Lane: deadline

### Enacted legislation: names, numbers, status [confidence: high]

The payday super regime is ENACTED LAW, in force. Treasury Laws Amendment (Payday Superannuation) Act 2025 (Act No. 57 of 2025) received Royal Assent 6 Nov 2025 and amends the Superannuation Guarantee (Administration) Act 1992 (SGAA) with effect for payments of qualifying earnings from 1 Jul 2026. Companion imposing Act: Superannuation Guarantee Charge Amendment Act 2025 (Act No. 58 of 2025), same assent date. Supporting delegated legislation: Treasury Laws Amendment (Payday Superannuation) Regulations 2026 (F2026L00133, registered 23 Feb 2026), amending the Superannuation Guarantee (Administration) Regulations 2018 (SGAR).

Citation: https://www.legislation.gov.au/C2025A00057/asmade (No. 57, 2025, assent 6 Nov 2025); https://www.aph.gov.au/Parliamentary_Business/Bills_Legislation/Bills_Search_Results/Result?bId=r7374 (No. 58 of 2025); https://www.legislation.gov.au/F2026L00133/latest/text; seen 2026-08-02

### Core deadline: 7 business days ('usual period') [confidence: high]

An SG contribution counts as on-time for a QE day if it is RECEIVED by the employee's fund during the 'usual period': the period 'starting on the QE day; and ending on the seventh business day after the QE day' (SGAA s 6(1) definition of 'usual period', quoted verbatim from the 1 Jul 2026 compilation). Operative provision: s 18C(1)(c)(i). Eligible contributions offset the individual SG amount only if received within a standard period or an allowable longer period. Early payments also count: the second standard period is 'the 12-month period ending on the day before the current QE day' (s 18C(1)(c)(ii)).

Citation: SGAA 1992 s 6(1) ('usual period'), s 18C(1)(c), compilation of 1 Jul 2026, https://www.legislation.gov.au/C2004A04402/latest (text verified verbatim from the FRL DOCX download, 2026-08-02)

### Statutory definition of 'business day': national, not employer-state [confidence: high]

SGAA s 6(1), verbatim: "business day means a day other than: (a) a Saturday or a Sunday; or (b) a day which is a public holiday for the whole of: (i) any State; or (ii) the Australian Capital Territory; or (iii) the Northern Territory." Effect: ONE national business-day calendar for all employers. A public holiday observed by the whole of ANY single State/ACT/NT (e.g. WA Day, Vic Melbourne Cup Day if state-wide) removes that day for every employer in Australia, regardless of where employer or employee is located. A holiday applying to only part of a State (e.g. Royal Hobart Show Day, regional show days) is still a business day. ATO confirms this reading: a state-wide holiday anywhere means not a business day 'even if your fund is not located in that state or territory'.

Citation: SGAA 1992 s 6(1) 'business day', 1 Jul 2026 compilation, https://www.legislation.gov.au/C2004A04402/latest (verbatim, 2026-08-02); ATO confirmation: https://www.ato.gov.au/tax-and-super-professionals/for-superannuation-professionals/super-funds-newsroom/business-days-decoded-why-it-matters-for-your-fund (seen via search 2026-08-02)

### Clock trigger: QE day is the day earnings are PAID, not the payslip period [confidence: high]

SGAA s 17A(1): the Subdivision applies 'if an employer makes a payment of qualifying earnings to or for an employee on a particular day (the QE day)'. The trigger is the actual payment (money paid to or on behalf of the employee), not the payslip date or pay-period end. For salary sacrifice, the QE day is the day the earnings reduction is made in return for the sacrificed contribution (s 10A(4)(b), noted in s 17A(1) Note). Every day on which any qualifying earnings are paid is a QE day with its own deadline.

Citation: SGAA 1992 ss 17A(1), 10A(4), 1 Jul 2026 compilation, https://www.legislation.gov.au/C2004A04402/latest (verbatim, 2026-08-02)

### SG rate: 12% of qualifying earnings for 2026-27 [confidence: high]

Individual SG amount for a QE day = amount of qualifying earnings × charge percentage/100, where 'charge percentage means 12' (SGAA s 17A(2), verbatim). 12% has applied since 1 Jul 2025 and remains the final legislated rate, with no further scheduled increases. PCG 2026/1 footnote 8 confirms: qualifying earnings multiplied by 0.12.

Citation: SGAA 1992 s 17A(2), 1 Jul 2026 compilation, https://www.legislation.gov.au/C2004A04402/latest (verbatim, 2026-08-02); PCG 2026/1 fn 8; ATO SG rate page https://www.ato.gov.au/tax-rates-and-codes/key-superannuation-rates-and-thresholds/super-guarantee

### Qualifying earnings (QE) definition vs old OTE [confidence: high]

SGAA s 10A(1): QE = (a) ordinary time earnings; (b) all commissions; (c) executive-body/director payments; (d) labour-contract payments (s 12(3)); (e) parliamentarian remuneration; (f) artist/entertainer/sportsperson payments (s 12(8)); (g) s 12(9)/(10) office-holder remuneration; (h) salary-sacrificed amounts (the reductions made in return for sacrificed contributions). Double-count protection s 10A(2). Exclusions: s 10A(3) (reversal of sacrificed contributions; prescribed kinds) plus SGAR regs 11-12: reg 11 excludes certain senior-executive visa holders and 'a part-time employee who is under 18' (part-time = employed to work not more than 30 h/wk, s 6(1)); reg 12 excludes parental leave payments, certain community-service/ADF absence payments, fringe benefits, certain non-resident/foreign work payments, and domestic/private work ≤30 h/wk. OTE remains defined in s 6(1) and still excludes termination lump sums for unused sick/annual/long-service leave.

Citation: SGAA 1992 ss 10A(1)-(3), 6(1) ('ordinary time earnings', 'part-time employee'), 1 Jul 2026 compilation, https://www.legislation.gov.au/C2004A04402/latest; SGAR 2018 regs 11-12, Compilation No. 8, 1 Jul 2026, https://www.legislation.gov.au/F2018L01289/latest (both verified verbatim 2026-08-02)

### Maximum contributions base: now ANNUAL per employer [confidence: high]

The maximum contributions base is now annual (was quarterly pre-1 Jul 2026): MCB = basic concessional contributions cap for the FY ÷ (charge percentage/100), rounded down to nearest $10 (SGAA s 10A(5)). Once an employee's total QE from one employer in a financial year exceeds the MCB, the excess is treated as nil QE (s 10A(6)). For 2026-27: concessional cap $32,500 → MCB $270,830 (ATO-published).

Citation: SGAA 1992 s 10A(5)-(6), 1 Jul 2026 compilation, https://www.legislation.gov.au/C2004A04402/latest (2026-08-02); ATO MCB page https://www.ato.gov.au/businesses-and-organisations/super-for-employers/paying-super-on-payday/what-payments-are-qualifying-earnings/maximum-contributions-base ($270,830); ATO concessional cap page ($32,500 from 1 Jul 2026), seen 2026-08-02

### Exception 1: new employee / new fund: 20 business days [confidence: high]

SGAA s 18C(2) table item 1: if the eligible contribution is the FIRST eligible contribution made to a particular fund/RSA by the employer for the employee (a) after the employee commenced or recommenced employment, or (b) after the employer ceased contributing to another fund for that employee (fund switch), it may be received during the 'extended usual period': 'starting on the QE day; and ending on the 20th business day after the QE day' (s 6(1), verbatim). ATO worked example: first QE day 9 Jul 2026 → contribution due 7 Aug 2026 (20 business days). The extension attaches to the first contribution to that fund, not to a fixed onboarding window.

Citation: SGAA 1992 s 18C(2) table item 1, s 6(1) 'extended usual period', 1 Jul 2026 compilation, https://www.legislation.gov.au/C2004A04402/latest (verbatim, 2026-08-02); ATO example: https://www.ato.gov.au/businesses-and-organisations/super-for-employers/paying-super-on-payday/payment-deadlines-for-payday-super (via search 2026-08-02)

### Exception 2: out-of-cycle payments [confidence: high]

SGAA s 18C(2) table item 2 + s 18C(3): where the QE day relates to qualifying earnings of a kind determined by the Commissioner as 'out-of-cycle', AND a later QE day exists for ordinary-cycle earnings (a 'standard QE day'), the contribution deadline rolls to 'before the end of the usual period for the first standard QE day after the current QE day', i.e. the out-of-cycle payment's super rides with the next regular payday's 7-business-day window. The final Superannuation Guarantee (Administration)(Out-of-Cycle Qualifying Earnings) Determination 2026 is registered as F2026L00784 and commences on 1 July 2026. Section 5(1) exhaustively lists allowances, bonuses, commissions, loadings, payments in advance and back payments. Under s 5(2), the employer must have an established timing, pattern or schedule for qualifying-earnings payments and the payment must fall outside it. Section 5(3) requires a subsequent qualifying-earnings payment on the next day consistent with that schedule, subject to s 5(4), which allows one or more out-of-cycle payments between the first and subsequent payments. A termination or final pay is therefore not covered merely because it is a listed kind: without the required subsequent scheduled payment, item 2 cannot apply and the ordinary 7-business-day rule governs the QE day.

Citation: SGAA 1992 s 18C(2) item 2, s 18C(3), 1 Jul 2026 compilation (verbatim, 2026-08-02); Superannuation Guarantee (Administration)(Out-of-Cycle Qualifying Earnings) Determination 2026 ss 2 and 5, F2026L00784, https://www.legislation.gov.au/F2026L00784/asmade/text (final instrument read 2026-08-14).

### Exception 3: exceptional circumstances determinations [confidence: high]

SGAA s 18C(2) table item 3 + s 18C(4): the Commissioner may by legislative instrument determine kinds of employers affected by prescribed exceptional circumstances and the affected period; contributions are then on time if received before the later of (a) end of the extended usual period (20 business days) for the QE day and (b) end of 20 business days starting the day after the determination is made. Prescribed kinds (SGAR reg 13, verbatim): '(a) natural disasters; (b) widespread outages of: (i) information and communication technology services; or (ii) other technology services or platforms that facilitate or support employers to make contributions.' Note also s 18C(2) item 4: if a QE day's usual period ends before the latest due day of an earlier contribution applied to an earlier QE day, the later QE day's deadline extends to that earlier latest due day (protects e.g. the second payday inside a new employee's 20-day window).

Citation: SGAA 1992 s 18C(2) items 3-4, s 18C(4), 1 Jul 2026 compilation (verbatim); SGAR 2018 reg 13, Compilation No. 8, 1 Jul 2026, https://www.legislation.gov.au/F2018L01289/latest (verbatim, 2026-08-02)

### When the obligation is MET: fund receipt, not clearing house payment [confidence: high]

The deadline tests when the contribution is RECEIVED by the fund, not when the employer pays: s 18C(1) applies eligible contributions 'in the order that it is received by the relevant fund, RSA, representative or scheme' and only if 'so received during' the usual/extended period. An eligible contribution must also be 'able to be allocated within the fund for the benefit of the employee' (s 18A(1)(a)(ii)), so a payment the fund cannot allocate (bad member data, rejected contribution) does not discharge the obligation. Paying a commercial clearing house by the deadline is NOT sufficient; money must reach the fund. The Act distinguishes 'receipt day' (day received by fund, s 33(3)(a)) from 'payment day' (day debited from employer's account, s 33(3)(b)); a 7-business-days-after-payment-day deeming of receipt exists ONLY for a narrow purpose: calculating notional earnings in a voluntary-disclosure assessment where no receipt day was disclosed (s 36(3)). It is not a general safe harbour. Supporting plumbing: the 2026 Regulations require fund trustees to allocate or return contributions within 3 business days of receipt.

Citation: SGAA 1992 ss 18A(1), 18C(1)(b)-(c), 33(3), 36(3), 1 Jul 2026 compilation, https://www.legislation.gov.au/C2004A04402/latest (verbatim, 2026-08-02); trustee 3-business-day allocation: Treasury Laws Amendment (Payday Superannuation) Regulations 2026 (F2026L00133) amendments to SIS Regulations, per https://www.legislation.gov.au/F2026L00133/latest/text and ASFA summary (seen via search 2026-08-02)

### Small Business Superannuation Clearing House: retired [confidence: high]

The ATO's SBSCH is closed. New users could not register from 1 Oct 2025; existing users could use it until 11:59 pm AEST 30 Jun 2026; from 1 Jul 2026 employers cannot log in, submit payment instructions or view records. As at Aug 2026 the SBSCH does not exist as a payment channel. Tools must not suggest it.

Citation: https://www.ato.gov.au/businesses-and-organisations/small-business-newsroom/the-small-business-superannuation-clearing-house-is-closing (seen via search 2026-08-02)

### SG charge composition (for exposure estimates) [confidence: high]

SG charge for a QE day = sum of (a) individual final SG shortfalls (unpaid 12% amounts, s 18D), (b) individual notional earnings components, daily compounding at the general interest charge rate (s 8AAD TAA 1953) for each day in the 'late period' the final shortfall exceeds nil (s 19A), (c) administrative uplift = 60% of (a)+(b) (s 19B(1)), reducible under regs, and (d) choice loadings = 25% of contributions made in breach of choice-of-fund requirements, capped by the choice loading limit (ss 20-20A, s 20C) (SGAA s 16B(2)). Late contributions made before assessment reduce the final shortfall (s 18D 'late period') but cannot reduce the charge to nil because notional earnings and uplift remain (PCG 2026/1 para 10). Charge is payable on the day the assessment is made (s 36(4)). Charge arises per QE day (s 16A), with no quarterly SG statement; instead optional 'voluntary disclosure statements' (s 33).

Citation: SGAA 1992 ss 16A, 16B(2), 18D, 19A, 19B, 20A, 33, 36(4), 1 Jul 2026 compilation, https://www.legislation.gov.au/C2004A04402/latest (verbatim, 2026-08-02); PCG 2026/1 para 10

### Administrative uplift reductions (60% → as low as 0%) [confidence: high]

SGAR 2018 Div 3 (regs 13A-13D, inserted by F2026L00133): the 60% uplift is reduced by (1) 20 percentage points if no Commissioner-initiated assessment (>nil) is in force and no s 268-10 TAA estimate was made for the employer in the 24 months ending on the QE day; transitional: for QE days 1 Jul 2026 to 30 Jun 2028 the look-back period is treated as starting 1 Jul 2026 (reg 13C(3)); and (2) if a voluntary disclosure statement is lodged before assessment: minus 40 points if lodged within 30 days of the QE day; 35 points within 31-60 days; 30 points within 61-120 days; 15 points after 120 days (reg 13D table). Both can stack; floor is 0%.

Citation: SGAR 2018 regs 13A-13D, Compilation No. 8 (1 Jul 2026, incorporating F2026L00133), https://www.legislation.gov.au/F2018L01289/latest (verbatim, 2026-08-02)

### First-year ATO compliance approach (not a law change) [confidence: high]

PCG 2026/1 (final, issued 28 Jan 2026) applies ONLY to QE days 1 Jul 2026 - 30 Jun 2027. Risk zones: LOW (attempted on-time payment, late receipt due to e.g. fund rejection, fixed as soon as reasonably practicable, final shortfalls nil), ATO 'will not have cause' to review; MEDIUM (not low, but all individual final SG shortfalls nil by 28 days after end of the quarter in which QE was paid, e.g. employers still paying quarterly), may be investigated at lower priority; HIGH (final shortfalls >nil after quarter-end+28 days), priority investigation. The Commissioner has NO discretion to waive the law: if definitive information shows a shortfall, the law is applied even for low-risk employers (para 11). The guideline does not apply to QE days on or after 1 Jul 2027.

Citation: PCG 2026/1 paras 2, 11-24, Tables 1-2, issued 28 Jan 2026, https://www.ato.gov.au/law/view/document?docid=COD/PCG20261/NAT/ATO/00001 (full text read from mirrored PDF, 2026-08-02)

### Open ambiguities in this lane

- Business-day calendar data: the statute names no holidays. The tool must ship/maintain a national calendar of public holidays that apply to the WHOLE of any State, the ACT or the NT, and must EXCLUDE part-of-state/regional holidays (e.g. Royal Hobart Show Day, regional show days) and include one-off state-wide declared holidays. Decide and document a data source and update cadence; miscoding one regional holiday shifts every affected deadline by a day.
- Edge reading of 'business day': s 6(1) lists States, ACT and NT only; holidays of other territories (e.g. Norfolk Island, Christmas Island) do not remove a business day. Also unresolved in statute: a holiday gazetted for 'part-day' (e.g. Christmas Eve evening part-day holidays in QLD/SA/NT); plain reading is that part-day holidays are not holidays 'for the whole of' the jurisdiction in the relevant sense; ATO guidance does not squarely address part-DAY (vs part-of-state) holidays. Surface as a flagged assumption.
- Payment date vs payslip date: the statutory trigger (s 17A(1)) is the day earnings are actually PAID (bank/EFT date), not period-end or payslip date. Pay-run CSVs often carry period-end. The tool must require the user to identify the actual payment-date column and warn when it differs from period dates. Salary-sacrifice reductions create a QE day too (s 10A(4)(b)).
- Fund-receipt vs remittance date: compliance turns on the day the FUND receives an allocable contribution, not the day the employer paid a clearing house (s 18C(1)). Employer records rarely hold fund-receipt dates. The tool can only compute deadlines and flag risk from remittance dates; it must state explicitly that remittance-date-based results assume same-day receipt, and that the s 36(3) '7 business days after payment day' deeming applies only inside voluntary-disclosure assessments, not as a general safe harbour. Clearing-house float is the user's residual risk.
- Out-of-cycle mechanics need next-payday data: s 18C(2) item 2 sets the deadline as the usual period of the FIRST later 'standard QE day', and the tool needs each employee's next regular payday to compute it, and must fall back to the default 7-business-day rule when no later standard QE day exists (e.g. terminated employees).
- New-employee extension scope: the 20-business-day window (s 18C(2) item 1) attaches to the FIRST eligible contribution to a particular fund (including fund switches mid-employment), not to a fixed onboarding period. Second paydays inside that window are protected only via item 4 (deadline alignment). The tool needs a start-date or first-contribution-to-fund flag and must implement the item 4 interaction, or conservatively apply plain 7-day deadlines and note possible false positives for new hires.
- GIC rate is a moving input: notional earnings compound daily at the general interest charge rate (s 19A; s 8AAD TAA 1953), which the ATO publishes quarterly. Ship it as a dated config value with the ATO GIC-rates page as source, not a hard-coded constant.
- Choice loading limit: s 20C formula was not extracted in this pass. If the tool estimates choice-of-fund exposure (25% loading), fetch and verify s 20C first; otherwise scope choice breaches out and say so.
- Guidance still in draft: LCR 2026/D1, LCR 2026/D2, LCR 2026/D3 and PS LA 2026/D3 (payday super law companion rulings / practice statement) were in draft as at 2 Aug 2026 and could not be fetched by script (ATO 403). Their finalisation may refine interpretations (e.g. 'able to be allocated', QE classifications). Re-verify before release and date-stamp the tool's legal content.
- Maximum contributions base is now ANNUAL per employer ($270,830 for 2026-27), not quarterly, and a checker reusing the old quarterly MCB logic overstates required super for high earners. Also the $32,500 concessional cap drives the MCB; both change yearly and belong in dated config.
- PCG 2026/1 risk zones are a compliance-resource-allocation policy for 2026-27 QE days only, not a legal defence; the Commissioner must apply the law if a shortfall is known (para 11). Tool messaging must present the medium-risk 'quarter-end + 28 days' marker as ATO triage, never as a lawful deadline, and must not extend it past 30 Jun 2027.

## Lane: sgc

### Enactment status [confidence: high]

Payday super is ENACTED LAW, not an announcement. Treasury Laws Amendment (Payday Superannuation) Act 2025 (No. 57 of 2025) and the Superannuation Guarantee Charge Amendment Act 2025 both received royal assent on 6 November 2025 and apply to QE days (paydays) from 1 July 2026. Supporting regulations (Treasury Laws Amendment (Payday Superannuation) Regulations 2026, F2026L00133) were made 19 February 2026.

Citation: https://www.legislation.gov.au/C2025A00057/asmade and https://www.legislation.gov.au/F2026L00133/asmade (seen 2026-08-02); royal-assent date via https://www.alvarezandmarsal.com/thought-leadership/payday-super-bills-received-royal-assent-and-start-date-remains-1-july-2026 (seen 2026-08-02)

### New SGC: components [confidence: high]

The redesigned SG charge for a QE day = (1) total individual FINAL SG shortfalls + (2) total individual notional earnings components + (3) administrative uplift amount + (4) total choice loadings. The old quarterly components (nominal interest at 10%, $20-per-employee admin fee, Part 7 200% penalty) do not apply to post-1-Jul-2026 paydays.

Citation: ATO, The new super guarantee charge, https://www.ato.gov.au/businesses-and-organisations/super-for-employers/payday-super/missed-or-late-payday-super-payments/the-new-super-guarantee-charge (seen 2026-08-02); SGAA 1992 s 16B as inserted per https://nexia.com.au/news/payday-super-changes-from-1-july-2026-superannuation-guarantee-charge/ (seen 2026-08-02)

### Shortfall base: qualifying earnings [confidence: high]

The shortfall is computed on QUALIFYING EARNINGS (QE, new SGAA s 10A), not the old 'salary or wages' base. QE broadly = OTE + amounts salary-sacrificed to super + ALL commissions (including commissions for work entirely outside ordinary hours). Individual SG amount = QE x 12% (charge percentage is 12% from 1 July 2025). An employee ATO exemption certificate can make QE nil.

Citation: SGAA 1992 ss 10A, 17A; ATO draft LCR 2026/D1 per https://www.claytonutz.com/insights/2026/june/payday-super-frequently-asked-questions (seen 2026-08-02); https://nexia.com.au/news/payday-super-changes-from-1-july-2026-superannuation-guarantee-charge/ (seen 2026-08-02)

### Base vs final shortfall (offsetting is automatic) [confidence: high]

Individual BASE SG shortfall = (QE x 12%) minus on-time eligible contributions (received and allocatable by the fund within 7 business days after the QE day; 20 business days for a new employee's first payment or first contribution to a different fund). Individual FINAL SG shortfall = base shortfall minus late eligible contributions received after the deadline but BEFORE the ATO makes the SG charge assessment. Late contributions offset automatically, with no election or statement needed (the old late-payment-offset election is gone; last quarter it applies to is the quarter ending 31 Mar 2026). Late/excess contributions apply automatically to the EARLIEST QE day with a shortfall and can be carried forward up to 12 months.

Citation: ATO, The new super guarantee charge (URL above, seen 2026-08-02); IPA, Payday Super — An Overview, v3 March 2026, https://www.publicaccountants.org.au/media/rslnwxe3/march2026_techresource_paydaysuper_f2.pdf (seen 2026-08-02); LCR 2026/D4 transition per https://www.bdo.com.au/en-au/insights/tax/articles/payday-super-developments-suite-of-new-draft-ato-guidance-materials-issued (seen 2026-08-02)

### Notional earnings: rate and compounding [confidence: high]

Notional earnings component (NEC, new SGAA s 19A) replaces the old 10% nominal interest. It accrues at the GENERAL INTEREST CHARGE rate, compounding DAILY: each day's NEC = daily GIC rate x notional sum, where notional sum = individual base SG shortfall + NEC already accrued on preceding days of the late period.

Citation: SGAA 1992 s 19A per https://nexia.com.au/news/payday-super-changes-from-1-july-2026-superannuation-guarantee-charge/ (seen 2026-08-02); daily-compounding formula per IPA v3 March 2026 PDF (URL above, seen 2026-08-02); ATO, The new super guarantee charge (URL above, seen 2026-08-02)

### Notional earnings: accrual window (critical formula input) [confidence: high]

NEC accrues over the 'late period': START = the day AFTER the last day an on-time eligible contribution could be made (i.e. day after the 7th business day following the QE day, or after the extended 20-business-day deadline where that applies), never from the payday itself. END = the EARLIER of (a) the day a late eligible contribution reduces the individual final SG shortfall to nil, and (b) the day before the ATO makes the SG charge assessment. One widely-shared secondary source (Scalesuite) claims accrual starts on the QE day itself. That contradicts the ATO page and draft LCR 2026/D3 and should be treated as wrong.

Citation: ATO, The new super guarantee charge (URL above, seen 2026-08-02: 'Notional earnings start to accrue on ... the day after the last day to make an on-time eligible contribution'); draft LCR 2026/D3, https://www.ato.gov.au/law/view/document?docid=COD%2FLCR2026D3%2FNAT%2FATO%2F00001 (seen 2026-08-02)

### GIC rate value (parameter, changes quarterly) [confidence: high]

GIC annual rate for 1 Jul–30 Sep 2026 is 11.43% (daily rate 0.03131507%, which is annual/365 because 2026 is not a leap year; TAA 1953 s 8AAD divides by the number of days in the calendar year, so a day in 2028 divides by 366). Prior quarter (Apr–Jun 2026) was 10.96%. The rate resets every quarter (90-day bank accepted bill rate + 7 percentage points uplift under TAA 1953 Pt IIA), so the tool must treat it as a dated parameter table, never a constant.

Citation: ATO, General interest charge (GIC) rates, https://www.ato.gov.au/tax-rates-and-codes/general-interest-charge-rates (official tables last updated 2026-06-05; read directly 2026-08-14). The 2026-27 table gives 11.43% annual and 0.03131507% daily for July-September 2026; the 2025-26 table gives 10.96% annual and 0.03002740% daily for April-June 2026.

### Administrative uplift: base [confidence: high]

Administrative uplift starts at 60% of (total individual final SG shortfalls + total individual notional earnings) for the QE day. It replaces both the $20-per-employee admin component and the old Part 7 up-to-200% penalty. The uplift is retained in consolidated revenue (the other three components are distributed to employees' funds).

Citation: ATO, The new super guarantee charge (URL above, seen 2026-08-02); https://www.grantthornton.com.au/insights/client-alerts/payday-super-regulations-released--understanding-the-new-administrative-uplift/ (seen 2026-08-02); IPA v3 March 2026 PDF (seen 2026-08-02)

### Administrative uplift: reduction schedule (exact numbers) [confidence: high]

Two cumulative reductions, prescribed by the 2026 Regulations (F2026L00133): (A) clean-history reduction of 20 percentage points if the Commissioner has NOT initiated an SGC assessment or estimate for the employer in the 24 months before the QE day; (B) voluntary-disclosure-timing reduction measured in days after the QE day: within 30 days = -40pp; 31–60 days = -35pp; 61–120 days = -30pp; more than 120 days (but before assessment) = -15pp; no VDS = -0pp. Resulting uplift percentages: clean history 0% / 5% / 10% / 25% / 40% (no VDS); prior-assessment history 20% / 25% / 30% / 45% / 60%. Floor is 0%.

Citation: ATO, The new super guarantee charge (URL above, seen 2026-08-02); Treasury Laws Amendment (Payday Superannuation) Regulations 2026 (F2026L00133) per https://www.grantthornton.com.au/insights/client-alerts/payday-super-regulations-released--understanding-the-new-administrative-uplift/ and https://www.claytonutz.com/insights/2026/june/payday-super-frequently-asked-questions (both seen 2026-08-02)

### Choice loading [confidence: high]

Choice loading = 25% of the value of eligible contributions for a QE day made in breach of the choice-of-fund rules, capped at $1,200 per notice period (cap raised from the old $500). It is a component of the SG charge and is distributed to the employee's account.

Citation: ATO, The new super guarantee charge (URL above, seen 2026-08-02); IPA v3 March 2026 PDF (seen 2026-08-02)

### Assessment: no more self-assessment statement [confidence: high]

The mandatory quarterly SG statement is ABOLISHED for QE days from 1 Jul 2026. The Commissioner assesses the SG shortfall and SG charge at any time, either on the ATO's own initiative (using Single Touch Payroll data, superannuation fund reporting/MATS matching, or employee notification) or on lodgment of a VOLUNTARY DISCLOSURE STATEMENT (VDS). ATO issues a notice of assessment; employers do not self-assess.

Citation: ATO, The new super guarantee charge (URL above, seen 2026-08-02: 'you no longer need to lodge a super guarantee statement ... We will calculate your super guarantee charge and send you a notice of assessment'); https://www.claytonutz.com/insights/2026/june/payday-super-frequently-asked-questions (seen 2026-08-02)

### Voluntary disclosure statement mechanics [confidence: medium]

A VDS is optional, must be in the approved form (minor errors don't invalidate), and can be lodged any time BEFORE the Commissioner makes an assessment for that QE day. Its only computational effect is the uplift reduction. It may state the fund receipt day and/or the employer payment day; if only the payment day is given, the receipt day is DEEMED to be 7 business days after the payment day for NEC calculation.

Citation: IPA, Payday Super — An Overview v3 March 2026 PDF (URL above, seen 2026-08-02); https://www.dbalawyers.com.au/ato/payday-super-part-1-the-new-law/ (seen 2026-08-02)

### SGC due date and GIC after assessment [confidence: high]

The SG charge is due and payable ON THE DAY the assessment is made. General interest charge (currently 11.43% p.a., daily compounding) accrues on any unpaid SG charge (shortfall + NEC + uplift components) from then until paid.

Citation: ATO, The new super guarantee charge (URL above, seen 2026-08-02); IPA v3 March 2026 PDF (seen 2026-08-02); https://www.dbalawyers.com.au/ato/payday-super-part-1-the-new-law/ (seen 2026-08-02)

### Late payment penalty (continued non-payment) [confidence: high]

If the SG charge is unpaid 28 days after it becomes payable, the Commissioner must issue a Notice to Pay; the amount is due 28 days after the day specified in that notice. If still unpaid, a LATE PAYMENT PENALTY applies: 25% of the outstanding amount; 50% if the employer was previously liable for the penalty in the 24-month period ending the day after the current notice payment period; 0% if an exceptional-circumstances determination applies. The LPP cannot be remitted by the ATO, does not itself accrue GIC, reduces proportionately if the SG charge reduces, and is objectable. This replaces the old Part 7 (up to 200%) penalty.

Citation: IPA v3 March 2026 PDF (URL above, seen 2026-08-02, incl. the 0%/25%/50% table); https://www.dbalawyers.com.au/ato/payday-super-part-1-the-new-law/ (seen 2026-08-02); https://www.superguide.com.au/super-booster/meeting-employer-super-obligations-penalties (seen 2026-08-02)

### Tax deductibility (changed from old law) [confidence: high]

REVERSED from the old regime: for QE days from 1 Jul 2026 the SG charge is TAX-DEDUCTIBLE in full, covering all four components (final shortfalls, notional earnings, administrative uplift, choice loading), because ITAA 1997 ss 26-95 and 290-95 were repealed. On-time AND late contributions are also deductible. NOT deductible: GIC that accrues on an unpaid/late SG charge payment, the late payment penalty, and any old-regime SGC for quarters before 1 Jul 2026 (which stays non-deductible).

Citation: ATO, The new super guarantee charge (URL above, seen 2026-08-02, explicit component-by-component list); repeal of ITAA 1997 ss 26-95 & 290-95 per https://hallandwilcox.com.au/news/payday-super-starts-1-july-2026-what-employers-need-to-do-now/ and https://www.dbalawyers.com.au/ato/payday-super-part-1-the-new-law/ (both seen 2026-08-02); IPA v3 deductibility table (seen 2026-08-02)

### Exposure-estimate formula (assembled from the above, per QE day) [confidence: high]

(1) sg_amount_i = round(QE_i x 0.12); (2) base_shortfall_i = sg_amount_i - on_time_contribs_i (on-time = received by fund within 7 business days after QE day, 20 BD for new employee/new fund); (3) NEC_i: for each day d in [due_date+1, min(day shortfall hits nil, assessment_day - 1)]: NEC += (base_shortfall_i + NEC) x GIC_daily(d) where GIC_daily = the quarterly annual rate for d divided by the number of days in the calendar year of d, which is 366 in a leap year (TAA 1953 s 8AAD). This step read "/ 365" as first written, which is wrong for 2028 and every later leap year, and `paydaysuper/rates.py` implements the statutory rule; (4) final_shortfall_i = base_shortfall_i - late_contribs_before_assessment_i; (5) uplift = uplift_pct x (Σ final_shortfall_i + Σ NEC_i), uplift_pct from {0,5,10,25,40}% (clean 24-month history) or {20,25,30,45,60}% (prior ATO-initiated assessment/estimate) keyed on VDS lodgment day minus QE day (≤30/31–60/61–120/>120/none); (6) choice_loading = 0.25 x affected_contributions, capped $1,200 per notice period (optional input); (7) SGC = Σ final_shortfall + Σ NEC + uplift + choice_loading; (8) post-assessment exposure: + GIC on unpaid SGC from assessment day, + LPP of 25% (or 50%) of unpaid amount if unpaid 28 days after Notice-to-Pay due date; (9) tax note: SGC deductible, GIC & LPP not.

Citation: Assembled strictly from the component facts above, ATO new-SGC page, F2026L00133 reduction schedule, IPA v3 NEC formula, DBA Lawyers LPP detail (all seen 2026-08-02)

### Old vs new regime boundary (tool must branch on payday date) [confidence: medium]

Paydays BEFORE 1 Jul 2026 stay under the OLD quarterly SGC (salary-and-wages base, 10% nominal interest from quarter start, $20/employee admin, Part 7 penalty, non-deductible, SG statement still required). Final old quarter is Apr–Jun 2026 (contributions due 28 Jul 2026). Transitional: contributions made 1–28 Jul 2026 apply FIRST to any 30 Jun 2026 quarter shortfall, then forward to new-regime paydays (draft LCR 2026/D4).

Citation: https://www.bdo.com.au/en-au/insights/tax/articles/payday-super-developments-suite-of-new-draft-ato-guidance-materials-issued (seen 2026-08-02); draft LCR 2026/D4

### SGAA section map (for citations in tool docs) [confidence: medium]

New/amended SGAA 1992 provisions per secondary sources: s 10A qualifying earnings; s 16B SG charge composition; s 17A minimum SG contribution (QE x charge %/100); s 19A individual notional earnings component. Section numbers for the uplift, choice loading, VDS and LPP provisions were not verifiable against primary text this session (ATO legal db and legislation.gov.au text views block fetchers).

Citation: https://nexia.com.au/news/payday-super-changes-from-1-july-2026-superannuation-guarantee-charge/ (seen 2026-08-02); s 10A corroborated by Clayton Utz FAQ (seen 2026-08-02)

### ATO guidance status [confidence: high]

ATO interpretive guidance is DRAFT, not final: LCR 2026/D1 (qualifying earnings), D2 (eligible contributions/7-business-day rule), D3 (SGC calculation and assessment), D4 (transition), released 18 Mar 2026; PCG 2026/1 also exists (compliance approach). The Act and Regulations are final law; the LCR numbers could shift at finalisation.

Citation: https://www.bdo.com.au/en-au/insights/tax/articles/payday-super-developments-suite-of-new-draft-ato-guidance-materials-issued (seen 2026-08-02); https://www.ato.gov.au/law/view/document?docid=COD%2FLCR2026D3%2FNAT%2FATO%2F00001 (seen 2026-08-02)

### Business day definition (feeds due-date and NEC start) [confidence: medium]

'Business day' = a day that is not a Saturday, Sunday, or a public holiday for the WHOLE of a State or Territory. Part-state/regional holidays do not extend the deadline.

Citation: https://www.dbalawyers.com.au/ato/payday-super-part-1-the-new-law/ (seen 2026-08-02, quoting the Act's definition)

### Peripheral but formula-relevant [confidence: medium]

(a) Maximum contribution base becomes ANNUAL instead of quarterly from 1 Jul 2026 (caps QE); (b) ATO Small Business Superannuation Clearing House abolished 1 Jul 2026 (stopped new employers 1 Oct 2025), so clearing-house processing time no longer protects employers: the contribution counts when RECEIVED and allocatable by the fund, not when paid to a clearing house.

Citation: MCB via https://www.claytonutz.com/insights/2026/june/payday-super-frequently-asked-questions (seen 2026-08-02); SBSCH via IPA v3 March 2026 PDF (seen 2026-08-02)

### Open ambiguities in this lane

- Partial late payments and NEC: the statutory notional-sum formula compounds on the individual BASE SG shortfall until the FINAL shortfall hits nil. Read literally, a partial late contribution does not slow interest accrual, only a payment clearing that employee's shortfall entirely stops it. Draft LCR 2026/D3 examples (unfetchable this session, ATO 403) would settle it. Tool should compute the conservative reading (full base shortfall until cleared) and surface the assumption.
- GIC rate is a quarterly moving parameter (11.43% for Jul–Sep 2026 per secondary sources only, because the ATO rates page blocked our fetcher). Late periods spanning quarters need per-quarter daily rates. Tool must ship a dated rate table with a staleness warning, and the 11.43% figure should be re-verified against ato.gov.au before release.
- SGAA section numbers for the administrative uplift, choice loading, VDS and late payment penalty provisions are unverified against primary legislation text (legislation.gov.au renders via JS; ATO PDF of the Act returns 401/403). Verify from the official compilation before printing section citations under the accountant's name.
- NEC end-day on assessment: ATO says accrual stops 'the day before' the assessment; where a VDS states only the employer payment day, receipt is DEEMED payment day + 7 business days for NEC purposes (IPA, single source). Affects estimates for users who disclose payment dates only.
- LPP lookback wording: 50% applies if 'previously liable for a penalty in the 24-month period ending on the day after the current notice payment period' (IPA) vs DBA's looser 'previous two years'. Exact boundary unverified in primary text; tool should present LPP as a post-assessment worst-case range, not a computed certainty.
- Uplift reduction discretion: the Regulations also allow reductions conditional on 'a person being satisfied of one or more specified matters', an ATO discretion the tool cannot model; estimates should show the table outcome as the default, flagged as reducible/increasable.
- Choice loading 'notice period' definition not researched; choice-of-fund breaches are not detectable from a pay-run CSV. Treat choice loading as an optional user-asserted input, default excluded from estimates.
- Business-day calculation: 'public holiday for the whole of a State or Territory': which State's holidays govern a given employer/employee is not resolved by the sources seen; national-uniform vs employer-State interpretation changes due dates by 1–2 days. Cross-check with the deadline research lane before hardcoding a holiday calendar.
- LCR 2026/D1–D4 are DRAFTS: calculation details sourced from them (accrual window edge cases, transition ordering) could change at finalisation; tool docs should date-stamp guidance reliance.
- One circulating secondary source (scalesuite.com.au) states notional earnings accrue from the QE day (payday) itself; this conflicts with ATO/LCR/IPA (accrual from day after the contribution deadline) and was rejected, but expect users to have seen the wrong version, so the tool's help text should state the accrual window explicitly.

## Lane: exceptions

### Regime status: enacted law [confidence: high]

Payday super is enacted law, not an announcement. Treasury Laws Amendment (Payday Superannuation) Act 2025 (No. 57 of 2025) received royal assent 6 Nov 2025 and amends the Superannuation Guarantee (Administration) Act 1992 (SGAA) with effect for QE days from 1 Jul 2026. Supported by Superannuation Guarantee Charge Amendment Act 2025 and Treasury Laws Amendment (Payday Superannuation) Regulations 2026 (F2026L00133, registered 23 Feb 2026).

Citation: https://www.legislation.gov.au/C2025A00057/asmade and https://www.legislation.gov.au/F2026L00133/asmade; full Act text read via https://www.ato.gov.au/law/view/pdf/acts/20250057.pdf, seen 2026-08-02

### Core deadline: usual period [confidence: high]

An on-time contribution must be RECEIVED by the employee's fund during the 'usual period': starts ON the QE day (the day qualifying earnings are paid) and ends on the 7th business day AFTER the QE day. Alternatively, contributions received in the 12-month period ending the day before the QE day (pre-payments) also count. QE day is defined in s 17A(1).

Citation: SGAA s 6(1) definition of 'usual period', s 18C(1)(c)(i)-(ii), s 17A(1), as inserted by Act No. 57 of 2025 Sch 1 (text read 2026-08-02); ATO: https://www.ato.gov.au/businesses-and-organisations/super-for-employers/paying-super-on-payday/payment-deadlines-for-payday-super

### Business day definition [confidence: high]

'business day' means a day other than (a) a Saturday or Sunday, or (b) a day which is a public holiday for the WHOLE of any State, the ACT, or the NT. So a state-wide public holiday in ANY state removes that day from the count for ALL employers nationally; regional or part-day holidays do not.

Citation: SGAA s 6(1) definition of 'business day', inserted by Act No. 57 of 2025 Sch 1 item 3 (text read 2026-08-02)

### (1) New employee / new fund: 20 business days [confidence: high]

Extended deadline (s 18C(2) table item 1): where the contribution is the FIRST eligible contribution made to a particular fund/RSA for the employee, either (a) after the employee commenced or recommenced employment, or (b) after the employer ceased contributing to another fund for that employee, the contribution may be received during the 'extended usual period': starts on the QE day, ends on the 20th BUSINESS day after the QE day. Trigger is the QE day (first payday), NOT the stapled-fund resolution or choice-form date. ATO phrases it as 'received within 20 business days of their first payday'.

Citation: SGAA s 18C(2) table item 1 + s 6(1) definition of 'extended usual period', Act No. 57 of 2025 Sch 1 (text read 2026-08-02); ATO payment-deadlines page (search snippet seen 2026-08-02)

### (1) Overlap rule for paydays inside an extended window [confidence: high]

s 18C(2) table item 4: if the usual period for a later QE day ends before the 'latest due day' that an earlier eligible contribution (applied to an earlier QE day) was able to be received, the later QE day's contribution may be received up to that latest due day. Practical effect: paydays 2 and 3 falling inside a new employee's 20-business-day window inherit the extended end date. Deadline for QE day N = max(usual period end for N, latest due day of earlier extended QE day).

Citation: SGAA s 18C(2) table item 4, Act No. 57 of 2025 Sch 1 (text read 2026-08-02); also PCG 2026/1 footnote 9

### (2) Stapled fund lookups: no separate relief [confidence: high]

No bespoke deadline relief exists for stapled-fund lookup delays. The 20-business-day extended usual period for a first contribution (item 1) is the accommodation for onboarding/stapling. Separately, s 20D protects against CHOICE LOADING (not lateness) where the employer, with no chosen fund in place, relies on the most recent Commissioner notification (stapled fund). Mid-employment choice change = item 1(b): first contribution to the NEW fund gets the 20-business-day extended usual period from its QE day.

Citation: SGAA s 18C(2) item 1, s 20D, Act No. 57 of 2025 Sch 1 (text read 2026-08-02)

### (5) Fund rejection / bounce-back [confidence: high]

APRA-regulated funds (non-SMSF, non-DB-interest) must allocate a received contribution within 3 business days, or if unable to allocate must REFUND it within 3 business days; a refunded contribution is 'taken not to have been made' (new SIS reg 7.07G(4)). There is NO deadline restart for resubmitting to the SAME fund. The re-made contribution must still land within the original allowable period or it is late. If redirected to a DIFFERENT fund, s 18C(2) item 1 can apply (first contribution to that fund → 20 business days from the QE day). SMSFs instead allocate within 28 days after month end (reg 7.07H).

Citation: SIS Regulations reg 7.07G-7.07H as substituted by F2026L00133 Sch 1 item 40 (text read via https://www.ato.gov.au/law/view/pdf/reg/r20260133.pdf, 2026-08-02)

### (5) Rejection handling: first-year compliance [confidence: high]

PCG 2026/1: for QE days 1 Jul 2026-30 Jun 2027, an employer who attempted on-time payment, had contributions rejected/late, and gets them received 'as soon as reasonably practicable' (final shortfalls nil) is LOW RISK, so the ATO 'will not have cause' to apply compliance resources (covers all SGC components incl. notional earnings, uplift, choice loading). Medium risk: shortfalls cleared within 28 days after quarter end but no payday-frequency alignment. High risk: final shortfalls remain after 28 days post-quarter. The law itself still applies, so the Commissioner has no discretion and must assess if definitive shortfall information is obtained (para 11). Guideline expires for QE days on/after 1 Jul 2027.

Citation: PCG 2026/1 paras 2, 11, 13-24, Tables 1-2, Examples 1-2 (issued 28 Jan 2026), https://www.ato.gov.au/law/view/document?LocID=%22COG/PCG20261/NAT/ATO%22 (full text read 2026-08-02)

### Out-of-cycle payments [confidence: medium]

s 18C(2) item 2: QE of a kind determined by Commissioner legislative instrument under s 18C(3) (out-of-cycle payments, payments outside the employer's established payment timing/pattern/schedule, e.g. off-cycle bonuses, commissions, allowances, back-payments) may be received up to the end of the usual period for the FIRST standard QE day after the current QE day, i.e. 7 business days after the next regular payday. The instrument is the Superannuation Guarantee (Administration) (Out-of-Cycle Qualifying Earnings) Determination 2026, consulted as draft LI 2026/D3 (May 2026), stated commencement 1 Jul 2026.

Citation: SGAA s 18C(2) item 2, s 18C(3) (text read 2026-08-02); draft LI 2026/D3 https://www.ato.gov.au/law/view/view.htm?docid=%22OPS%2FLI2026D3%2F00001%22, seen 2026-08-02

### Exceptional circumstances determinations [confidence: high]

s 18C(2) item 3 + s 18C(4): the Commissioner may by legislative instrument determine kinds of employers affected by prescribed exceptional circumstances, prescribed by reg 13 as (a) natural disasters and (b) widespread outages of ICT services or other technology platforms supporting contributions. Covered employers may have contributions received before the LATER of: (a) end of the extended usual period for the QE day (20th business day after QE day), and (b) end of 20 business days starting the day after the determination is made. Determinations can operate retrospectively.

Citation: SGAA s 18C(2) item 3, s 18C(4) (Act text read 2026-08-02); F2026L00133 reg 13 (text read 2026-08-02)

### (3) Under-18 exemption [confidence: high]

A 'part-time employee who is under 18' is a prescribed excluded employee, so their earnings are not qualifying earnings, so no SG is payable (reg 11(f), made for SGAA s 10A(3)(b)(i)). 'Part-time employee' takes the existing SGAA s 6(1) meaning (employed to work not more than 30 hours per week). ATO administers this week-by-week: SG payable only for weeks the under-18 works more than 30 hours. The exemption is unchanged in substance from pre-payday-super law.

Citation: F2026L00133 Sch 1, reg 11(f) of SGA Regulations 2018 (text read 2026-08-02); ATO: https://www.ato.gov.au/businesses-and-organisations/super-for-employers/paying-super-on-payday/what-payments-are-qualifying-earnings (snippet seen 2026-08-02)

### (3) Private/domestic workers exemption [confidence: high]

Payments under a contract for employment of not more than 30 hours per week in work wholly or principally of a domestic or private nature are excluded from qualifying earnings (reg 12(1)(j)). Unchanged in substance from prior law. Other reg 12 exclusions: parental leave pay, certain community-service and ADF-reserve absences, fringe benefits, certain non-resident/overseas work, Aged Care Registered Nurses' Payment-funded amounts, international social security agreement carve-outs.

Citation: F2026L00133 Sch 1, reg 12(1)(a)-(j) of SGA Regulations 2018 (text read 2026-08-02)

### (3) Contractors deemed employees [confidence: high]

Persons working under a contract wholly or principally for their labour remain deemed employees (SGAA s 12(3), unchanged), and payments under such contracts in respect of the person's labour ARE qualifying earnings (s 10A(1)(d)). PCG 2026/1 confirms 'employee' covers the extended definitions in s 12(2)-(11). The payday deadlines apply to their QE days like any employee.

Citation: SGAA s 10A(1)(d), s 12(3) (Act text read 2026-08-02); PCG 2026/1 para 5

### (3) Defined benefit members [confidence: high]

For DB members covered by a benefit certificate, the employer's obligation is met by a NOTIONAL contribution (QE x notional employer contribution rate) treated as received ON the QE day, i.e. always on time; the 7-business-day clock is irrelevant for DB interests (s 18A(3); note to s 18C(1)). Actual cash contributions to a DB interest are NOT 'eligible contributions' (s 18A(1)(a)(iii)). s 20B also shields certain DB schemes (surplus >=110%, max accrued benefit, benefit-not-affected) from choice loading. A checker should exclude DB-interest lines from lateness testing.

Citation: SGAA s 18A(1)(a)(iii), s 18A(3), s 20B (Act No. 57 of 2025 text read 2026-08-02)

### (3) Maximum contributions base: now ANNUAL [confidence: high]

From 1 Jul 2026 the MSCB is annual, per employer, per employee: (basic concessional contributions cap x 100 / charge percentage), rounded DOWN to the nearest $10 (s 10A(5)). For 2026-27: cap $32,500, charge % 12 → MSCB $270,830. Mechanism (s 10A(6)): once cumulative QE paid by that employer to that employee in the financial year exceeds the base, the excess portion of the tipping payment (and all of any later payment) is treated as nil QE, with no per-payday or per-quarter proration. A checker must track cumulative FY QE per employer-employee pair.

Citation: SGAA s 10A(5)-(6) (Act text read 2026-08-02); ATO: https://www.ato.gov.au/businesses-and-organisations/super-for-employers/paying-super-on-payday/what-payments-are-qualifying-earnings/maximum-contributions-base ($270,830, snippet seen 2026-08-02)

### (3) High-income opt-out [confidence: high]

Employer shortfall exemption certificates continue under payday super, relocated to SGAA s 17C (formerly s 19AB): where a certificate covers the employer/employee, the individual SG amount is nil for covered QE days (multi-employer high earners).

Citation: SGAA s 17C (Act No. 57 of 2025 Sch 1 item 4 amends the s 6(1) definition to point to s 17C; text read 2026-08-02)

### (4) Small-employer concessions: none by size [confidence: high]

There is NO small-employer carve-out, no size-based extension, and no statutory first-year penalty moratorium. The only transitional accommodations are: (a) PCG 2026/1 risk-zone compliance approach (1 Jul 2026-30 Jun 2027 only, applies to ALL employers); (b) reg 13C(3): for QE days from 1 Jul 2026 to 30 Jun 2028 the 24-month 'clean history' lookback is treated as starting 1 Jul 2026, so virtually all employers qualify for the administrative uplift reduction from 60% to 40%; (c) the SBSCH (small-business clearing house) CLOSED: last use 30 Jun 2026, new registrations stopped 1 Oct 2025, so small employers must use payroll-software/commercial/fund clearing channels, and clearing-house transit time is the employer's risk because receipt by the fund is what counts.

Citation: PCG 2026/1 (28 Jan 2026); F2026L00133 reg 13C(3) (text read 2026-08-02); ATO SBSCH closure: https://www.ato.gov.au/businesses-and-organisations/small-business-newsroom/the-small-business-superannuation-clearing-house-is-closing (seen 2026-08-02)

### SG charge structure (for exposure estimates) [confidence: high]

SG shortfall for a QE day = (a) total individual FINAL SG shortfalls + (b) total individual notional earnings components + (c) administrative uplift + (d) total choice loadings (s 16B(2)). Base shortfall = 12% x QE minus on-time contributions (ss 17A(2), 18C(1)). Late contributions made before assessment reduce the final shortfall (s 18D, 'late period' s 6(1)). Notional earnings = daily compounding at the GIC rate (s 8AAD TAA 1953) on the shortfall during the late period (s 19A). Administrative uplift = 60% of (final shortfalls + notional earnings) (s 19B(1)), reduced by 20 points for clean 24-month history (reg 13C) and by 40/35/30/15 points for a voluntary disclosure statement lodged within 30/60/120/120+ days of the QE day (reg 13D), floor 0%. Choice loading = lower of 25% of offending contributions and the $1,200 choice loading limit per notice period (ss 20A, 20C(1)). NOTE: enacted limit is $1,200, not the old $500.

Citation: SGAA ss 16B(2), 17A(2), 18C, 18D, 19A, 19B, 20A, 20C(1) (Act No. 57 of 2025 text read 2026-08-02); F2026L00133 regs 13A-13D (text read 2026-08-02)

### SGC deductibility change [confidence: medium]

ITAA 1997 s 26-95 (denying deduction of SG charge) and s 290-95 were repealed by Act No. 57 of 2025 Sch 1 items 80 and 92, and the s 12-5 'superannuation guarantee charge' table entry removed (item 79). Firm commentary (Hall & Wilcox) reads this as SG-charge amounts potentially becoming deductible from 1 Jul 2026 under general provisions. Treat as interpretation, not settled, and do not hard-code in the tool.

Citation: Act No. 57 of 2025 Sch 1 items 79, 80, 92 (text read 2026-08-02); https://hallandwilcox.com.au/news/payday-super-starts-1-july-2026-what-employers-need-to-do-now/ (seen 2026-08-02)

### July 2026 transition ordering [confidence: high]

Old quarterly law continues for quarters ending before 1 Jul 2026 (final quarterly payment due 28 Jul 2026). A contribution made 1-28 Jul 2026 while an old-law shortfall exists for the Jun-2026 quarter is applied FIRST to that old-law quarter; only the remainder can count for new-regime QE days (Sch 1 item 186). Pre-1 Jul 2026 contributions not already applied under old law can count under the 12-month lookback (item 185(3)). A checker parsing Jul-2026 pay runs must not double-count these contributions.

Citation: Act No. 57 of 2025 Sch 1 Part 3, items 185-186 (text read 2026-08-02)

### Draft ATO guidance in circulation [confidence: medium]

Draft (non-final, not binding) guidance as at research date: LCR 2026/D1 (qualifying earnings), LCR 2026/D2 (contribution timing/clearing arrangements per Clayton Utz), LCR 2026/D3, and draft LI 2026/D3 (out-of-cycle determination). PCG 2026/1 is FINAL (issued 28 Jan 2026, replacing draft PCG 2025/D5).

Citation: ATO legal database entries seen via search 2026-08-02; https://www.claytonutz.com/insights/2026/june/payday-super-frequently-asked-questions (seen 2026-08-02)

### Open ambiguities in this lane

- Out-of-cycle determination final status unverified: LI 2026/D3 (SG (Administration) (Out-of-Cycle Qualifying Earnings) Determination 2026) was in consultation to late May 2026 with stated commencement 1 Jul 2026; I could not confirm final registration on legislation.gov.au as at 2 Aug 2026 (ATO pages block automated fetch). Tool must check the registered instrument before applying the next-regular-payday deadline to off-cycle payments; conservative default = plain 7-business-day deadline, with the extension shown as 'possible relief'.
- Business-day calendar engineering: s 6(1) requires excluding any day that is a public holiday for the WHOLE of any State/ACT/NT, so a merged national calendar (e.g. WA Day affects NSW employers). Part-day holidays (e.g. Christmas Eve 7pm-12am in SA/QLD/NT) and regional holidays (e.g. Royal Queensland Show, Melbourne Cup where not state-wide) are NOT excluded. Melbourne Cup and some others are state-wide in some jurisdictions and not others, so the tool needs a curated, year-versioned holiday table and a user override.
- Under-18 test wording vs practice: reg 11(f) excludes 'a part-time employee who is under 18' (definition = EMPLOYED TO WORK <=30 h/week, a contractual test), while ATO guidance and payroll vendors apply an actual-hours week-by-week (Mon-Sun) test. Tool should default to ATO weekly-hours practice but disclose the divergence.
- New-employee window edge: s 18C(2) item 1 attaches to 'the first eligible contribution made to a particular fund' and contributions are applied in order received (s 18C(1)(b)), so where multiple early paydays and contributions interleave, which QE day gets the 20-business-day period can be non-obvious. Safest tool model: extended usual period on the first QE day after commencement (or after a fund switch) for the destination fund, with item 4 propagating the latest due day to later QE days whose usual periods end earlier; flag affected rows rather than silently passing them.
- 'Received' timing: the statutory test is receipt by the fund (and allocability), never the date the employer initiated payment, and not clearing-house receipt (SBSCH is gone; no equivalent safe harbour for commercial clearing houses). A CSV of employer payment dates cannot prove compliance; tool should report 'paid date + estimated clearing lag' as at-risk, and only 'fund receipt date' as definitive.
- Fund-rules overlay: some funds (e.g. CSC's PSSap/ADF Super) require contribution each payday under their own rules, so the SGAA 20-business-day extension is practically unavailable to those employers. Tool should disclaim that it tests SGAA/SGC exposure only, not fund deeds, EBAs, or industrial instruments (PCG 2026/1 para 3 makes the same point).
- Administrative uplift for exposure estimates is scenario-dependent (60/40/25/20/5/0% depending on reg 13C clean-history and reg 13D voluntary-disclosure timing) and notional earnings depend on the quarterly GIC rate (s 8AAD TAA), so the tool should output a range with stated assumptions, not a single figure, and must maintain a GIC rate table.
- SGC deductibility post-repeal of ITAA s 26-95 is commentary-level interpretation; do not state it as settled in tool output.
- 2026-27 MSCB $270,830 rests on the $32,500 basic concessional cap. Verify both against the ATO rates pages at release time (ATO pages 403 automated fetch; figure corroborated by ATO page snippet + formula + multiple firm bulletins on 2026-08-02).
- PCG 2026/1 protects only against ATO compliance-resource allocation. It does not switch off SGC liability (para 11: Commissioner MUST assess if definitive shortfall information obtained). Tool wording must say 'low ATO review risk', never 'no liability'.

## Lane: holidays

### Statutory business-day definition (the calendar the tool must implement) [confidence: high]

SGAA 1992 s 6(1) (inserted by Treasury Laws Amendment (Payday Superannuation) Act 2025, No. 57 of 2025, Sch 1 item 3) defines: "business day means a day other than: (a) a Saturday or a Sunday; or (b) a day which is a public holiday for the whole of: (i) any State; or (ii) the Australian Capital Territory; or (iii) the Northern Territory." This is ENACTED LAW (Royal Assent 6 Nov 2025, operative 1 Jul 2026). Consequence: ONE national calendar for every employer regardless of location. A whole-of-jurisdiction holiday in ANY of the 8 jurisdictions (6 states + ACT + NT) removes that day from the count nationally. External territories are not listed and are irrelevant.

Citation: Superannuation Guarantee (Administration) Act 1992 s 6(1), as amended by Act No. 57 of 2025 Sch 1 item 3, quoted verbatim from authorised Act text at https://www.legislation.gov.au/C2025A00057/asmade/2025-11-06/text/1/pdf (registered 17/11/2025), seen 2026-08-02

### Deadline machinery the calendar feeds ('usual period') [confidence: high]

SGAA s 6(1) (Sch 1 item 10): "usual period, for a QE day and an employer, means the period: (a) starting on the QE day; and (b) ending on the seventh business day after the QE day." Count semantics: the QE day (payday) itself is day 0 even if it is a business day; the deadline is end of the 7th business day AFTER it. s 18C(1)(c)(i) counts an eligible contribution only if RECEIVED by the fund during that period (receipt by fund, not payment initiation). s 18C(1)(c)(ii) also counts contributions received in the 12-month period ending the day before the QE day (advance payments).

Citation: SGAA s 6(1) definition of 'usual period' and s 18C(1)(c), quoted from https://www.legislation.gov.au/C2025A00057/asmade/2025-11-06/text/1/pdf pp. 6, 18, seen 2026-08-02

### 20-business-day extensions the calendar must also serve [confidence: high]

SGAA s 6(1): "extended usual period" = QE day to the 20th business day after the QE day. Applies via the s 18C(2) table: item 1, first eligible contribution by the employer to a particular fund/RSA for that employee (new/recommenced employee, or after switching funds); item 2, out-of-cycle qualifying earnings of a kind determined under s 18C(3); item 3, exceptional-circumstances determinations under s 18C(4) (deadline = later of extended usual period or 20 business days starting the day after the determination); item 4, alignment with an earlier contribution's latest due day. Same national business-day calendar is used for the 20-day count.

Citation: SGAA s 6(1) ('extended usual period') and s 18C(2)-(4), quoted from https://www.legislation.gov.au/C2025A00057/asmade/2025-11-06/text/1/pdf pp. 4, 18-20, seen 2026-08-02

### Regional public holidays are business days [confidence: high]

Regional/local holidays (Royal Queensland Show 'Ekka', Brisbane area only; QLD regional show days; Royal Hobart Show/Regatta; Geelong Cup) are NOT 'a public holiday for the whole of' a state, so they remain business days and do NOT pause the 7/20-day count, even for an employer located in that region. ATO guidance states this expressly, using Royal Hobart Show Day as its example: a state/territory-wide holiday anywhere in Australia is not a business day 'even if your fund is not located in that state or territory', but regional holidays still count as business days.

Citation: SGAA s 6(1)(b) ('for the whole of'); ATO 'Payment deadlines for Payday Super' https://www.ato.gov.au/businesses-and-organisations/super-for-employers/paying-super-on-payday/payment-deadlines-for-payday-super and ATO 'Business days decoded' https://www.ato.gov.au/tax-and-super-professionals/for-superannuation-professionals/super-funds-newsroom/business-days-decoded-why-it-matters-for-your-fund, ATO wording seen via search snippets 2026-08-02 (ato.gov.au returns 403 to automated fetch; verify quotes in a browser before publishing)

### Weekend definition edge case: settled by statute [confidence: high]

No engineering needed for weekend variation: the statute hard-codes Saturday and Sunday in the definition itself (s 6(1)(a)), so state-level weekend conventions are irrelevant. Separately, no Australian state or territory uses a non-Sat/Sun weekend. Saturday-only holidays (e.g. Easter Saturday) are already excluded as weekends; no double-count issue.

Citation: SGAA s 6(1) para (a), quoted from https://www.legislation.gov.au/C2025A00057/asmade/2025-11-06/text/1/pdf p. 3, seen 2026-08-02

### Fund-side business-day definitions differ: do not conflate [confidence: medium]

The ATO notes different parts of super law use different business-day definitions: fund-side processing rules use a location-based definition ('excludes weekends and any public holiday in the location where your fund operates'), unlike the employer's national SGAA s 6(1) definition. The checker computes the EMPLOYER deadline only and must use the national definition; do not reuse fund-side or Acts Interpretation Act s 2B ('place concerned') definitions.

Citation: ATO 'Business days decoded: why it matters for your fund' https://www.ato.gov.au/tax-and-super-professionals/for-superannuation-professionals/super-funds-newsroom/business-days-decoded-why-it-matters-for-your-fund, seen via search snippet 2026-08-02

### data.gov.au national public-holidays dataset: dead, do not depend on it [confidence: high]

The 'Australian Public Holidays Dates Machine Readable Dataset' on data.gov.au is titled '[INACTIVE]'; the Department of the Prime Minister and Cabinet stopped maintaining it and no further updates will be released. Latest combined resource covers 2021-2025 only, with no 2026 or 2027 data. CSV via CKAN still downloadable but useless for this tool's horizon. No maintained federal machine-readable public-holiday API exists as of 2026-08-02; the authoritative sources are the 8 state/territory government pages (gazette/proclamation-based, mostly HTML, typically current year +1).

Citation: https://data.gov.au/data/dataset/australian-holidays-machine-readable-dataset, title '[INACTIVE]' and DPM&C non-maintenance note confirmed across multiple search results 2026-08-02 (page returns 403 to automated fetch; verify in a browser before publishing)

### python-holidays package: state of maintenance [confidence: high]

PyPI package 'holidays' v0.101 released 20 Jul 2026; maintained by the Vacanza team (repo moved from dr-prodigy to the vacanza org); release cadence roughly fortnightly; requires Python >=3.10. Australia: all 8 subdivisions (ACT NSW NT QLD SA TAS VIC WA); three categories PUBLIC, BANK, HALF_DAY. Actively maintained.

Citation: https://pypi.org/project/holidays/ and https://raw.githubusercontent.com/vacanza/holidays/main/holidays/countries/australia.py, seen 2026-08-02

### python-holidays: Ekka gotcha (must filter, immediate relevance) [confidence: high]

python-holidays puts 'The Royal Queensland Show' in the QLD PUBLIC category (rule: 1st Wednesday from Aug 10; hardcoded 2020-08-14 and 2021-10-29 COVID exceptions), with no comment that it is Brisbane-area only. Under SGAA s 6(1) it is NOT whole-of-state, so naive use of Australia(subdiv='QLD') PUBLIC wrongly removes a national business day. In 2026 that Wednesday falls 12 Aug 2026, inside the first weeks of the live regime, so an unfiltered calendar mis-dates deadlines immediately. The generator must drop Ekka (and verify no other sub-state entries sit in PUBLIC).

Citation: https://raw.githubusercontent.com/vacanza/holidays/main/holidays/countries/australia.py (code quoted from file), seen 2026-08-02; regional status corroborated by ATO regional-holiday guidance and https://www.ajbuckingham.com.au/payday-super-part-1-understanding-the-new-law/

### python-holidays: proclaimed-yearly holidays are the accuracy risk [confidence: high]

Two whole-of-state holidays that DO affect the national calendar are proclaimed yearly and only rule-approximated by python-holidays: (1) VIC Grand Final Day (Friday before AFL Grand Final), fallback rule 'day prior to last Saturday of September' with hardcoded exceptions 2015/2016/2020; 2026-27 dates are rule-derived, not confirmed, and depend on the AFL fixture; (2) WA King's Birthday, proclaimed annually (usually late Sep), package has needed hardcoded corrections (e.g. 2024). One-off proclamations (days of mourning, special holidays) only appear after a package release. Any bundled calendar must be cross-checked against state government pages per year, and rule-derived future dates flagged unverified.

Citation: https://raw.githubusercontent.com/vacanza/holidays/main/holidays/countries/australia.py (Grand Final code quoted), seen 2026-08-02

### python-holidays: categories align with statutory treatment [confidence: high]

Helpful separations: NSW and ACT August Bank Holidays are in the BANK category (bank holidays are not general public holidays, so correctly excluded from a PUBLIC-only query, they are business days); part-day holidays (SA Christmas Eve and New Year's Eve from 7pm since 2012; NT both from 7pm since 2016; QLD Christmas Eve from 6pm since 2019) are in the HALF_DAY category, so a PUBLIC-only query excludes them, matching the recommended default treatment. Royal Hobart Regatta is not implemented at all (harmless, being regional).

Citation: https://raw.githubusercontent.com/vacanza/holidays/main/holidays/countries/australia.py, seen 2026-08-02

### Recommended architecture: bundled curated data file + override file; python-holidays as dev-time generator only [confidence: high]

Ship a bundled national non-business-day table (union of whole-of-jurisdiction holidays across the 8 jurisdictions, calendar years 2026-2028) as a data file in the repo, generated by a checked-in script that queries python-holidays (pinned version, PUBLIC category only, Ekka filtered out) and is then cross-checked line-by-line against the 8 official state/territory pages before release. Ship a user override file (add/remove dates) for late proclamations and disputed days. Do NOT make python-holidays a runtime dependency: (a) compliance output must not change when a transitive dependency updates; (b) raw package output is provably wrong for this statute (Ekka) so runtime output would need runtime filtering anyway; (c) one-off proclamations need overrides regardless. At runtime, warn when any computed deadline falls beyond the bundled table's verified horizon. Test cases to include: WA King's Birthday (late Sep) pauses the clock for a Sydney employer; Ekka Wednesday (12 Aug 2026) does NOT pause it for a Brisbane employer; differing state Labour Days all pause it nationally.

Citation: Engineering recommendation derived from SGAA s 6(1) (national union calendar) + python-holidays source review + data.gov.au dataset inactivity, all cited above, 2026-08-02

### Melbourne Cup Day: probably a non-business day, with a caveat [confidence: medium]

Melbourne Cup Day (first Tuesday of November) is generally a statewide VIC public holiday and practitioner guidance treats it as a non-business day nationally. Caveat: under Victorian law, non-metropolitan districts can substitute a local holiday for Melbourne Cup Day, so 'for the whole of' Victoria is arguable in years where substitutions occur. Recommended default: treat as non-business day (matches common treatment and python-holidays), document the caveat, make it overridable.

Citation: Public Holidays Act 1993 (Vic) substitution mechanism, NOT verified this session; practitioner treatment per https://www.ajbuckingham.com.au/payday-super-part-1-understanding-the-new-law/ seen 2026-08-02

### Payday Super Regulations exist and were not reviewed in this lane [confidence: medium]

Treasury Laws Amendment (Payday Superannuation) Regulations 2026 (F2026L00133) were made and may prescribe details (e.g. exceptional-circumstances kinds under s 18C(4), administrative uplift reduction methods). Nothing found suggests they alter the business-day definition, but they were not read in this lane, so another lane or the design phase should confirm before publication.

Citation: https://www.legislation.gov.au/F2026L00133/asmade/downloads, seen 2026-08-02 (existence only; text not reviewed)

### Open ambiguities in this lane

- Part-day holidays (SA and NT from 7pm on 24 and 31 Dec; QLD from 6pm on 24 Dec): the statute excludes 'a day which is a public holiday for the whole of' a jurisdiction: these days are statewide geographically but holidays for only part of the day. Neither the Act, the ATO snippets found, nor firm bulletins resolve whether such a day counts as a business day. Recommended default: count them as BUSINESS days (a part-day holiday arguably does not make the day 'a public holiday', and this errs toward an earlier computed deadline, so the tool never calls a genuinely late payment on-time). Must be user-overridable and disclosed in output; they only ever affect late-December pay runs.
- Melbourne Cup Day 'whole of Victoria' question: Victorian districts can substitute local holidays for Melbourne Cup Day, so in substitution years it may not be a holiday 'for the whole of' the State. Default non-business day per common practice, but the tool should disclose this and allow override. Note the two ambiguities pull in opposite directions, so there is no single 'conservative' setting, which is exactly why both need surfacing rather than silent resolution.
- Whether the ATO publishes (or will publish) an official payday-super business-day calendar is unconfirmed, and ato.gov.au blocks automated fetching, so ATO wording in this report came from search snippets. Before publication, open the three cited ATO pages in a browser and re-verify the quotes; if the ATO ships an official calendar, the bundled table should defer to it and cite it.
- Rule-derived 2027+ dates for proclaimed-yearly holidays (VIC Grand Final Friday, WA King's Birthday) are unverified until each state gazettes them; the bundled table should mark such dates provisional and the CLI should warn when a deadline calculation depends on one.
- The Payday Superannuation Regulations 2026 (F2026L00133) and any Commissioner legislative instruments under s 18C(3) (out-of-cycle earnings kinds) and s 18C(4) (exceptional circumstances) were not reviewed in this lane; the 20-day pathways the tool models as exceptions depend partly on those instruments existing and their terms.

## Independent verification pass

### [CONFIRMED] Payday super is ENACTED law: Treasury Laws Amendment (Payday Superannuation) Act 2025 (No. 57 of 2025) + Superannuation Guarantee Charge Amendment Act 2025 (No. 58 of 2025), Royal Assent 6 Nov 2025, effective for QE days from 1 Jul 2026; regulations F2026L00133 registered 23 Feb 2026

Independent: legislation.gov.au C2025A00057/asmade result title; aph.gov.au bill r7374 (SGC Amendment Act No 58 of 2025, assent 6 Nov 2025); KPMG Flash Alert 2025-268 'Payday Superannuation Legislation Receives Royal Assent'; Alvarez & Marsal royal-assent bulletin; IPA technical resource PDF (publicaccountants.org.au, v3 Mar 2026, extracted locally): 'received Royal Assent on 6 November 2025' and 'the PDS Regs were registered on 23 February 2026'. Minor: one researcher lane says regs 'made 19 February 2026', so use the registration date (23 Feb 2026, F2026L00133) in citations; both can coexist (made vs registered) but I could only independently verify registration. All seen 2026-08-02.

### [CONFIRMED] Core deadline: contribution is on time only if RECEIVED by the fund (and allocatable) during the 'usual period' starting on the QE day and ending on the 7th business day after the QE day; pre-payments received in the 12 months ending the day before the QE day also count

PCG 2026/1 full primary text (extracted from mirrored PDF, hubspot mirror of ato.gov.au original) para 9: on-time contributions are eligible contributions made within 'the period that is 7 business days after the day the QE is paid (the usual period)' or 'the 12-month period ending on the day before the current QE day'; IPA PDF: 'able to be allocated to the employee's account before the end of the seventh business day after the QE day... the fund must have received the money and accurate data'; ATO 'Payment deadlines for Payday Super' page content via search (ato.gov.au 403s direct fetch). No contrary evidence found; no calendar-day variant survives into the enacted law.

### [CONFIRMED] 'Business day' is ONE national calendar: excludes Sat/Sun and any public holiday applying to the WHOLE of any State, the ACT or NT, regardless of employer location; regional/part-state holidays (e.g. Royal Hobart Show Day, Brisbane Ekka) remain business days

ATO 'Business days decoded: why it matters for your fund' (ato.gov.au super-funds-newsroom, via search content 2026-08-02): a state/territory-wide public holiday is not a business day 'even if you are not located in that state or territory'; regional public holidays (Royal Hobart Show Day example) still count as business days. IPA PDF: business day = day other than Sat/Sun or 'a public holiday for the whole of any State or Territory'. Caveat for publication: legislation.gov.au and the ATO Act PDF 403 automated fetchers, so the researchers' verbatim s 6(1) quote could not be re-read this session, so eyeball the statutory text in a browser before shipping the exact quote.

### [CONFIRMED] Clock trigger: the QE day is the day the employer actually PAYS qualifying earnings (s 17A(1)), not the payslip period or pay-period end; every payment day is its own QE day with its own deadline

PCG 2026/1 primary text fn 6: QE day is 'Defined in subsection 17A(1). It is a day on which the employer makes a payment of qualifying earnings to or for an employee.' IPA PDF: 'A QE day is the day on which the employer pays QE to or for an employee.' LCR 2026/D3 (ato.gov.au legal database, via search): amounts paid on the same QE day are aggregated. Consistent across primary and secondary sources; no contrary reading found.

### [CONFIRMED] Obligation met on FUND RECEIPT (with data sufficient to allocate), not on payment to a commercial clearing house; clearing-house transit time is the employer's risk; no general deemed-receipt safe harbour

ATO pages via search: contributions 'must be received by your employees' super funds within 7 business days... with enough information to allocate the contributions'; IPA PDF explicitly: SBSCH users were treated as satisfying the obligation on SBSCH receipt but 'This treatment does not apply for users of commercial clearing houses'; Norton Rose Fulbright: 'received by the employee's super fund... not just sent'. Also confirmed: trustee allocate-or-refund window cut from 20 to 3 business days (IPA; SIS reg change). Adversarial note: one garbled search summary implied a 20-business-day allowance 'if you use a commercial clearing house', traced to conflation with the new-employee extension; no clearing-house extension exists in any source. The VDS deemed-receipt rule (payment day + 7 business days) exists only for NEC calculation when a disclosure states payment day only (IPA PDF), never a compliance safe harbour, matching the researchers' framing.

### [CONFIRMED] SG rate: charge percentage is 12% of qualifying earnings for 2026-27; 12% since 1 Jul 2025, final legislated rate, no scheduled increases

PCG 2026/1 primary text fn 8: individual SG amount = 'qualifying earnings multiplied by 0.12 (the charge percentage (12) divided by 100)'; ATO small-business newsroom 'The final SG rate increase is coming on 1 July' (12% from 1 Jul 2025, final scheduled increase); IPA PDF: 'no amendment to the mandatory SG rate of 12 per cent'.

### [CONFIRMED] New SGC composition and numbers: (1) individual final SG shortfalls (base shortfall minus late contributions before assessment, offset automatic, applied to earliest shortfall QE day, excess carried forward 12 months); (2) notional earnings compounding DAILY at the GIC rate; (3) administrative uplift 60% of (1)+(2), reduced -20pp clean 24-month history and -40/-35/-30/-15pp by VDS timing (≤30/31-60/61-120/>120 days), stackable, floor 0%; (4) choice loading 25% capped $1,200 per notice period (up from $500); SGC payable on the day the assessment is made; old $20/employee admin fee, 10% nominal interest and Part 7 200% penalty abolished

IPA PDF (extracted in full): four components listed; NEC = notional sum × GIC rate compounding daily; uplift 'starts at 60 per cent'; choice loading 'limit will increase from the current $500 to $1,200 per notice period', rate 25%; 'The SG charge is payable on the day the assessment is made'; LPP table 0%/25%/50% (50% if previously liable in the 24 months ending the day after the current notice payment period); Part 7 penalty abolished. ATO 'The new super guarantee charge' page content via search: uplift 'initially 60%', choice loading 'maximum of $1,200 for each notice period'. Reduction schedule: Grant Thornton 'Payday Super regulations released' + Clayton Utz FAQ via search: VDS within 30 days = -40pp (60→20), clean-history = -20pp (60→40), stackable to 0%. Caveat: the exact SGAR reg numbers (13A-13D, and the 13C(3) transitional lookback treated as starting 1 Jul 2026 for QE days to 30 Jun 2028) could not be re-read against primary reg text this session (legislation.gov.au 403), so substance is confirmed but the numbering is PLAUSIBLE only; verify reg numbers in a browser before citing them in docs.

### [CONFIRMED] Notional earnings accrue from the DAY AFTER the last day an on-time eligible contribution could be received (end of usual/extended period), not from the QE day, and stop at the earlier of shortfall reaching nil or the day before/of assessment

LCR 2026/D3 worked example (ato.gov.au legal database via search, 2026-08-02): for an 8 Jun 2027 QE day whose usual period ends 18 Jun 2027, 'notional earnings component ... begins to accrue from 19 June 2027 (the beginning of the late period)'; A&M bulletin: NEC 'will cease accruing as soon as sufficient contributions... reduce an employee's final SG shortfall to nil, even if this is before the SG shortfall is assessed'. The Scalesuite claim that accrual starts on the QE day is contradicted by the ATO example, so the researchers were right to reject it. Note LCR 2026/D3 remains DRAFT; the start-day rule also follows from the statutory 'late period' definition, so risk of change at finalisation is low but re-check.

### [CONFIRMED] New employee / new fund exception: the FIRST eligible contribution by the employer to a particular fund for the employee (new/recommenced employment, or fund switch) gets the 'extended usual period': QE day to the 20th business day after the QE day; later paydays inside that window inherit the extended end date (table item 4)

IPA PDF: 'The first time that an employer makes a contribution to an employee's superannuation fund — a new employee, or an employee changes fund — there is an extension until the end of the 20th business day after the QE day'; ATO payment-deadlines page + Employment Hero/Tanda FAQs via search: received 'within 20 business days of their first payday', 7 business days thereafter. Item 4 overlap rule corroborated by PCG 2026/1 primary text fn 9: allowable longer period 'where the usual period for one QE day ends before an extended usual period for an earlier one'. Trigger is the QE day, not stapling/choice-form resolution, consistent everywhere.

### [CONFIRMED] Maximum contributions base is ANNUAL per employer-employee from 1 Jul 2026: MCB = concessional cap × 100/12 rounded down to nearest $10; 2026-27 cap $32,500 → MCB $270,830; once cumulative FY QE from that employer exceeds it, excess is nil QE (cumulative tracking, no proration)

ATO contributions-caps page via search: concessional cap $32,500 from 1 Jul 2026 (AWOTE indexation, $2,500 increments); Rest Super MSCB page: 'The MSCB for 2026–27 is $270,830 for the year' (max SG $32,499.60); ATO MCB page (paying-super-on-payday path) title/snippet; Pitcher Partners 'hidden traps in changes to Maximum Contribution Base' (quarterly $62,500 → annual $270,830). Arithmetic checks: 32,500×100/12 = 270,833.33 → $270,830. ADVERSARIAL FINDING supporting a design rule: the IPA March 2026 resource computed $250,000 assuming the cap stayed $30,000, a pre-indexation figure now stale. MCB and cap are yearly indexed parameters; the tool must store them per-FY, never as constants.

### [CONFIRMED] PCG 2026/1 (first-year compliance approach) is FINAL, issued 28 Jan 2026, applies ONLY to QE days 1 Jul 2026–30 Jun 2027; low/medium/high risk zones as described (low = attempted on-time, fixed as soon as reasonably practicable, final shortfalls nil; medium = shortfalls nil by 28 days after quarter end; high = otherwise); Commissioner has no discretion to waive the law (para 11)

Full primary text of PCG 2026/1 read this session (mirrored PDF): 'Commissioner of Taxation 28 January 2026'; paras 2, 12-13 (QE days 1 Jul 2026–30 Jun 2027 inclusive, 'will not apply to a QE day that occurs on or after 1 July 2027'); Tables 1-2 match the researchers' description verbatim; para 11: no discretion, 'required to apply the law' even for low-risk employers (citing Macquarie Bank [2013] FCAFC 119); previous draft PCG 2025/D5. Examples 1-2 confirm the fund-rejection low-risk scenario.

### [CONFIRMED] Out-of-cycle exception: Commissioner's determination under s 18C(3) is FINAL and in force: Superannuation Guarantee (Administration) (Out-of-Cycle Qualifying Earnings) Determination 2026 (LI 2026/20), commenced 1 Jul 2026, covering allowances, commissions, bonuses, payments in advance, back payments made outside the employer's established payment timing/pattern/schedule; deadline rolls to end of the usual period for the next standard QE day

IFPA 3 July 2026 update (fetched in full): the Determination 'has been made' as of 30 Jun 2026; ATO materials via search identify it as LI 2026/20 made under s 18C(3), commencing 1 Jul 2026, with the established-timing/pattern/schedule test; IPA PDF confirms the roll-forward mechanics ('until the end of the usual period for the next QE day'). Researchers' [medium] confidence can be raised for existence/commencement. Gap: I could not locate its Federal Register (F2026L…) number, so cite it as LI 2026/20 and capture the FRL number in a browser before publication.

### [UNRESOLVED] ATO interpretive guidance status as at 2 Aug 2026: LCR 2026/D1-D4 (issued 18 Mar 2026, consultation closed 1 May 2026) are still DRAFT

Confirmed still draft as of early July 2026: IFPA 3 Jul 2026 update lists withdrawn/updated guidance (SGD 2003/2W, SGR 2009/2W, PS LA 2007/1(GA), PS LA 2021/3) but 'contains no mention of finalised LCR 2026/D1-D4'; no final LCR 2026/1-4 appears in any search result. However the PwC August 2026 Monthly Tax Update (the one source that would cover late-July finalisation) returned 403, so status in the last ~4 weeks is unverified. Tool docs must label LCR-derived details as draft guidance and this needs a manual browser check of the ATO legal database immediately before publication.

### [CONFIRMED FROM PRIMARY SOURCE] GIC rate 11.43% p.a. (daily 0.03131507%) for 1 Jul–30 Sep 2026; resets quarterly; must be a dated parameter table

ATO, General interest charge (GIC) rates, read directly on 14 Aug 2026: Jul–Sep 2026 annual 11.43%, daily 0.03131507%; Apr–Jun 2026 annual 10.96%, daily 0.03002740%. The official page says it was last updated 5 Jun 2026 and that rates are updated quarterly. ADVERSARIAL FINDING: a cached/summarised version of the ATO new-SGC explainer still quotes 'currently 10.61%' (an old rate). ATO explainer pages can lag the quarterly table, so the tool must source GIC from the rates table only, never from explainer-page prose. Oct 2026+ rates do not exist yet; the tool needs a horizon warning. Source: https://www.ato.gov.au/tax-rates-and-codes/general-interest-charge-rates

### [CONFIRMED] SBSCH retired: no new registrations from 1 Oct 2025, last use 30 Jun 2026, gone as a channel from 1 Jul 2026

ATO small-business newsroom closure page, Xero SBSCH-closure guide, NFPAS and NSW Small Business Commissioner notices via search; IPA PDF: 'abolished from 1 July 2026. It ceased accepting new employers on 1 October 2025' (~250,000 affected employers).

### [CONFIRMED] SG charge fully tax-deductible for post-1 Jul 2026 QE days (all components); GIC on unpaid SGC and the late payment penalty NOT deductible; old-regime SGC stays non-deductible

IPA PDF deductibility table: deductible = on-time contributions, late contributions, SG charge; not deductible = late payment penalty, GIC. A&M bulletin: 'the SGC itself will be tax deductible... GIC and late-payment penalties will remain non-deductible' (repeal of ITAA 1997 ss 26-95/290-95 per Hall & Wilcox and the Act's Sch 1). The [exceptions] lane's caution ('treat as interpretation') is overly conservative for the headline rule, because multiple independent sources including the ATO's own explainer state deductibility plainly, but keep the tool's tax note phrased as general information, not advice.

### Load-bearing items the verifier found MISSING or unresolved

- Rounding of the individual SG amount: the assembled formula uses round(QE × 0.12) but no statutory or ATO rounding rule (cents vs nearest dollar, per-employee vs per-QE-day) was cited or verified. Do not hard-code rounding; compute in cents and flag. Check LCR 2026/D3 worked examples for the ATO's arithmetic before release.
- End-of-day / time-zone convention for 'end of the seventh business day': no source addresses whose midnight applies (fund's? AEST?) when a contribution lands late on the deadline day. Load-bearing for borderline receipts; document as an open ambiguity and have the tool treat deadline-day receipt as on time with a warning for near-midnight cases.
- Definition of 'notice period' for the $1,200 choice-loading cap (s 20C): the cap unit is cited but 'notice period' is never defined in the researched facts; required if the tool implements choice-loading estimates rather than making them an optional pass-through input.
- Whether any exceptional-circumstances determination (s 18C(4)) was actually made for Jul-Aug 2026 (e.g. a natural disaster or outage): the tool supports the mechanism but nobody checked for live determinations; a current determination would change deadlines for affected employers. Needs a pre-release browser check of the ATO/FRL and ideally a user-config flag.
- STP reporting obligation: employers must report qualifying earnings and super liability amounts through Single Touch Payroll each pay event (IPA PDF). Not in the researched facts; relevant as a checker warning (ATO detects lateness via STP + fund MATS matching) and for CSV column expectations.
- Federal Register number and exact conditions of the out-of-cycle determination (LI 2026/20): the 'circumstances' limbs (established timing/pattern/schedule test, and any exclusions for e.g. termination payments) were never read from the instrument text, only summarised. The tool's out-of-cycle logic and its termination-pay position rest partly on unread instrument text; read LI 2026/20 in a browser before publication.
- SGAR regulation numbering (regs 11-13D) and the reg 13C(3) transitional lookback wording: substance confirmed via Grant Thornton/Clayton Utz but primary reg text was unreachable this session (403). Verify section/reg numbers verbatim before they go in published citations.
- Late-July 2026 guidance sweep: ato.gov.au, legislation.gov.au, PwC and the ATO Act PDF all 403 automated fetchers, so anything published in the ~4 weeks before 2 Aug 2026 (LCR finalisations, new instruments, PCG amendments) is a blind spot. A manual browser session over the ATO legal database 'what's new' and FRL is required before the accountant's name goes on this.
- Verbatim statutory quotes (s 6(1) definitions, s 17A, s 18C, s 10A(5)-(6), s 36(4)): researchers claim verbatim verification from FRL downloads; this session could not re-open any primary legislative text (all 403). Their quotes are consistent with every secondary source checked, but 'payable on the day the assessment is made' and the s 36(3) deemed-receipt scope specifically rest on their reading alone plus IPA corroboration, so re-verify in a browser.
