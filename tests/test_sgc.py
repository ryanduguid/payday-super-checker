from datetime import date, timedelta
from decimal import Decimal

import pytest

from paydaysuper.rates import GicQuarter, GicTable, RatesError, load_gic
from paydaysuper.sgc import exposure_range, notional_earnings, uplift_scenarios


@pytest.fixture(scope="module")
def gic():
    return load_gic()


def test_daily_rate_divides_by_365_in_a_non_leap_year(gic):
    """365 is a fact about 2026, not the rule. TAA 1953 s 8AAD divides the
    quarter's annual rate by the number of days in the calendar year of that
    day, so 2028 divides by 366 - test_daily_rate_uses_366_in_a_leap_year
    below. This test was named "..._is_annual_over_365", which read as a
    general licence for /365 in the one file a maintainer checks before
    changing rates.py, and /365 everywhere is the leap-year defect."""
    assert gic.daily_rate(date(2026, 8, 15)) == Decimal("11.43") / 100 / 365


def test_rate_table_covers_prior_quarter(gic):
    assert gic.daily_rate(date(2026, 5, 1)) == Decimal("10.96") / 100 / 365


def test_staleness_warns_past_the_shipped_table(gic):
    """Pinned to the table's own horizon so a quarterly data update does
    not turn this red."""
    from datetime import timedelta

    assert gic.staleness(gic.last_known) is None
    assert "GIC rate table ends" in gic.staleness(gic.last_known + timedelta(days=1))


def test_no_accrual_before_the_deadline_passes(gic):
    due = date(2026, 7, 20)
    assert notional_earnings(Decimal("600"), due, due, gic) == Decimal("0")


def test_accrual_starts_the_day_after_the_deadline(gic):
    """LCR 2026/3 example: usual period ends 18 Jun 2027, notional earnings
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
    for _day, pct in ((date(2026, 9, 30), "11.43"), (date(2026, 10, 1), "20.00")):
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


def test_lcr_2026_d3_accrual_boundary(gic):
    """LCR 2026/3 worked example: usual period ends 18 Jun 2027, so
    notional earnings begin accruing on 19 Jun 2027, not before."""
    due = date(2027, 6, 18)
    assert notional_earnings(Decimal("1000"), due, due, gic) == Decimal("0")
    assert notional_earnings(Decimal("1000"), due, date(2027, 6, 19), gic) > Decimal("0")


def test_daily_rate_uses_366_in_a_leap_year():
    """TAA 1953 s 8AAD divides by the days in the calendar year."""
    table = GicTable([GicQuarter(date(2027, 1, 1), date(2028, 12, 31), Decimal("11.43"))])
    assert table.daily_rate(date(2027, 3, 1)) == Decimal("11.43") / 100 / 365
    assert table.daily_rate(date(2028, 3, 1)) == Decimal("11.43") / 100 / 366


def test_daily_rate_before_the_table_raises():
    table = GicTable([GicQuarter(date(2026, 7, 1), date(2026, 9, 30), Decimal("11.43"))])
    with pytest.raises(RatesError):
        table.daily_rate(date(2026, 6, 1))


def test_daily_rate_past_the_table_falls_back_with_a_warning():
    table = GicTable([GicQuarter(date(2026, 7, 1), date(2026, 9, 30), Decimal("11.43"))])
    beyond = date(2026, 12, 1)
    assert table.daily_rate(beyond) == Decimal("11.43") / 100 / 365
    assert "11.43" in table.staleness(beyond)
    assert table.staleness(date(2026, 9, 30)) is None
