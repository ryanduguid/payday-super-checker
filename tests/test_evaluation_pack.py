from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

import pytest

from paydaysuper.cli import main

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "evaluation" / "payday_super_evidence"
EXPECTED = PACK / "expected_results.json"


@pytest.mark.parametrize(
    ("fixture", "expected_verdict", "expected_exit"),
    [
        ("timely_remittance_no_receipt.csv", "AT_RISK", 2),
        ("late_remittance_no_receipt.csv", "LATE", 2),
        ("receipt_on_due_date.csv", "ON_TIME", 0),
        ("receipt_after_due_date.csv", "LATE", 2),
    ],
)
def test_evidence_boundary_scenarios(
    tmp_path: Path,
    fixture: str,
    expected_verdict: str,
    expected_exit: int,
) -> None:
    output = tmp_path / f"{Path(fixture).stem}-report.csv"
    code = main(
        [
            str(PACK / "fixtures" / fixture),
            "--as-at",
            "2026-08-20",
            "-o",
            str(output),
        ]
    )
    assert code == expected_exit
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["due_date"] == "2026-08-17"
    assert rows[0]["verdict"] == expected_verdict


def test_machine_readable_contract_matches_the_parametrised_cases() -> None:
    contract = json.loads(EXPECTED.read_text(encoding="utf-8"))
    observed = {
        (item["fixture"], item["expected_verdict"], item["expected_exit"])
        for item in contract["scenarios"]
    }
    assert observed == {
        ("timely_remittance_no_receipt.csv", "AT_RISK", 2),
        ("late_remittance_no_receipt.csv", "LATE", 2),
        ("receipt_on_due_date.csv", "ON_TIME", 0),
        ("receipt_after_due_date.csv", "LATE", 2),
    }


def test_evaluation_guide_keeps_the_evidence_and_human_boundaries_visible() -> None:
    contract = json.loads(EXPECTED.read_text(encoding="utf-8"))
    readme = (PACK / "README.md").read_text(encoding="utf-8")
    assert contract["product_release"] == "v0.1.2"
    assert contract["fixture_version"] == "1"
    assert contract["source_reviewed"] == "2026-08-15"
    assert contract["human_decision"] in readme
    for phrase in (
        "fabricated",
        "remittance",
        "fund receipt",
        "cannot prove on-time",
        "experimental",
    ):
        assert phrase in readme.casefold()
    assert "case study" not in readme.casefold()


def test_only_declared_evaluation_csvs_are_allowlisted() -> None:
    allowed = {
        "evaluation/payday_super_evidence/fixtures/timely_remittance_no_receipt.csv",
        "evaluation/payday_super_evidence/fixtures/late_remittance_no_receipt.csv",
        "evaluation/payday_super_evidence/fixtures/receipt_on_due_date.csv",
        "evaluation/payday_super_evidence/fixtures/receipt_after_due_date.csv",
    }
    rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for relative in sorted(allowed):
        assert f"!{relative}" in rules
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", "--", relative],
            cwd=ROOT,
            check=False,
        )
        assert result.returncode == 1, relative
    refused = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            "--quiet",
            "--",
            "evaluation/payday_super_evidence/fixtures/client.csv",
        ],
        cwd=ROOT,
        check=False,
    )
    assert refused.returncode == 0
