from datetime import date, timedelta
from decimal import Decimal

import pytest

from paydaysuper.rates import GicQuarter, GicTable, load_gic
from paydaysuper.sgc import exposure_range, notional_earnings, uplift_scenarios


@pytest.fixture(scope="module")
def gic():
    return load_gic()


def test_daily_rate_is_annual_over_365(gic):
    assert gic.daily_rate(date(2026, 8, 15)) == Decimal("11.43") / 100 / 365


def test_rate_table_covers_prior_quarter(gic):
    assert gic.daily_rate(date(2026, 5, 1)) == Decimal("10.96") / 100 / 365


def test_staleness_warns_past_the_table(gic):
    assert gic.staleness(date(2026, 9, 30)) is None
    assert "GIC rate table ends" in gic.staleness(date(2026, 12, 1))


def test_no_accrual_before_the_deadline_passes(gic):
    due = date(2026, 7, 20)
    assert notional_earnings(Decimal("600"), due, due, gic) == Decimal("0")


def test_accrual_starts_the_day_after_the_deadline(gic):
    """LCR 2026/D3 example: usual period ends 18 Jun 2027, notional earnings
    begin to accrue from 19 Jun 2027."""
    due = date(2026, 7, 20)
    one_day = notional_earnings(Decimal("600"), due, date(2026, 7, 21), gic)
    assert one_day == Decimal("600") * gic.daily_rate(date(2026, 7, 21))


def test_accrual_compounds_daily(gic):
    due = date(2026, 7, 20)
    shortfall = Decimal("600")
    got = notional_earnings(shortfall, due, date(2026, 7, 23), gic)

    expected = Decimal("0")
    for offset in (1, 2, 3):
        day = due + timedelta(days=offset)
        expected += (shortfall + expected) * gic.daily_rate(day)
    assert got == expected
    # compounding beats simple interest
    assert got > shortfall * gic.daily_rate(date(2026, 7, 21)) * 3


def test_accrual_uses_the_rate_of_each_quarter():
    table = GicTable(
        [
            GicQuarter(date(2026, 7, 1), date(2026, 9, 30), Decimal("11.43")),
            GicQuarter(date(2026, 10, 1), date(2026, 12, 31), Decimal("20.00")),
        ]
    )
    due = date(2026, 9, 29)
    got = notional_earnings(Decimal("1000"), due, date(2026, 10, 1), table)

    expected = Decimal("0")
    for day, pct in ((date(2026, 9, 30), "11.43"), (date(2026, 10, 1), "20.00")):
        rate = Decimal(pct) / 100 / 365
        expected += (Decimal("1000") + expected) * rate
    assert got == expected


def test_negative_shortfall_rejected(gic):
    with pytest.raises(ValueError):
        notional_earnings(Decimal("-1"), date(2026, 7, 20), date(2026, 7, 25), gic)


def test_uplift_matrix_percentages():
    scenarios = uplift_scenarios(Decimal("1000"), Decimal("0"))
    assert scenarios["clean_history"]["vds_within_30d"] == Decimal("0")
    assert scenarios["clean_history"]["vds_31_60d"] == Decimal("50")
    assert scenarios["clean_history"]["vds_61_120d"] == Decimal("100")
    assert scenarios["clean_history"]["vds_after_120d"] == Decimal("250")
    assert scenarios["clean_history"]["no_vds"] == Decimal("400")
    assert scenarios["prior_history"]["no_vds"] == Decimal("600")


def test_uplift_applies_to_shortfall_plus_notional_earnings():
    scenarios = uplift_scenarios(Decimal("1000"), Decimal("100"))
    assert scenarios["prior_history"]["no_vds"] == Decimal("660")


def test_exposure_range_spans_best_and_worst_uplift():
    low, high = exposure_range(Decimal("1000"), Decimal("100"))
    assert low == Decimal("1100")            # uplift 0%
    assert high == Decimal("1100") + Decimal("660")  # uplift 60%
    assert low < high
