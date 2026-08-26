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
PACK_LINK = "evaluation/payday_super_evidence/README.md"

EXPECTED_CONTRACT = {
    "schema_version": 1,
    "product_release": "v0.1.2",
    "fixture_version": "1",
    "as_at": "2026-08-20",
    "source_reviewed": "2026-08-15",
    "sources": [
        {
            "publisher": "Federal Register of Legislation",
            "title": "Superannuation Guarantee (Administration) Act 1992",
            "url": "https://www.legislation.gov.au/C2004A04402/latest/text",
        },
        {
            "publisher": "Australian Taxation Office",
            "title": "LCR 2026/2 eligible contributions",
            "url": (
                "https://www.ato.gov.au/law/view/document?DocID=COG%2FLCR20262%2FNAT%2FATO%2F00001"
            ),
        },
    ],
    "scenarios": [
        {
            "id": "timely_remittance_without_receipt",
            "fixture": "timely_remittance_no_receipt.csv",
            "expected_due_date": "2026-08-17",
            "expected_verdict": "AT_RISK",
            "expected_exit": 2,
        },
        {
            "id": "late_remittance_without_receipt",
            "fixture": "late_remittance_no_receipt.csv",
            "expected_due_date": "2026-08-17",
            "expected_verdict": "LATE",
            "expected_exit": 2,
        },
        {
            "id": "receipt_on_due_date",
            "fixture": "receipt_on_due_date.csv",
            "expected_due_date": "2026-08-17",
            "expected_verdict": "ON_TIME",
            "expected_exit": 0,
        },
        {
            "id": "receipt_after_due_date",
            "fixture": "receipt_after_due_date.csv",
            "expected_due_date": "2026-08-17",
            "expected_verdict": "LATE",
            "expected_exit": 2,
        },
    ],
    "human_decision": (
        "Remittance evidence can show operational timing but cannot prove on-time; "
        "a human must establish eligible fund receipt, allocation and the other "
        "assessment facts before relying on a statutory conclusion."
    ),
}

GUIDE_HEADINGS = [
    "## Accounting problem",
    "## Intended reviewer",
    "## Fabricated inputs",
    "## Reproduce the result",
    "## Expected result",
    "## Controls and refusal boundary",
    "## Primary sources and review date",
    "## Product and fixture version",
    "## Human decision",
    "## Limitations and non-claims",
]

REPRODUCTION_COMMANDS = [
    "uv run --locked --extra dev --python 3.12 payday-super-check "
    "evaluation/payday_super_evidence/fixtures/timely_remittance_no_receipt.csv "
    "--as-at 2026-08-20 -o timely-report.csv",
    "uv run --locked --extra dev --python 3.12 payday-super-check "
    "evaluation/payday_super_evidence/fixtures/late_remittance_no_receipt.csv "
    "--as-at 2026-08-20 -o late-remittance-report.csv",
    "uv run --locked --extra dev --python 3.12 payday-super-check "
    "evaluation/payday_super_evidence/fixtures/receipt_on_due_date.csv "
    "--as-at 2026-08-20 -o on-time-report.csv",
    "uv run --locked --extra dev --python 3.12 payday-super-check "
    "evaluation/payday_super_evidence/fixtures/receipt_after_due_date.csv "
    "--as-at 2026-08-20 -o late-receipt-report.csv",
    "uv run --locked --extra dev --python 3.12 pytest tests/test_evaluation_pack.py -q",
]

FIXTURE_HEADER = [
    "employee_id",
    "payment_date",
    "sg_amount",
    "remitted_date",
    "fund_received_date",
    "first_contribution_to_fund",
    "out_of_cycle",
    "next_standard_payday",
    "defined_benefit",
]

EXPECTED_FIXTURE_ROWS = {
    "timely_remittance_no_receipt.csv": [
        "SYN001",
        "2026-08-06",
        "120.00",
        "2026-08-14",
        "",
        "no",
        "no",
        "",
        "no",
    ],
    "late_remittance_no_receipt.csv": [
        "SYN001",
        "2026-08-06",
        "120.00",
        "2026-08-18",
        "",
        "no",
        "no",
        "",
        "no",
    ],
    "receipt_on_due_date.csv": [
        "SYN001",
        "2026-08-06",
        "120.00",
        "2026-08-14",
        "2026-08-17",
        "no",
        "no",
        "",
        "no",
    ],
    "receipt_after_due_date.csv": [
        "SYN001",
        "2026-08-06",
        "120.00",
        "2026-08-14",
        "2026-08-18",
        "no",
        "no",
        "",
        "no",
    ],
}


