from pathlib import Path

# One sample file, used by both the tests and the README, so an edit to it
# cannot leave the documented output quietly wrong.
SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample_payrun.csv"
REMITTANCE_ONLY = (
    Path(__file__).resolve().parents[1] / "examples" / "sample_remittance_only.csv"
)
