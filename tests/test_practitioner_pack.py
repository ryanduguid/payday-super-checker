import csv
import hashlib
import subprocess
from pathlib import Path

import pytest

from paydaysuper import cli
from paydaysuper.practitioner_pack import (
    EXPECTED_REPORT_HEADER,
    PractitionerPackError,
    load_report_snapshot,
    render_practitioner_pack,
    write_practitioner_pack,
)
from paydaysuper.report import CSV_HEADER


NOTE_TEXT = (
    "payday-super-checker 0.1.1, source C:\\Private\\Client A\\pay.csv, "
    "as at 2026-09-10. Legal content current at 2026-08-15. "
    "EXPERIMENTAL ESTIMATES: the ATO assesses the charge."
)
ROOT = Path(__file__).resolve().parents[1]


def _row(**overrides):
    values = {
        "row": "2",
        "employee_id": "000123",
        "qe_day": "2026-08-06",
        "pathway": "usual period",
        "due_date": "2026-08-17",
        "verdict": "LATE",
        "days_late": "3",
        "lateness_measured_to": "fund receipt",
        "sg_amount": "100.00",
        "final_shortfall": "0.00",
        "notional_earnings": "1.00",
        "uplift_best_case": "0.20",
        "uplift_worst_case": "0.60",
        "sgc_estimate_low": "1.20",
        "sgc_estimate_high": "1.60",
        "caveats": "verify receipt evidence",
        "notes": "fabricated test row",
        "unassessable_between": "",
    }
    values.update(overrides)
    return [values[name] for name in EXPECTED_REPORT_HEADER]


def _note(**overrides):
    values = {name: "" for name in EXPECTED_REPORT_HEADER}
    values["employee_id"] = "NOTE"
    values["notes"] = NOTE_TEXT
    values.update(overrides)
    return [values[name] for name in EXPECTED_REPORT_HEADER]


def _write_report(path: Path, rows=None, header=None):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header or EXPECTED_REPORT_HEADER)
        writer.writerows(rows or [_row(), _note()])
    return path


def test_contract_is_deliberately_pinned_to_the_report_writer():
    assert list(EXPECTED_REPORT_HEADER) == CSV_HEADER
    assert len(EXPECTED_REPORT_HEADER) == 18


def test_pack_is_deterministic_private_by_default_and_source_bound(tmp_path):
    source = _write_report(
        tmp_path / "report.csv",
        [
            _row(employee_id="'=SUM(1,1)"),
            _row(
                row="3",
                employee_id="ava.lawson@example.test",
                verdict="AT_RISK",
                days_late="",
                final_shortfall="",
                notional_earnings="",
                uplift_best_case="",
                uplift_worst_case="",
                sgc_estimate_low="",
                sgc_estimate_high="",
                caveats="remittance is not fund receipt | needs follow-up",
            ),
            _note(),
        ],
    )
    snapshot = load_report_snapshot(source)

    first = render_practitioner_pack(snapshot)
    second = render_practitioner_pack(snapshot)

    assert first == second
    assert hashlib.sha256(source.read_bytes()).hexdigest() in first
    assert "ATTENTION REQUIRED" in first
    assert "LATE" in first and "AT_RISK" in first
    assert "source row 2" in first and "source row 3" in first
    assert "000123" not in first
    assert "SUM(1,1)" not in first
    assert "ava.lawson@example.test" not in first
    assert "Client A" in first  # the producer's exact provenance note is retained
    assert "does not lodge, pay, post or make a compliance determination" in first


def test_no_exception_pack_still_requires_human_signoff(tmp_path):
    source = _write_report(
        tmp_path / "report.csv",
        [
            _row(
                verdict="ON_TIME",
                days_late="",
                final_shortfall="",
                notional_earnings="",
                uplift_best_case="",
                uplift_worst_case="",
                sgc_estimate_low="",
                sgc_estimate_high="",
            ),
            _note(),
        ],
    )
    pack = load_report_snapshot(source)
    text = render_practitioner_pack(pack)

    assert pack.needs_attention is False
    assert "NO EXCEPTION INDICATORS" in text
    assert "Practitioner sign-off is still required" in text


@pytest.mark.parametrize(
    "rows, message",
    [
        ([_row()], "terminal NOTE"),
        ([_note(), _row()], "terminal NOTE"),
        ([_row(), _note(), _note()], "exactly one NOTE"),
        ([_row(verdict="PASS"), _note()], "unsupported verdict"),
        ([_row(row="two"), _note()], "positive integer"),
        ([_row(qe_day="06/08/2026"), _note()], "ISO date"),
        ([_row(sg_amount="NaN"), _note()], "finite amount"),
        ([_row(sgc_estimate_low="1.21"), _note()], "does not add up"),
    ],
)
def test_malformed_or_internally_inconsistent_reports_fail_closed(tmp_path, rows, message):
    source = _write_report(tmp_path / "report.csv", rows)
    with pytest.raises(PractitionerPackError, match=message):
        load_report_snapshot(source)


