"""Seeded date-boundary and exact-money properties."""

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import example, given, seed, settings, strategies as st

from paydaysuper.calendar import load_calendar
from paydaysuper.sgc import exposure_range, uplift_scenarios


CALENDAR = load_calendar()
PROPERTY_SETTINGS = settings(max_examples=100, database=None, deadline=None)
NONNEGATIVE_MONEY = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1000000000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


@seed(0xDA7E)
@PROPERTY_SETTINGS
@example(date(2026, 12, 24), 7)
@example(date(2027, 3, 25), 7)
@example(date(2026, 8, 1), 0)
@given(
    start=st.dates(min_value=date(2026, 7, 1), max_value=date(2027, 7, 1)),
    count=st.integers(min_value=0, max_value=40),
)
def test_business_day_addition_counts_only_days_after_the_start(
    start: date, count: int
) -> None:
    """Counting the start, a weekend or a confirmed holiday must break this."""
    result = CALENDAR.add_business_days(start, count)

    if count == 0:
        assert result == start
        return

    assert result > start
    assert CALENDAR.is_business_day(result)
    elapsed = (result - start).days
    counted = sum(
        CALENDAR.is_business_day(start + timedelta(days=offset))
        for offset in range(1, elapsed + 1)
    )
    before_result = sum(
        CALENDAR.is_business_day(start + timedelta(days=offset))
        for offset in range(1, elapsed)
    )
    assert counted == count
    assert before_result == count - 1


@seed(0x5AC)
@PROPERTY_SETTINGS
@example(Decimal("0"), Decimal("0"))
@example(Decimal("1000"), Decimal("100"))
@given(final_shortfall=NONNEGATIVE_MONEY, nec=NONNEGATIVE_MONEY)
def test_exposure_scenarios_conserve_the_shortfall_plus_nec_base(
    final_shortfall: Decimal, nec: Decimal
) -> None:
    """Changing an uplift rate or omitting NEC from its base must break this."""
    base = final_shortfall + nec
    expected_percentages = {
        "clean_history": {
            "vds_within_30d": Decimal("0"),
            "vds_31_60d": Decimal("5"),
            "vds_61_120d": Decimal("10"),
            "vds_after_120d": Decimal("25"),
            "no_vds": Decimal("40"),
        },
        "prior_history": {
            "vds_within_30d": Decimal("20"),
            "vds_31_60d": Decimal("25"),
            "vds_61_120d": Decimal("30"),
            "vds_after_120d": Decimal("45"),
            "no_vds": Decimal("60"),
        },
    }

    scenarios = uplift_scenarios(final_shortfall, nec)
    for history, row in expected_percentages.items():
        for scenario, percentage in row.items():
            assert scenarios[history][scenario] == base * percentage / Decimal("100")

    low, high = exposure_range(final_shortfall, nec)
    assert low == base
    assert high == base * Decimal("1.60")
