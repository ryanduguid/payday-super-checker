# Audit fix round 2

Branch `fix/audit-findings`. Nine findings from the adversarial verify pass on
round 1. Suite went 329 to 366, green at every commit. Nothing pushed.

## Commits

| SHA | Subject | Suite after |
| --- | --- | --- |
| c544b53 | fix: keep the universal caveat out of the at-risk listing | 332 |
| 412ca16 | fix: refuse a GIC rate that is negative or absurd | 340 |
| 37c8f82 | fix: read the calendar's horizon off the holidays the table holds | 352 |
| 4f73e9d | fix: assess the side of a short calendar's horizon that can be proved | 360 |
| 789e80d | fix: a nil payday is not the earlier contribution item 4 needs | 364 |
| 9dfaea2 | fix: report the deadline a missing out-of-cycle flag actually produced | 366 |

## Teeth-proofs

Twenty-two mutations, each breaking a guard the exact way its finding
describes. Every one fails a covering test; every one passes again on revert.
Run against the committed tree, not a scratch copy.

A note on method. The first proof run reported a false pass on 7c. The
mutation swapped `coverage_until` for `verified_until`, the same byte length,
and the restore landed inside one filesystem mtime tick, so CPython reused the
mutated `.pyc`. The harness now clears `__pycache__` and runs with
`PYTHONDONTWRITEBYTECODE=1`. Rerun under those conditions, 7c was a real
toothless test, and the covering test was rewritten to catch it.

### 1. Force-UNKNOWN past the calendar's horizon (CRITICAL)

Gated on the indeterminable side only: `past_horizon and settled > dl.due`,
`past_horizon and line.remitted > dl.due`. A missing holiday can only push the
real deadline later, so a date on or before the computed deadline is provably
on time under every future holiday set.

| Mutation | Test | Assertion |
| --- | --- | --- |
| `elif past_horizon and settled > dl.due` back to `elif past_horizon` | `test_receipt_before_a_past_horizon_deadline_is_on_time` | `assert 'UNKNOWN' == 'ON_TIME'` |
| `if past_horizon and line.remitted > dl.due` back to `if past_horizon` | `test_remittance_before_a_past_horizon_deadline_is_at_risk` | `assert 'UNKNOWN' == 'AT_RISK'` |
| exit code back to `any(r.verdict in EXPOSED ...)` | `test_an_unassessable_line_gets_its_own_block_and_a_non_zero_exit` | `assert 0 == 2` |
| `indeterminate = []`, so the block never prints | `test_an_unassessable_line_is_not_counted_as_a_plain_data_quality_note` | `assert 'cannot be assessed' in "payday-super-checker: 1 contribution lines..."` |

The two tests that asserted UNKNOWN for an early date now assert ON_TIME and
AT_RISK. `test_receipt_past_the_calendar_horizon_is_not_called_late` keeps the
genuinely unknowable case, and `test_receipt_on_a_past_horizon_deadline_is_on_time`
pins the boundary at the due date itself.

The row from the finding now reads:

```
1 line(s) cannot be assessed: the date recorded is after the deadline shown, and that
deadline runs past the calendar's coverage, so a holiday the calendar does not hold
could still make the line on time. Each one is either verdict below and needs a decision.
  row 2  VERYLATE29  QE day 2029-03-01  due 2029-03-12  super $9000.00  LATE or ON_TIME
```

Exit 2, not 0.

### 2. Boilerplate caveat filling the at-risk listing

`NO_RECEIPT_CAVEAT` is now a module constant. The listing splits each row's
caveats into that one and the rest, keeps only rows with at least one other,
and prints only the others.

| Mutation | Test | Assertion |
| --- | --- | --- |
| `flagged = [(r, list(r.caveats)) for r in at_risk]` | `test_the_universal_at_risk_caveat_does_not_fill_the_listing` | `assert 'counted 2 times' in "payday-super-checker: 12 contribution lines..."` |

Twelve at-risk rows, ten with nothing of their own to say and the last two an
identical pair. The duplicate-payday warning now reaches the console.

### 3. Nil payday seeding an item 4 alignment

`apply_item4` skips `sg_amount <= 0` when accumulating `group_latest`. The
donor test in `_item4_seeded_by_unrecorded` treats a nil donor as unrecorded
whatever dates it carries.

| Mutation | Test | Assertion |
| --- | --- | --- |
| drop `and line.sg_amount > 0` | `test_a_nil_payday_does_not_seed_an_item_4_alignment` | `assert datetime.date(2026, 8, 7) == datetime.date(2026, 8, 4)` |
| donor test back to dates only | `test_a_nil_donor_does_not_suppress_the_unrecorded_item_4_caveat` | `assert False = any(...)` on `"no payment is recorded"` |

The EMP200 repro is covered end to end: the 1000.00 payday keeps its own
2026-08-04 deadline and comes out LATE, two days late, instead of ON_TIME.

### 4. Next-standard-payday caveat naming the wrong pathway

The caveat is built after the winning candidate is known. Item 2 is computed
and held; the caveat fires with `max(item2, due)` where item 2 is later, and
says the flag would change nothing where item 1 already won.

| Mutation | Test | Assertion |
| --- | --- | --- |
| restore the unconditional 7-business-day wording | `test_next_payday_caveat_names_the_deadline_the_row_actually_got` | `assert '20-business-day deadline 2026-08-10 was used' in 'a next standard QE day 2026-07-23 is supplied but the out-of-cycle flag is not set, so the strict 7-business-day dead...'` |

`test_next_payday_caveat_still_fires_where_item_2_would_win` holds the other
branch, where setting the flag really would move the deadline.

### 5. Unguarded top level in the data files

