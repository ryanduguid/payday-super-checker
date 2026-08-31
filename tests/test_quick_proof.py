"""Checks for the fabricated Payday Super proof shown in the README."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "assets" / "quick-proof.svg"
TRANSCRIPT = ROOT / "assets" / "quick-proof.md"


def test_renderer_check_accepts_the_committed_assets():
    result = subprocess.run(
        [sys.executable, "tools/render_quick_proof.py", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_proof_is_tied_to_the_fabricated_cli_run():
    transcript = TRANSCRIPT.read_text(encoding="utf-8")
    assert "examples/sample_payrun_no_transition.csv" in transcript
    assert "ON_TIME: 3  AT_RISK: 1  LATE: 1  UNPAID: 1" in transcript
    assert "shortfall $780.00" in transcript
    assert "experimental estimated SG charge $788.76 - $1262.02" in transcript
    assert "Educational tool, not advice" in transcript


def test_readme_places_the_proof_and_check_before_install():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    proof = "[![Fabricated Payday Super review](assets/quick-proof.svg)](assets/quick-proof.md)"
    command = "python tools/render_quick_proof.py --check"
    assert proof in readme
    assert command in readme
    assert readme.index(proof) < readme.index("## Install")
    assert SVG.name in proof
