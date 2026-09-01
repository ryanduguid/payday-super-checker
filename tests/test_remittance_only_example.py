"""Guards on the fabricated example that isolates the remittance boundary.

`examples/sample_remittance_only.csv` exists to show one thing: a contribution
sent by its own deadline is still only `AT_RISK` until a fund receipt date is
known. The example is worth nothing if it drifts into carrying exposure, a
receipt date or a transition-period payday, because any of those would give
the run a second reason to refuse and the boundary would stop being isolated.
"""

import csv
from datetime import date
from pathlib import Path

from paydaysuper.cli import EXIT_LATE_FOUND, EXIT_OK, main as cli_main

from conftest import REMITTANCE_ONLY

README = Path(__file__).resolve().parents[1] / "README.md"
AS_AT = "2026-09-10"

# LCR 2026/1 applies 1-28 July 2026 contributions to the June quarter first.
# A payday inside that window would make the run ask for a second, unrelated
# confirmation and stop before a verdict.
TRANSITION_ENDS = date(2026, 7, 28)

REMITTED_BY_DEADLINE = (
    "4 line(s) remitted by the deadline but with no fund-receipt date. The "
    "statutory timing test turns on receipt by the fund, not the day you "
    "paid, and clearing-house transit time is the employer's risk."
)
ASKS_FOR_CONFIRMATION = (
    "This file cannot produce ON_TIME: no in-scope positive row has a "
    "fund-receipt date on or before the as-at date."
)
RECORDS_CONFIRMATION = (
    "Operator confirmed remittance-only review: no in-scope positive row has "
    "a fund-receipt date on or before the as-at date, so this file cannot "
    "produce ON_TIME."
)


def rows():
    with REMITTANCE_ONLY.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def run(tmp_path, capsys, *flags):
    code = cli_main(
        [
            str(REMITTANCE_ONLY),
            "-o",
            str(tmp_path / "report.csv"),
            "--as-at",
            AS_AT,
            *flags,
        ]
    )
    return code, capsys.readouterr().out


def test_every_line_is_remitted_with_no_fund_receipt():
    """The whole point of the file: vendor dates present, receipts absent."""
    lines = rows()
    assert lines, "the example must carry contribution lines"
    for line in lines:
        assert line["fund_received_date"] == ""
        assert line["remitted_date"] != ""


def test_paydays_sit_after_the_transition_period():
    for line in rows():
        assert date.fromisoformat(line["payment_date"]) > TRANSITION_ENDS


def test_unconfirmed_run_exits_two_and_asks_for_confirmation(tmp_path, capsys):
    code, printed = run(tmp_path, capsys)

    assert code == EXIT_LATE_FOUND
    assert ASKS_FOR_CONFIRMATION in printed
    assert "pass --confirm-remittance-only" in printed


def test_confirmed_run_exits_zero_and_records_the_confirmation(tmp_path, capsys):
    """Nothing in the file is exposed or undecided, so the missing receipt is
    the only thing holding the unconfirmed run above zero. Confirming it must
    reach zero, or the example is not isolating the boundary it claims to."""
    code, printed = run(tmp_path, capsys, "--confirm-remittance-only")

    assert code == EXIT_OK
    assert RECORDS_CONFIRMATION in printed


def test_confirming_does_not_promote_any_line_to_on_time(tmp_path, capsys):
    counts = "ON_TIME: 0  AT_RISK: 4  LATE: 0  UNPAID: 0  UNKNOWN: 0  SKIPPED: 0"

    _, unconfirmed = run(tmp_path, capsys)
    _, confirmed = run(tmp_path, capsys, "--confirm-remittance-only")

    assert counts in unconfirmed
    assert counts in confirmed


def test_both_runs_say_remittance_does_not_prove_receipt(tmp_path, capsys):
    """At least one line is remitted by its supported due date, and the run
    says so while still refusing to call it on time."""
    _, unconfirmed = run(tmp_path, capsys)
    _, confirmed = run(tmp_path, capsys, "--confirm-remittance-only")

    assert REMITTED_BY_DEADLINE in unconfirmed
    assert REMITTED_BY_DEADLINE in confirmed


def test_readme_documents_both_commands_and_their_boundary_text():
    readme = README.read_text(encoding="utf-8")
    both = "payday-super-check examples/sample_remittance_only.csv --as-at 2026-09-10"

    assert both in readme
    assert f"{both} --confirm-remittance-only" in readme
    assert ASKS_FOR_CONFIRMATION in readme
    assert RECORDS_CONFIRMATION in readme
    assert REMITTED_BY_DEADLINE in readme