`rates.py` and `calendar.py` both check `isinstance(doc, dict)`, then each
expected key's presence and type, raising `RatesError` or `CalendarError`
naming the file and the key. `verified_from` and `verified_until` are parsed
through a guard. `load_rates` gets the same check, since `console_summary`
calls `.get()` on it.

| Mutation | Test | Assertion |
| --- | --- | --- |
| `doc = json.load(f)` in `load_gic` | `test_a_missing_quarters_key_is_named` | `KeyError: 'quarters'` |
| `doc = json.load(f)` in `load_calendar` | `test_a_missing_top_level_key_is_named[non_business_days]` | `KeyError: 'non_business_days'` |
| raw `date.fromisoformat` on the verified dates | `test_an_unreadable_verified_date_is_named[verified_from]` | `ValueError: Invalid isoformat string: '31/12/2028'` |

Both CLI tests assert stderr starts with `error: ` and holds no `Traceback`.

### 6. GIC rate sign and magnitude

Below zero or above `RATE_CEILING = Decimal("100")` is refused, naming the
quarter and the value.

| Mutation | Test | Assertion |
| --- | --- | --- |
| drop the `value < 0` check | `test_a_negative_rate_is_refused` | `Failed: DID NOT RAISE RatesError` |
| drop the ceiling check | `test_a_rate_above_the_ceiling_is_refused` | `Failed: DID NOT RAISE RatesError` |
| widen to `value <= 0` | `test_a_zero_rate_is_accepted` | `RatesError: ... has annual_pct '0'; a GIC rate cannot be negative` |

`test_the_ceiling_itself_is_accepted` pins 100 as the last accepted value.

### 7. check_horizon ignoring --holidays-override

`BusinessCalendar` carries `coverage_until`: `verified_until` raised to the
latest holiday any override added. `check_horizon` reads it, and `report.py`
drives `past_horizon` from it.

| Mutation | Test | Assertion |
| --- | --- | --- |
| `coverage_until = verified_until` | `test_an_override_raises_the_coverage_end_past_verified_until` | `assert datetime.date(2028, 12, 31) == datetime.date(2029, 4, 25)` |
| `check_horizon` back to `verified_until` | `test_check_horizon_reads_the_table_not_the_verified_date` | `assert "2029-04-09 is beyond the calendar's verified horizon..." is None` |
| `past_horizon = dl.due > cal.verified_until` | `test_a_supplied_2029_calendar_produces_a_real_verdict` | `assert 'UNKNOWN' == 'LATE'` |

The third mutation is the one the first proof run missed. The test originally
checked only the on-time side, which the mutation does not change; it now
checks a receipt three days past the moved deadline, which needs `report.py`
to read the coverage end before it can be called LATE.

An override supplying Good Friday, Easter Monday and Anzac Day 2029 moves a
2029-03-27 payday's deadline from 2029-04-05 to 2029-04-09, and the caveat
stops firing for dates the user covered.

### 8. Definite figures off an indeterminate deadline

A row still exposed past the coverage end (an unpaid payday, a stale
pre-payment) leaves `days_late` blank and labels the money a maximum.

| Mutation | Test | Assertion |
| --- | --- | --- |
| `result.days_late = max((outstanding_to - dl.due).days, 0)` unconditionally | `test_exposure_past_the_horizon_leaves_days_late_blank_and_labels_a_maximum` | `assert 81 is None` |

Console reads `days late not pinned down, measured to as-at date` and
`notional earnings at most $12.84  SG charge estimate at most $512.84 -
$820.55`. `test_days_late_inside_the_horizon_is_still_a_definite_number` holds
the other side at 21 days with no `at most`, and
`test_days_late_blank_reaches_the_report_csv` pins the empty CSV cell.

### 9. Toothless at-risk console test

Twelve rows, distinct ids, two distinct markers each, none of which appears
anywhere else in the output.

| Mutation | Test | Assertion |
| --- | --- | --- |
| drop the row-identifying line | `test_the_at_risk_block_names_every_row_and_every_caveat_it_prints` | `assert '  row 2  ARK01  QE day 2026-07-09  due 2026-07-20' in "..."` |
| print one caveat per row | same | `assert '      note: beta marker 1' in "..."` |
| print one flagged row | same | `assert '  row 3  ARK02  QE day 2026-07-09  due 2026-07-20' in "..."` |
| never emit the truncation notice | same | `assert '... and 2 more at-risk line(s) with notes' in "..."` |

The test also counts notes and row lines exactly (`text.count("      note: ")
== 20`, ten row lines), and
`test_the_at_risk_truncation_notice_counts_only_flagged_rows` proves the
overflow counts flagged rows rather than at-risk rows.

## Beyond the nine

`load_rates` got the same top-level guard as `load_gic`. It is one line away
from finding 5 and the identical failure mode: `console_summary` calls `.get()`
on the result, so a JSON list there reaches the user as an AttributeError
traceback, which the CLI does not catch either.

## Docs

README's verdict paragraph and exit-code contract now describe the three ways
into UNKNOWN and say plainly that exit 0 means nothing exposed AND nothing left
undecided. `docs/design.md` records the asymmetry that decides one side of the
horizon and not the other.

## Not done

Nothing from the nine was left out. Two things a later round should look at:

- The report CSV marks an unassessable row `UNKNOWN` like any other. A parser
  reading the CSV rather than the console or the exit code cannot tell it from
  a nil row. A dedicated verdict or column would fix it; the console block and
  exit code cover the stated requirement.
- `PATHWAY_WORDS.get(pathway, pathway)` falls back to the raw constant name.
  Unreachable today, because the branch that writes the caveat can only produce
  `USUAL_7BD` or `EXTENDED_20BD`, but the fallback would read badly if a new
  pathway ever reached it.
