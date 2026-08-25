# Contributing

This tool checks contributions against the payday-super deadline and estimates SG-charge exposure. A human reads the output and decides what to do with it. Keep that boundary: no contribution should give the tool authority to submit an SGC statement, move money, or present an estimate as an assessment.

## Data boundary

- Use fabricated data. The `.gitignore` blocks `.csv`, `.xls`, `.xlsx`, `.pdf`, `.ofx`, `.qif` and `.aba` files, with exceptions for `examples/*.csv` and `tests/fixtures/importers/*.csv`. Put new fixtures in one of those two directories.
- Never commit an `.aba` file, redacted or not. It carries the account numbers a payroll run pays into.
- Keep employee names, membership numbers, TFNs, ABNs tied to a real employer, and screenshots of a live payroll system out of the repository.

## Legislation and calendar changes

- Trace every rate, threshold and deadline to a primary source, and cite the provision or instrument in your pull request.
- Business days follow one national calendar. A day is not a business day if it falls on a Saturday, a Sunday, or a public holiday declared for the whole of any State, the ACT or the NT. Regional holidays do not stop the clock.
- Vendor column profiles ship `"verified": false` because no Australian payroll vendor publishes its export header list. To flip a profile to `"verified": true`, quote a real header row from that vendor's export in the pull request. Headers only, no data.

## Local verification

Python 3.10 or newer. The runtime imports nothing outside the standard library. `uv` manages the development environment, and we commit the lock file.

```bash
uv sync --locked --extra dev --python 3.12
uv run --locked --extra dev --python 3.12 pytest
uv run --locked --extra dev --python 3.12 python -m build
uv run --locked --extra dev --with "pip-audit==2.10.1" pip-audit --local --strict
```

CI repeats this on Ubuntu with Python 3.10 and 3.13, and on Windows with 3.12. Keep runtime strings ASCII: on Windows, redirected stdout uses the machine's ANSI codepage rather than UTF-8.

## Pull requests

Name the rule you changed and the test that pins it. A behaviour change needs a focused test under `tests/`. Run that test against the old code first. If it passes there too, it is not testing your change.

When you change a rule, search for everything else that states or enforces it. An enumeration in the report, a README table and a docstring can all keep asserting the old rule long after you have changed the code.

For a potential security vulnerability, follow [SECURITY.md](SECURITY.md) rather than opening an issue.

## Experimental prereleases

Do not create or move a release tag from a pull-request branch. The owned-repo
procedure in [docs/releases/PROCESS.md](docs/releases/PROCESS.md) requires the
exact tag, current `main` commit, package versions and reviewed release notes to
agree. It also requires an administrator to enable and re-check GitHub release
immutability before tagging. The manual workflow publishes a non-latest GitHub
prerelease with reproducible artefacts, checksums, an SPDX runtime SBOM and
GitHub attestations; it does not publish to PyPI. A release remains an
experimental review aid, not a compliance determination.
