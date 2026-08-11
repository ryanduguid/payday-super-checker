# Contributing

This tool checks contributions against the payday-super deadline and estimates SG-charge exposure. It reports; it does not lodge, pay, or advise. Keep that boundary: no contribution should give it authority to submit an SGC statement, move money, or present an estimate as an assessment.

## Data boundary

- Use fabricated data only. The `.gitignore` blocks `.csv`, `.xls`, `.xlsx`, `.pdf`, `.ofx`, `.qif` and `.aba` files, with exceptions only for `examples/*.csv` and `tests/fixtures/importers/*.csv`. Put new fixtures in one of those two directories.
- `.aba` files are the most sensitive artifact a payroll run produces. Never commit one, even redacted.
- Do not commit employee names, membership numbers, TFNs, ABNs tied to a real employer, or screenshots of a live payroll system.

## Legislation and calendar changes

- Every rate, threshold and deadline traces to a primary source. Cite the provision or instrument in the pull request. `docs/research-notes-2026-08-02.md` shows the expected level of detail.
- Business days follow one national calendar: a day is not a business day if it is a Saturday, a Sunday, or a public holiday for the whole of any State, the ACT or the NT. Regional holidays do not stop the clock.
- Vendor column profiles ship `"verified": false` because no Australian payroll vendor publishes its export header list. Flipping a profile to `"verified": true` requires a real header row from that vendor's export, quoted in the pull request. Headers only, no data.

## Local verification

Python 3.10 or newer. Runtime code is standard library only; `uv` manages the development environment and the lock file is committed.

```bash
uv sync --locked --extra dev --python 3.12
uv run --locked --extra dev --python 3.12 pytest
uv run --locked --extra dev --python 3.12 python -m build
uv run --locked --extra dev --with "pip-audit==2.10.1" pip-audit --local --strict
```

CI repeats this on Ubuntu with Python 3.10 and 3.13, and on Windows with 3.12. Runtime strings stay ASCII: non-console stdout on Windows uses the machine's ANSI codepage, not UTF-8.

## Pull requests

Name the rule you changed and the test that pins it. A behaviour change needs a focused test under `tests/`; a green suite that passes both before and after tells a reviewer nothing.

If you change a rule, search for everything that documents or enforces it. An enumeration in the report, a README table and a docstring can all keep asserting the old rule after the code stops.

For a potential security vulnerability, follow [SECURITY.md](SECURITY.md) rather than opening an issue.
