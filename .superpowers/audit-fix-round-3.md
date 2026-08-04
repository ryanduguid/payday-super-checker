# Audit fix round 3

Round 2's verify pass returned 17 defects across three repos, two of them
Critical and both caused by a fix round 2 itself specified. This round closed
all 17 plus two items round 2 carried forward. Fixed by hand rather than by
another agent fleet: the repro commands were already written down, and five
consecutive rounds had each ended with a green suite hiding new defects.

Suites: payday-super-checker 379 (was 366), xero-trial-balance-export 54 (was
34), accounting-excel-toolkit 18 (was 17). Nothing pushed.

## The Critical, and why it was mine

`coverage_until = max(verified_until, *holidays)` read the presence of one
holiday as proof the table was complete up to it. I specified that in round 2
to fix the opposite problem: a user who entered the missing years was being
told the calendar could not see holidays it was using.

An override adding only Christmas 2029 jumped coverage nine months forward.
A March 2029 payday then lost its horizon caveat entirely and came out LATE
with an SG charge attached, while the holidays actually missing from that
window (Good Friday 30 Mar, Easter Monday 2 Apr) would have moved the
deadline and made it on time. Strictly worse than the false UNKNOWN the fix
was meant to remove.

Reproduced on the CLI, before:

    ON_TIME: 0  AT_RISK: 0  LATE: 1
    row 2  EAST29  QE day 2029-03-27  due 2029-04-05  LATE, 1 days late

after:

    ON_TIME: 0  AT_RISK: 0  LATE: 0  UNPAID: 0  UNKNOWN: 1
    note: 2029-04-05 is beyond the calendar's coverage (2028-12-31, the last
    day the holiday table is complete to)

and with the year declared, `{"verified_until": "2029-12-31", "add": [...]}`:

    ON_TIME: 1  AT_RISK: 0  LATE: 0

Completeness is a claim and only the user can make it. An override raises the
horizon by setting its own `verified_until`; adding holidays does not, though
the holidays are still used. A declaration below the bundled span is ignored,
since adding a holiday never invalidates what was already verified.

`check_horizon` also stopped claiming the table "holds no holidays at all"
past the horizon, which this change made false: a partial override can hold a
2029 holiday while 2029 stays uncovered. It now claims only what holds either
way, that a missing holiday pushes the deadline later and never earlier.

## The pattern worth carrying forward

Both Criticals, and four of the Importants, were fixes that stopped one step
short of the thing they were fixing.

- Coverage inferred completeness from the presence of a holiday.
- `load_rates` guarded the document but not `financial_years`, which is the
  field `console_summary` actually dereferences, and not the entries under it.
- `_parse_entry` called `tuple()` on a `jurisdictions` value it never
  type-checked, in a file the tool invites users to write.
- The missing-flag caveat was deferred past the winning candidate but not
  past `apply_item4`, which runs later and moves the same deadline.
- `CALLBACK_READ_TIMEOUT` bounded one recv, not the connection, so a peer
  dribbling one byte per second reset it forever.
- `collect_targets` widened from `.bas` to three suffixes but still used
  `iterdir`, so a subdirectory export passed with exit 0 unopened.

The question that catches this class: after the guard, what is the next line
that touches untrusted input, and is it covered?

## Two tests that passed under the defect they named

`test_non_ascii_frm_fails` asserted only that some `EncodingCheckError` was
raised. Drop `.frm` from `VBE_TEXT_SUFFIXES` and `collect_targets` raises
"no .bas, .cls or .frm files found" instead, same exception type, test green.

`test_a_forged_state_beats_the_error_branch` was written this round and was
toothless when written. `main()` assigns `auth_code`, `auth_error` and
`returned_state` to None right after constructing the server, so a fake
carrying them as class attributes had them wiped before the branch under test
ran. It passed under the exact reorder it exists to catch. The values are now
set from inside the `wait_for_callback` stand-in, where a real callback sets
them.

Both were caught by mutation, not by reading.

## Teeth-proofs

Every fix was mutated back and the suite re-run with `__pycache__` cleared and
`PYTHONDONTWRITEBYTECODE=1`, per round 2's stale-bytecode lesson.

| Mutation | Caught by |
|---|---|
| coverage back to `max(*holidays)` | 3 tests, incl. the end-to-end CLI repro |
| missing-flag caveat against the pre-item4 deadline | 2 tests |
| UNPAID past-horizon branch removed | 1 test |
| `financial_years` guard removed | 1 test |
| `jurisdictions` guard removed | 4 parametrised cases |
| `rglob` back to `iterdir` | 1 test |
| magnitude guard removed | 3 tests |
| connection deadline set to 9999s | 1 test |
| `ERROR_CODE.fullmatch` to `.match` | 1 test |
| state check moved below the error branch | 2 tests |
| port 0 accepted | 1 test |
| clamped wait reported as the server's figure | 1 test |
| `unassessable_between` blanked | 1 test |
| note row back to `note[-1]` | 2 tests |

## Carried forward

Nothing from the 17 was left out. Two things a reader should know:

The sdist build was not re-run this round; `build` is not installed in this
environment. The `MANIFEST.in` fix it verifies was checked when made.

`.superpowers/` holds these reports. They are tracked in this repo and
gitignored in the other two, which is inconsistent. Worth one decision before
pushing: either track the reports everywhere or nowhere. The substance is in
the commit messages either way.