def test_employee_identifier_note_is_not_a_terminal_note(tmp_path):
    source = _write_report(tmp_path / "report.csv", [_row(employee_id="NOTE"), _note()])

    snapshot = load_report_snapshot(source)

    assert [row.source_row for row in snapshot.rows] == [2]


def test_note_only_report_is_rejected_instead_of_rendering_no_exceptions(tmp_path):
    source = _write_report(tmp_path / "report.csv", [_note()])

    with pytest.raises(PractitionerPackError, match="at least one contribution row"):
        load_report_snapshot(source)


def test_terminal_note_requires_non_whitespace_provenance(tmp_path):
    source = _write_report(tmp_path / "report.csv", [_row(), _note(notes=" \t ")])

    with pytest.raises(PractitionerPackError, match="malformed terminal NOTE"):
        load_report_snapshot(source)


def test_malformed_terminal_note_with_data_fields_fails_closed(tmp_path):
    source = _write_report(tmp_path / "report.csv", [_row(), _note(row="3")])

    with pytest.raises(PractitionerPackError, match="terminal NOTE"):
        load_report_snapshot(source)


def test_duplicate_or_changed_headers_fail_closed(tmp_path):
    duplicate = list(EXPECTED_REPORT_HEADER)
    duplicate[-1] = "notes"
    source = _write_report(tmp_path / "duplicate.csv", header=duplicate)
    with pytest.raises(PractitionerPackError, match="exact 18-column"):
        load_report_snapshot(source)

    changed = list(EXPECTED_REPORT_HEADER)
    changed[0] = "source_row"
    source = _write_report(tmp_path / "changed.csv", header=changed)
    with pytest.raises(PractitionerPackError, match="exact 18-column"):
        load_report_snapshot(source)


def test_default_practitioner_workpaper_is_ignored():
    rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()

    assert "/practitioner-review.md" in rules
    assert "include .gitignore" in manifest

    if (ROOT / ".git").exists():
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", "--", "practitioner-review.md"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


def test_output_is_atomic_and_replaces_the_link_not_its_target(tmp_path):
    source = _write_report(tmp_path / "report.csv")
    target = tmp_path / "elsewhere.md"
    target.write_text("leave me", encoding="utf-8")
    output = tmp_path / "practitioner-review.md"
    try:
        output.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    write_practitioner_pack(load_report_snapshot(source), output)

    assert output.is_file() and not output.is_symlink()
    assert "# Payday Super Practitioner Review Pack" in output.read_text(encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "leave me"


def test_cli_writes_pack_and_uses_attention_exit_code(tmp_path, capsys):
    source = _write_report(tmp_path / "report.csv")
    output = tmp_path / "review.md"

    result = cli.main(["review-pack", str(source), "-o", str(output)])

    assert result == cli.EXIT_LATE_FOUND
    assert output.exists()
    assert f"wrote {output}" in capsys.readouterr().out


def test_cli_refuses_input_output_collision_and_wrong_suffix(tmp_path, capsys):
    source = _write_report(tmp_path / "report.csv")

    assert cli.main(["review-pack", str(source), "-o", str(source)]) == cli.EXIT_ERROR
    assert "overwrite the input report" in capsys.readouterr().err

    assert cli.main(["review-pack", str(source), "-o", str(tmp_path / "review.txt")]) == 1
    assert ".md filename" in capsys.readouterr().err


def test_cli_refuses_input_output_collision_through_a_symlink(tmp_path, capsys):
    source = _write_report(tmp_path / "report.csv")
    output = tmp_path / "review.md"
    try:
        output.symlink_to(source)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    assert cli.main(["review-pack", str(source), "-o", str(output)]) == cli.EXIT_ERROR
    assert "overwrite the input report" in capsys.readouterr().err

def test_relative_report_path_cannot_leave_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / "escaped-report.csv"
    _write_report(outside)
    try:
        with pytest.raises(PractitionerPackError, match="allowed directory"):
            load_report_snapshot(Path("..") / outside.name)
    finally:
        outside.unlink(missing_ok=True)


def test_report_path_must_be_csv(tmp_path):
    source = tmp_path / "report.txt"
    source.write_text("not csv", encoding="utf-8")
    with pytest.raises(PractitionerPackError, match=".csv"):
        load_report_snapshot(source)

