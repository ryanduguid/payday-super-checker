"""Guards on the two documents that have to agree with each other.

`docs/design.md` describes what ships; `docs/research-notes-2026-08-02.md`
records what was verified and what was not. A rewrite of the design page's
rounding text dropped the last note that the rounding rule is an unverified
choice, leaving the design page asserting an arithmetic that the research
notes still list as an open, release-blocking question, with nothing in the
suite to notice.
"""

from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"

# The open item, quoted from docs/research-notes-2026-08-02.md.
OPEN_ROUNDING_ITEM = "Do not hard-code rounding; compute in cents and flag."


def test_design_flags_the_rounding_rule_while_the_research_item_is_open():
    """paydaysuper rounds money to cents with ROUND_HALF_UP (report.money,
    report.cents, importers._amount through them), and no statutory or ATO
    rounding rule was ever verified. design.md has to say both: the rule it
    implements, and that the rule is this tool's choice pending the LCR
    2026/D3 worked examples. Describing only the first is how a reader ends
    up treating an unverified figure as settled."""
    research = (DOCS / "research-notes-2026-08-02.md").read_text(encoding="utf-8")
    design = (DOCS / "design.md").read_text(encoding="utf-8")

    assert OPEN_ROUNDING_ITEM in research, (
        "the rounding research item moved or was closed. If it is genuinely "
        "resolved, update design.md's caveat and this test together; do not "
        "delete one of them alone"
    )
    # What ships.
    assert "ROUND_HALF_UP" in design
    # That it is a choice, and what would settle it.
    assert "not a verified one" in design
    assert "LCR 2026/D3 worked examples" in design
