# Audit fix round: payday-super-checker

Branch `fix/audit-findings`, from `ebc60f1`. Twelve commits, nothing pushed.
Suite: `python -m pytest` from the repo root, **329 passed** (300 at the start).

Every behavioural fix below was proved to have teeth: the fix was broken in the
way the finding describes, the covering test was confirmed to FAIL with the
actual assertion recorded, then the break was reverted and the test confirmed to
pass again.

---

## 1. The item-4 caveat named a deadline the line never had

`report._item4_seeded_by_unrecorded` re-derived the aligned line's own deadline
as `qe_day` plus 7 or 20 business days. That ignores the OUT_OF_CYCLE pathway and
the items 1 + 2 `max()`.

`Deadline` gained `own_due`. `apply_item4` records the pre-alignment date there
before it overwrites `due`; the caveat reports that value. `cal` is no longer
passed to the helper.

Files: `paydaysuper/deadlines.py`, `paydaysuper/report.py`.
Test: `tests/test_integration.py::test_item4_caveat_keeps_an_out_of_cycle_lines_own_deadline`.
An aligned out-of-cycle line riding the 27 Jul payday has its own deadline on
6 Aug; `qe_day + 7` would say 4 Aug.

Break: restored the `cal.add_business_days` re-derivation.

```
AssertionError: assert '2026-08-06' in 'this deadline is inherited from the QE day
2026-07-09, for which no payment is recorded. ... the deadline for this line is
2026-08-04 and any shortfall is larger than shown'
```

## 2. A nil row could still be LATE

The zero-amount guard was `and line.sg_amount > 0` on the UNPAID branch only, so
a 0.00 row with a late remittance or receipt date came out LATE and forced exit
code 2 with no exposure behind it.

The amount is now tested once, before the verdict ladder. A nil row gets its own
outcome (`UNKNOWN`, the existing "nothing to assess" bucket) and a note that it
records no SG.

File: `paydaysuper/report.py`.
Tests: `test_zero_amount_late_line_does_not_claim_a_receipt`,
`test_zero_amount_line_with_a_late_receipt_is_not_late`.

Break: restored `and line.sg_amount > 0` and disabled the new branch.

```
AssertionError: assert 'LATE' == 'UNKNOWN'
```

**One existing test was rewritten, not weakened.**
`test_zero_amount_late_line_does_not_claim_a_receipt` asserted
`"shortfall $0.00" in text`, which only holds while the nil row appears in the
exposure listing. That is the defect. Its real intent, the negative assertion
`"received, so the shortfall is nil" not in text`, is kept, and the test now also
asserts the verdict, the absent exposure block and exit code 0. It covers strictly
more than it did.

## 3. A nil row past its deadline was told the deadline had not passed

Same area. The nil row fell through to the not-yet-due branch and got its wording.

Split by `dl.due < as_at`: past the deadline it says the deadline passed but the
row records no SG; otherwise the not-yet-due wording stands.

File: `paydaysuper/report.py`.
Tests: `test_overdue_nil_row_is_not_told_the_deadline_has_not_passed`,
`test_nil_row_before_its_deadline_still_says_so`.

Break: same as finding 2.

```
assert any("the deadline passed on 2026-07-20" in c for c in r.caveats)
E       assert False
```

## 4. A next standard payday supplied without the out-of-cycle flag was ignored silently

`next_standard_qe_day` is only read inside the `out_of_cycle` branch and `csv_io`
does not cross-validate the two columns, so the row got the strict 7-business-day
deadline with nothing said.

`compute_due` now appends a caveat naming the item 2 deadline that would apply
with the flag set. A next payday that is not after the QE day gets its own caveat
rather than a nonsense date, since only the `out_of_cycle` path raises on that.

File: `paydaysuper/deadlines.py`.
Tests: `tests/test_deadlines.py::test_next_payday_without_the_flag_names_the_item_2_deadline`,
`::test_next_payday_without_the_flag_is_flagged_when_it_is_not_later`,
`::test_out_of_cycle_row_gets_no_missing_flag_caveat`.

Break: `elif line.next_standard_qe_day is not None:` -> `elif False:`.

```
assert caveat, dl.caveats
E       AssertionError: []
```

## 5. Past the calendar horizon the tool asserted verdicts it could not support

`check_horizon` only warned past 2028-12-31. Beyond that the holiday table is
empty, not merely incomplete, so every weekday counted as a business day and the
tool returned a definite LATE or ON_TIME with dollar figures on contributions
that were on time under holidays already legislated.

