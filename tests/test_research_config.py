from dataclasses import replace

import pytest

from personal_quant.common import QuantError


@pytest.mark.parametrize("factor", [0, -1, True, 252.5])
def test_volatility_factor_requires_a_positive_integer(config, factor):
    with pytest.raises(QuantError, match="volatility_annual_factor"):
        replace(config, volatility_annual_factor=factor).validate()


@pytest.mark.parametrize("changes", [
    {"development_end": None},
    {"development_start": "2024-06-29", "development_end": "2024-06-28"},
    {"development_end": "2024-07-01"},
    {"evaluation_start": "2024-02-30"},
])
def test_research_periods_reject_missing_reversed_overlapping_or_invalid_dates(config, changes):
    with pytest.raises(QuantError):
        replace(config, **changes).validate()


@pytest.mark.parametrize("name", ["commission_bps", "max_weight", "cash_buffer", "lot_size", "research_capital", "demo_deposit"])
def test_numeric_risk_and_capital_parameters_reject_boolean(config, name):
    with pytest.raises(QuantError):
        replace(config, **{name: True}).validate()


def test_demo_funds_are_configured_separately_from_research(config, tmp_path, monkeypatch):
    from personal_quant.cli import demo_account
    monkeypatch.chdir(tmp_path)
    adjusted = replace(config, demo_deposit=5000, research_capital=12345)
    result = demo_account(adjusted)
    assert float(result["snapshot"]["deposits"]) == 5000
    assert adjusted.research_capital == 12345