@pytest.mark.parametrize(
    ("fixture", "expected_due_date", "expected_verdict", "expected_exit"),
    [
        (
            scenario["fixture"],
            scenario["expected_due_date"],
            scenario["expected_verdict"],
            scenario["expected_exit"],
        )
        for scenario in EXPECTED_CONTRACT["scenarios"]
    ],
)
def test_evidence_boundary_scenarios(
    tmp_path: Path,
    fixture: str,
    expected_due_date: str,
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
    assert len(rows) == 2
    assert rows[1]["employee_id"] == "NOTE"
    assert rows[0]["due_date"] == expected_due_date
    assert rows[0]["verdict"] == expected_verdict


@pytest.mark.parametrize(("fixture", "expected_row"), EXPECTED_FIXTURE_ROWS.items())
def test_fabricated_fixture_has_exact_approved_header_and_row(
    fixture: str,
    expected_row: list[str],
) -> None:
    with (PACK / "fixtures" / fixture).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    assert rows == [FIXTURE_HEADER, expected_row]


def test_machine_readable_contract_matches_the_exact_ordered_contract() -> None:
    contract = json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert contract == EXPECTED_CONTRACT


def test_evaluation_guide_locks_the_ordered_public_evidence_contract() -> None:
    readme = (PACK / "README.md").read_text(encoding="utf-8")
    headings = [line for line in readme.splitlines() if line.startswith("## ")]
    reproduction_block = readme.split("```bash\n", 1)[1].split("\n```", 1)[0]
    normalised = " ".join(readme.split())

    assert headings == GUIDE_HEADINGS
    assert reproduction_block.splitlines() == REPRODUCTION_COMMANDS
    assert EXPECTED_CONTRACT["human_decision"] in readme
    for statement in (
        "Timely remittance with no receipt remains `AT_RISK` and cannot prove on-time.",
        "Remittance after the due date can establish lateness even without a receipt, "
        "so the result is `LATE`.",
        "Eligible receipt on the due date can produce `ON_TIME` for the supplied facts.",
        "Receipt after the due date produces `LATE`.",
    ):
        assert statement in normalised
    assert (
        "These four rows do not establish fund eligibility, statutory allocation, "
        "qualifying-earnings classification, assessments or final ATO amounts." in normalised
    )
    assert (
        "They do not test transition allocation, item 4 extensions, out-of-cycle "
        "payments, exceptional-circumstances determinations, "
        "maximum-contribution-base limits or fund-deed, award and "
        "enterprise-agreement obligations." in normalised
    )
    assert (
        "The checker and its monetary output remain experimental review aids, not "
        "tax, legal or financial advice, an ATO assessment or a compliance "
        "determination." in normalised
    )
    assert (
        "`v0.1.2` is the latest published product prerelease. That release tag does "
        "not contain this new evaluation directory. After this pull request is "
        "merged, the evaluation will be protected by the permanent link to its "
        "merge commit." in normalised
    )
    assert "case study" not in readme.casefold()


def test_product_discovery_files_link_the_pack_exactly_once_each() -> None:
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    llms = (ROOT / "llms.txt").read_text(encoding="utf-8")

    assert root_readme.count(PACK_LINK) == 1
    assert f"[fabricated Payday Super evidence evaluation]({PACK_LINK})" in root_readme
    assert llms.count(PACK_LINK) == 1
    assert f"- **Evidence Evaluation**: {PACK_LINK}" in llms.splitlines()


def test_only_declared_evaluation_csvs_are_allowlisted() -> None:
    allowed = {
        "evaluation/payday_super_evidence/fixtures/timely_remittance_no_receipt.csv",
        "evaluation/payday_super_evidence/fixtures/late_remittance_no_receipt.csv",
        "evaluation/payday_super_evidence/fixtures/receipt_on_due_date.csv",
        "evaluation/payday_super_evidence/fixtures/receipt_after_due_date.csv",
    }
    rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    evaluation_prefix = "!evaluation/payday_super_evidence/fixtures/"
    evaluation_allowlist = {
        rule.removeprefix("!") for rule in rules if rule.startswith(evaluation_prefix)
    }
    assert evaluation_allowlist == allowed
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