**Choice: force UNKNOWN, not refuse.** Refusing the QE day the way a pre-regime
QE day is refused would take the whole file down for one forward-dated payday, and
it would refuse rows whose verdict never consults the deadline at all. UNKNOWN
says exactly what is true and leaves every other row assessed.

Scope of the override: a verdict that turns on comparing a supplied date against
`dl.due`, that is the receipt-vs-due and remittance-vs-due branches. Two carve-outs,
both deliberate:

- **Pre-payments keep their verdict.** s 18C(1)(c)(ii) compares the receipt with
  the QE day and a 12-month calendar window. It never touches the business-day
  deadline, so the horizon cannot make it unknowable.
- **UNPAID keeps its verdict.** Nothing at all is recorded against the payday. No
  calendar shift can turn an unrecorded contribution into a paid one, and dropping
  it to UNKNOWN would hide the largest exposure the tool can see. The horizon
  caveat still rides on the row.

The warn-only caveat that still reaches unpaid, skipped and pre-payment rows was
reworded as instructed: it now says the calendar holds no holidays at all after
that date and weekends are the only non-business days it sees.

Files: `paydaysuper/calendar.py`, `paydaysuper/report.py`.
Tests: `test_receipt_past_the_calendar_horizon_is_not_called_late`,
`::..._is_not_called_on_time`, `test_remittance_past_the_calendar_horizon_is_not_called_at_risk`,
`test_a_deadline_inside_the_horizon_is_still_assessed`,
`test_prepayment_past_the_horizon_keeps_its_verdict`,
`test_horizon_caveat_says_the_calendar_holds_no_holidays`.

Break A: `past_horizon = dl.due > cal.verified_until` -> `past_horizon = False`.

```
AssertionError: assert 'LATE' == 'UNKNOWN'
AssertionError: assert 'ON_TIME' == 'UNKNOWN'
AssertionError: assert 'AT_RISK' == 'UNKNOWN'
```

Break B: restored the old caveat wording.

```
assert 'holds no holidays at all' in "2029-01-01 is beyond the calendar's verified
horizon (2028-12-31); holidays proclaimed later could move this deadline"
```

## 6. An unguarded Decimal in load_gic

`Decimal(e["annual_pct"])` raised `decimal.InvalidOperation` on a typo. That is an
`ArithmeticError`, not a `ValueError`, so it escaped the CLI's handler and printed
a traceback. A value Decimal does accept, `nan` or `Infinity`, passed silently and
poisoned every money figure.

Both are now `RatesError` naming the offending quarter and its date span. The
quarter dates and missing or non-dict entries get the same treatment; `load_rates`
returns raw JSON and does no numeric conversion.

File: `paydaysuper/rates.py`. New test file `tests/test_rates.py` (11 tests,
`DATA_DIR` monkeypatched) covering an unreadable rate, nan/NaN/Infinity/-Infinity/sNaN,
a missing key, a null rate, a bad quarter date, and the CLI printing
`error: ...` with no traceback.

Break: collapsed `_rate` to `return Decimal(str(raw))`.

```
decimal.InvalidOperation: [<class 'decimal.ConversionSyntax'>]
Failed: DID NOT RAISE RatesError        (x5, the non-finite cases)
8 failed, 3 passed
```

## 7. AT_RISK caveats never reached stdout

An AT_RISK line is excluded from the exposure listing and from the unflagged
bucket, so its caveats went nowhere but the CSV, including the one saying two rows
are identical and the payday is counted twice.

**Choice: print them in the at-risk block**, the way the exposed block does, rather
than folding them into the unflagged count. The count tells you a number; the
block tells you which rows and why. Capped at ten with a "and N more" line.

File: `paydaysuper/report.py`.
Test: `test_at_risk_caveats_reach_the_console`.

Break: `flagged = [r for r in at_risk if r.caveats]` -> `flagged = []`.

```
assert 'counted 2 times' in "payday-super-checker: 2 contribution lines, as at
2026-08-10\n\n  ON_TIME: 0  AT_RISK: 2 ..."
```

## 8. The on-time boundary was untested

Both `<=` comparisons in the verdict ladder could be tightened to `<` with the
whole suite green.

Test only, no production change.
Tests: `test_receipt_on_the_due_date_is_on_time` (receipt == due, ON_TIME, no
final shortfall), `test_remittance_on_the_due_date_with_no_receipt_is_at_risk`.

Break: flipped both `<=` to `<`.

