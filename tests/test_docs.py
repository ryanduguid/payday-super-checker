"""Guards on the primary-source review and the user-facing claims it settled."""

import json

from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
README = Path(__file__).resolve().parents[1] / "README.md"
REVIEW = DOCS / "primary-source-review-2026-08-15.md"
RATES = Path(__file__).resolve().parents[1] / "paydaysuper" / "data" / "rates.json"
CALENDAR = (
    Path(__file__).resolve().parents[1]
    / "paydaysuper"
    / "data"
    / "business_days.json"
)
GENERATOR = (
    Path(__file__).resolve().parents[1] / "tools" / "generate_calendar.py"
)
LOCKED_CALENDAR_COMMAND = (
    "uv run --locked --extra dev --python 3.12 "
    "python tools/generate_calendar.py > paydaysuper/data/business_days.json"
)

def test_rounding_authority_and_experimental_boundary_stay_visible():
    """LCR 2026/3 settled the assessment-level five-cent rule, not this
    tool's per-line display boundary. The distinction must survive in both
    implementation design and user guidance."""
    design = (DOCS / "design.md").read_text(encoding="utf-8")
    review = REVIEW.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    for document in (design, review, readme):
        assert "ROUND_HALF_UP" in document
        assert "TAA 1953 s 16B" in document
        assert "final assessed" in document
        assert "experimental" in document.lower()
    assert "nearest multiple of five cents" in design
    assert "implementation choice" in review


def test_final_out_of_cycle_determination_is_pinned_in_user_guidance():
    """The final instrument, its closed list and conditions must stay visible."""
    readme = README.read_text(encoding="utf-8")
    review = REVIEW.read_text(encoding="utf-8")

    for document in (readme,):
        assert "F2026L00784" in document
        for kind in (
            "allowances",
            "bonuses",
            "commissions",
            "loadings",
            "payments in advance",
            "back payments",
        ):
            assert kind in document
        assert "established timing, pattern or schedule" in document
        assert "subsequent" in document

    assert "LI 2026/20" in review
    assert "does not display that shorthand" in review
    assert "registered identifier and text control" in review


def test_final_ruling_status_and_transition_gate_are_current():
    review = REVIEW.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    design = (DOCS / "design.md").read_text(encoding="utf-8")

    for document in (review, readme, design):
        for final in ("LCR 2026/1", "LCR 2026/2", "LCR 2026/3"):
            assert final in document
        assert "LCR 2026/D1" in document
        assert "draft" in document
        assert "--confirm-transition-allocation" in document
    assert "--confirm-remittance-only" in readme
    assert "--confirm-remittance-only" in design
    assert "5 August 2026" in review
    assert "Department of Education v Commissioner of Taxation" in review


def test_item4_and_import_allocation_boundaries_stay_visible():
    review = REVIEW.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    design = (DOCS / "design.md").read_text(encoding="utf-8")

    for document in (review, readme, design):
        assert "LCR 2026/2" in document
        assert "fund-receipt order" in document
        assert "earliest" in document and "shortfall" in document
        assert "--confirm-statutory-allocation" in document
        assert "item 4" in document.lower()
        assert "on-time fund receipt" in document
        assert "UNKNOWN" in document


def test_regulations_11_and_12_are_an_operator_input_boundary():
    review = REVIEW.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    design = (DOCS / "design.md").read_text(encoding="utf-8")

    for document in (review, readme, design):
        assert "regulations 11 and 12" in document.lower()
        assert "operator" in document.lower()
        assert "sg_amount" in document


def test_primary_review_pins_regulations_and_direct_mcb_provenance():
    review = REVIEW.read_text(encoding="utf-8")
    rates = RATES.read_text(encoding="utf-8")

    for regulation in ("Regulation 11", "Regulation 12", "Regulation 13"):
        assert regulation in review
    for regulation in ("13A", "13B", "13C", "13D"):
        assert f"Regulation {regulation}" in review
    assert "F2026C00535" in review
    assert "$270,830" in review
    assert '"seen": "2026-08-15"' in rates
    assert '"cross_check"' in rates
    assert "search-result snippets" not in rates


def test_calendar_authority_horizon_and_exclusions_are_pinned():
    review = REVIEW.read_text(encoding="utf-8")
    normalised_review = " ".join(review.split())
    calendar = CALENDAR.read_text(encoding="utf-8")
    calendar_data = json.loads(calendar)

    assert '"verified_until": "2027-08-31"' in calendar
    assert '"checked": "2026-08-15"' in calendar
    for jurisdiction in ("ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"):
        assert f'"{jurisdiction}": "http' in calendar
    assert "Melbourne Cup Day" not in {
        entry["name"] for entry in calendar_data["non_business_days"]
    }
    assert all(
        entry["provisional"]
        for entry in calendar_data["non_business_days"]
        if entry["date"].startswith("2028-")
    )
    assert "WA's official page" in review
    assert "Legislative Council second reading" in normalised_review
    assert "subject to the AFL schedule" in normalised_review


def test_calendar_regeneration_guidance_uses_the_locked_environment():
    readme = README.read_text(encoding="utf-8")
    generator = GENERATOR.read_text(encoding="utf-8")

    for guidance in (readme, generator):
        assert LOCKED_CALENDAR_COMMAND in guidance
    assert "holidays==" not in readme
    assert "pip install holidays==" not in generator
