import json
from datetime import date
from decimal import Decimal

import pytest

from paydaysuper import rates as rates_module
from paydaysuper.rates import RatesError, load_gic


def write_table(tmp_path, quarters):
    (tmp_path / "gic_rates.json").write_text(
        json.dumps({"quarters": quarters}), encoding="utf-8"
    )
    return tmp_path


GOOD = {"from": "2026-07-01", "to": "2026-09-30", "annual_pct": "11.43", "seen": "2026-08-02"}


def test_a_good_table_still_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(rates_module, "DATA_DIR", write_table(tmp_path, [GOOD]))
    table = load_gic()
    assert table.last_known == date(2026, 9, 30)
    assert table.daily_rate(date(2026, 8, 1)) == Decimal("11.43") / 100 / 365


def test_unsorted_contiguous_quarters_are_sorted_and_accepted(tmp_path, monkeypatch):
    following = dict(GOOD, **{"from": "2026-10-01", "to": "2026-12-31"})
    monkeypatch.setattr(
        rates_module, "DATA_DIR", write_table(tmp_path, [following, GOOD])
    )

    table = load_gic()

    assert table.last_known == date(2026, 12, 31)
    assert table.daily_rate(date(2026, 9, 30)) == Decimal("11.43") / 100 / 365


def test_a_reversed_interval_is_refused(tmp_path, monkeypatch):
    reversed_quarter = dict(GOOD, **{"from": "2026-09-30", "to": "2026-07-01"})
    monkeypatch.setattr(
        rates_module, "DATA_DIR", write_table(tmp_path, [reversed_quarter])
    )

    with pytest.raises(RatesError, match="ends before it starts") as exc:
        load_gic()

    assert "2026-09-30 to 2026-07-01" in str(exc.value)


@pytest.mark.parametrize(
    ("following_start", "relation"),
    [("2026-09-30", "overlap"), ("2026-10-02", "gap")],
)
def test_non_contiguous_intervals_name_both_ranges(
    tmp_path, monkeypatch, following_start, relation
):
    following = dict(GOOD, **{"from": following_start, "to": "2026-12-31"})
    monkeypatch.setattr(
        rates_module, "DATA_DIR", write_table(tmp_path, [GOOD, following])
    )

    with pytest.raises(RatesError, match=relation) as exc:
        load_gic()

    message = str(exc.value)
    assert "2026-07-01 to 2026-09-30" in message
    assert f"{following_start} to 2026-12-31" in message


def test_an_unreadable_rate_raises_rates_error_naming_the_entry(tmp_path, monkeypatch):
    """decimal.InvalidOperation is an ArithmeticError, so an unguarded
    Decimal() here escaped the CLI's handler and printed a traceback."""
    bad = dict(GOOD, annual_pct="eleven point four")
    monkeypatch.setattr(rates_module, "DATA_DIR", write_table(tmp_path, [bad]))
    with pytest.raises(RatesError) as exc:
        load_gic()
    message = str(exc.value)
    assert "eleven point four" in message
    assert "2026-07-01 to 2026-09-30" in message


@pytest.mark.parametrize("value", ["nan", "NaN", "Infinity", "-Infinity", "sNaN"])
def test_a_non_finite_rate_is_refused(tmp_path, monkeypatch, value):
    """Decimal builds these happily, and every money figure downstream would
    come out nan without a word said."""
    monkeypatch.setattr(
        rates_module, "DATA_DIR", write_table(tmp_path, [dict(GOOD, annual_pct=value)])
    )
    with pytest.raises(RatesError) as exc:
        load_gic()
    assert "finite" in str(exc.value)


def test_a_negative_rate_is_refused(tmp_path, monkeypatch):
    """A stray minus sign printed notional earnings of $-112.12 and an SG
    charge estimate running from $-112.12 to $-179.39, bounds inverted."""
    monkeypatch.setattr(
        rates_module, "DATA_DIR", write_table(tmp_path, [dict(GOOD, annual_pct="-11.43")])
    )
    with pytest.raises(RatesError) as exc:
        load_gic()
    message = str(exc.value)
    assert "-11.43" in message
    assert "2026-07-01 to 2026-09-30" in message
    assert "negative" in message


def test_a_rate_above_the_ceiling_is_refused(tmp_path, monkeypatch):
    """A dropped decimal point turned 11.43 into 1143, which billed 612934.92
    of notional earnings on a 10000.00 shortfall."""
    monkeypatch.setattr(
        rates_module, "DATA_DIR", write_table(tmp_path, [dict(GOOD, annual_pct="1143")])
    )
    with pytest.raises(RatesError) as exc:
        load_gic()
    message = str(exc.value)
    assert "1143" in message
    assert "2026-07-01 to 2026-09-30" in message
    assert "100%" in message