```
AssertionError: assert 'LATE' == 'ON_TIME'
AssertionError: assert 'LATE' == 'AT_RISK'
```

## 9. report.csv was written without a BOM

Written as plain UTF-8 while the reader uses `utf-8-sig`, so Excel on a cp1252
Windows box mis-decoded a non-ASCII employee id and the report stopped joining
back to payroll.

File: `paydaysuper/report.py`, `encoding="utf-8-sig"`.
Test: `test_report_csv_carries_a_bom_and_round_trips_a_non_ascii_id`. Runs an id
carrying U+00D1 (built with `chr(0x00D1)`, so the test file stays ASCII) through
the CLI, asserts the file starts with `codecs.BOM_UTF8`, that `row` is still the
first heading and the id survives, then feeds a BOM-prefixed canonical file back
through `parse_rows` and checks the id and QE day round-trip.

Break: `encoding="utf-8-sig"` -> `"utf-8"`.

```
assert False
 +  where False = b'row,employee_id,qe_day,...'.startswith(b'\xef\xbb\xbf')
```

## 10. apply_item4's chronological sort was never exercised

The row-order regression test built every row on the same QE day, so the sort key
could be deleted with the suite green.

Test only.
Test: `tests/test_deadlines.py::test_item4_aligns_paydays_given_out_of_date_order`.
Feeds one employee's 23 Jul payday before their 9 Jul first-to-fund payday and
asserts the later line still comes out aligned, matching the same facts in date
order.

Break: `items.sort(key=lambda p: (p[0].qe_day, p[0].row))` -> sort by row only.

```
AssertionError: assert {...} == {...}
Differing items:
{datetime.date(2026, 7, 23): (datetime.date(2026, 8, 4), 'USUAL_7BD')} !=
{datetime.date(2026, 7, 23): (datetime.date(2026, 8, 7), 'ITEM4_ALIGNED')}
```

## 11. test_report_columns_add_up was a tautology

It compared a `_rounded_figures` entry against the expression that defines it, so
it held whatever `write_csv` did.

Test only. It now runs the CLI, reads `report.csv` back with `utf-8-sig` and sums
the written strings for every LATE and UNPAID row: `final_shortfall +
notional_earnings + uplift_best_case == sgc_estimate_low`, and the same for the
worst-case and high columns. Asserts at least three rows were checked, so the loop
cannot pass by matching nothing. The now-unused `_rounded_figures` import was
dropped.

Break: `write_csv` writes `money(r.sgc_high)`, the unrounded exposure total, instead
of `money(figures["high"])`. This is the discriminating break: the old test would
still have passed, since it never touched `write_csv`.

```
AssertionError: {'row': '5', 'employee_id': 'EMP004', ...}
assert ((Decimal('780.00') + Decimal('5.15')) + Decimal('471.09')) == Decimal('1256.23')
```

---

## Also changed

- `README.md` and `docs/design.md`: `UNKNOWN` was documented as "not due yet,
  nothing recorded". It now has three ways in, so both files say so. `design.md`
  also picked up the horizon behaviour change.
- `docs/design.md` converted to pure ASCII (17 em dashes, an en dash, three
  arrows, one `>=`). It was the only shipped source or doc file carrying non-ASCII
  bytes, and this round edited it.

## Untouched, as instructed

`csv_io.py`'s comma handling and `ci.yml`'s `--no-index`.

## Concerns

- **`docs/research-notes-2026-08-02.md` holds 539 non-ASCII bytes.** Not touched
  this round, so not converted, but it ships in the sdist via `MANIFEST.in` and
  breaks the pure-ASCII rule the moment anyone edits it.
- **UNPAID rows past the calendar horizon still carry `days_late` and notional
  earnings computed against a deadline that can only be too early.** Deliberate
  (see finding 5), and the horizon caveat is attached, but the figures are
  marginally overstated for those rows. Extending `business_days.json` past
  2028-12-31 removes the whole class of problem and is the real fix.
- **The horizon override is keyed on `dl.due > cal.verified_until` only.** A
  deadline window that starts inside the verified range and ends outside it is
  caught; one wholly inside is not, which is correct. Nothing checks the QE day
  against `verified_from`, since the regime start already floors it.
- **A nil row maps to `UNKNOWN` rather than a new verdict constant.** The finding
  asked for "its own outcome". `UNKNOWN` is the existing "nothing to assess"
  bucket and an existing test already pins a nil row to it; adding a seventh
  verdict would have changed `VERDICTS`, the console counts line and that test for
  no gain in what the user learns. The distinguishing signal is the caveat.