def test_a_zero_rate_is_accepted(tmp_path, monkeypatch):
    """The boundary. Zero is not a sign error, so the guard must test < 0,
    not <= 0, or a quarter with no interest stops the whole run."""
    monkeypatch.setattr(
        rates_module, "DATA_DIR", write_table(tmp_path, [dict(GOOD, annual_pct="0")])
    )
    table = load_gic()
    assert table.daily_rate(date(2026, 8, 1)) == Decimal("0")


def test_the_ceiling_itself_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(
        rates_module, "DATA_DIR", write_table(tmp_path, [dict(GOOD, annual_pct="100")])
    )
    assert load_gic().daily_rate(date(2026, 8, 1)) == Decimal("100") / 100 / 365


def test_a_missing_quarters_key_is_named(tmp_path, monkeypatch):
    """The hardening covered every field of every quarter and left the key
    they hang off unguarded: a renamed 'quarters' raised KeyError, which the
    CLI's handler tuple does not catch."""
    (tmp_path / "gic_rates.json").write_text(
        json.dumps({"gic_quarters": [GOOD]}), encoding="utf-8"
    )
    monkeypatch.setattr(rates_module, "DATA_DIR", tmp_path)
    with pytest.raises(RatesError) as exc:
        load_gic()
    message = str(exc.value)
    assert "quarters" in message
    assert "gic_rates.json" in message


def test_a_list_at_the_top_level_is_refused(tmp_path, monkeypatch):
    """A JSON list gave TypeError, which the CLI does not catch either."""
    (tmp_path / "gic_rates.json").write_text(json.dumps([GOOD]), encoding="utf-8")
    monkeypatch.setattr(rates_module, "DATA_DIR", tmp_path)
    with pytest.raises(RatesError) as exc:
        load_gic()
    assert "must be a JSON object" in str(exc.value)


def test_quarters_must_be_a_list(tmp_path, monkeypatch):
    (tmp_path / "gic_rates.json").write_text(
        json.dumps({"quarters": GOOD}), encoding="utf-8"
    )
    monkeypatch.setattr(rates_module, "DATA_DIR", tmp_path)
    with pytest.raises(RatesError) as exc:
        load_gic()
    assert "must be a list" in str(exc.value)


def test_a_table_that_is_not_json_is_a_rates_error_naming_the_file(
    tmp_path, monkeypatch
):
    """json.JSONDecodeError is a ValueError, so the CLI already printed
    "error: ..." for a hand-edit that broke the JSON itself, but the message
    was a bare parse error with no path in it. Re-raised as RatesError naming
    the file, the way profiles.load_profiles already does."""
    (tmp_path / "gic_rates.json").write_text('{"quarters": [,]}', encoding="utf-8")
    monkeypatch.setattr(rates_module, "DATA_DIR", tmp_path)
    with pytest.raises(RatesError) as exc:
        load_gic()
    message = str(exc.value)
    assert "is not valid JSON" in message
    assert "gic_rates.json" in message


def test_the_cli_prints_a_top_level_rates_error_without_a_traceback(
    tmp_path, monkeypatch, capsys
):
    from conftest import SAMPLE
    from paydaysuper.cli import EXIT_ERROR, main

    (tmp_path / "gic_rates.json").write_text(
        json.dumps({"gic_quarters": [GOOD]}), encoding="utf-8"
    )
    monkeypatch.setattr(rates_module, "DATA_DIR", tmp_path)
    assert main([str(SAMPLE), "-o", str(tmp_path / "r.csv"), "--as-at", "2026-08-10"]) == (
        EXIT_ERROR
    )
    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert "Traceback" not in err
    assert "quarters" in err


def test_a_missing_rate_key_is_named(tmp_path, monkeypatch):
    entry = {k: v for k, v in GOOD.items() if k != "annual_pct"}
    monkeypatch.setattr(rates_module, "DATA_DIR", write_table(tmp_path, [entry]))
    with pytest.raises(RatesError) as exc:
        load_gic()
    assert "annual_pct" in str(exc.value)


def test_a_null_rate_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(
        rates_module, "DATA_DIR", write_table(tmp_path, [dict(GOOD, annual_pct=None)])
    )
    with pytest.raises(RatesError):
        load_gic()


def test_an_unreadable_quarter_date_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(
        rates_module, "DATA_DIR", write_table(tmp_path, [dict(GOOD, to="30/09/2026")])
    )
    with pytest.raises(RatesError) as exc:
        load_gic()
    assert "YYYY-MM-DD" in str(exc.value)


def test_the_cli_prints_a_rate_error_without_a_traceback(tmp_path, monkeypatch, capsys):
    from conftest import SAMPLE
    from paydaysuper.cli import EXIT_ERROR, main

    monkeypatch.setattr(
        rates_module,
        "DATA_DIR",
        write_table(tmp_path, [dict(GOOD, annual_pct="11,43")]),
    )
    assert main([str(SAMPLE), "-o", str(tmp_path / "r.csv"), "--as-at", "2026-08-10"]) == (
        EXIT_ERROR
    )
    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert "Traceback" not in err
