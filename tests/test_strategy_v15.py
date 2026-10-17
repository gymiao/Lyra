from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from personal_quant.common import QuantError
from personal_quant.strategies.adapter import decode_signal, resolve, signal_v2
from personal_quant.strategies.monthly import signal as legacy_signal
from personal_quant.strategies.registry import definitions
from personal_quant.strategies.spec import DataBundle, StrategySpec
from personal_quant.strategies.templates import evaluate


def test_spec_freezes_parameters_and_ignores_display_identity():
    original = StrategySpec.create("momentum_rotation", ["SPY", "IEF", "GLD"])
    copied = original.content()
    copied.update(name="重命名", strategy_id="clone", revision=2)
    clone = StrategySpec.from_dict(copied)
    assert clone.spec_hash == original.spec_hash
    copied["parameters"]["lookback"] = 63
    assert StrategySpec.from_dict(copied).spec_hash != original.spec_hash
    assert original.content()["parameters"]["lookback"] == 126
    assert original.required_prices == 127


@pytest.mark.parametrize("parameter,value", [("top_k", True), ("top_k", 4), ("lookback", 1.5), ("lookback", 0), ("nonexistent", 1)])
def test_invalid_template_parameters_are_not_silently_normalized(parameter, value):
    with pytest.raises(QuantError):
        StrategySpec.create("momentum_rotation", ["SPY", "IEF", "GLD"], parameters={parameter: value})


def test_missing_base_weights_and_false_version_are_rejected():
    with pytest.raises(QuantError, match="基础权重"):
        StrategySpec.create("mean_reversion", ["SPY", "IEF"])
    body = StrategySpec.create("inverse_volatility", ["SPY", "IEF"]).content()
    body["implementation_version"] = "99.0"
    with pytest.raises(QuantError, match="未安装"):
        StrategySpec.from_dict(body)


def test_six_registered_templates_are_explicit():
    assert set(definitions()) == {"fixed", "trend", "momentum_rotation", "mean_reversion", "inverse_volatility", "multi_factor"}


def test_momentum_keeps_unfilled_slots_in_cash():
    spec = StrategySpec.create("momentum_rotation", ["A", "B", "C"], parameters={"lookback": 1, "top_k": 2})
    prices = pd.DataFrame({"A": [100., 112.], "B": [100., 108.], "C": [100., 98.]})
    weights, _, _ = evaluate(prices, spec)
    assert weights == {"A": .475, "B": .475, "C": 0.}
    prices.loc[1, "B"] = 99
    weights, _, _ = evaluate(prices, spec)
    assert weights == {"A": .475, "B": 0., "C": 0.}


def test_reversion_threshold_and_no_trigger_are_independent():
    # Each pair has a mean of exactly 100: deviations are -6%, -2%, +3%.
    prices = pd.DataFrame({"A": [106., 94.], "B": [102., 98.], "C": [97., 103.]})
    spec = StrategySpec.create("mean_reversion", ["A", "B", "C"],
        parameters={"lookback": 2, "threshold": .05}, weights={"A": .3, "B": .3, "C": .3})
    assert evaluate(prices, spec)[0] == {"A": .3, "B": 0., "C": 0.}
    prices["A"] = [105., 95.]
    assert evaluate(prices, spec)[0]["A"] == .3
    prices["A"] = [104.99, 95.01]
    assert evaluate(prices, spec)[0]["A"] == 0


def test_inverse_volatility_ratio_and_cap_preserve_cash():
    # A has daily returns +/-1%, B +/-2%: standard deviations have ratio 1:2.
    prices = pd.DataFrame({"A": [100, 101, 99.99], "B": [100, 102, 99.96]})
    spec = StrategySpec.create("inverse_volatility", ["A", "B"],
        parameters={"lookback": 2}, invested_budget=.9)
    assert evaluate(prices, spec)[0] == pytest.approx({"A": .6, "B": .3})
    body = spec.content(); body["weight_cap"] = .5
    assert evaluate(prices, StrategySpec.from_dict(body))[0] == pytest.approx({"A": .5, "B": .3})
    with pytest.raises(QuantError, match="波动率"):
        evaluate(pd.DataFrame({"A": [100]*3, "B": [100]*3}), spec)


def test_factor_ties_use_stable_asset_id_not_input_order():
    spec = StrategySpec.create("multi_factor", ["C", "A", "B"], parameters={"mode": "fundamental", "top_k": 2})
    factors = pd.DataFrame({"book_to_market": [3., 2., 1.], "roe_ttm": [.1, .2, .3]}, index=["A", "B", "C"])
    prices = pd.DataFrame({"A": [100.], "B": [100.], "C": [100.]})
    weights, _, scores = evaluate(prices, spec, factors)
    assert scores == {"A": .5, "B": .5, "C": .5}
    assert weights == {"A": .475, "B": .475, "C": 0.}
    assert evaluate(prices, spec, factors.iloc[::-1])[0] == weights
    with pytest.raises(QuantError):
        evaluate(prices, spec, factors.drop(index="B"))


def test_v1_config_hash_and_signal_round_trip_remain_unchanged(config, market):
    assert "strategy_spec" not in config.content()
    _, frame, metadata, calendar = market
    value = legacy_signal(frame, calendar, config, "2024-07-31", "fixed", metadata["snapshot_id"])
    assert decode_signal(value.content()).content() == value.content()
    assert "schema_version" not in decode_signal(value.content()).content()


def make_signal(market, config, *, frame=None, decision_time=None):
    _, original, metadata, calendar = market
    spec = StrategySpec.create("momentum_rotation", config.symbols, parameters={"lookback": 10, "top_k": 2})
    config = resolve(config, spec).config
    bundle = DataBundle(metadata["snapshot_id"], calendar.hash)
    return signal_v2(original if frame is None else frame, calendar, config, spec, "2024-07-31", bundle, decision_time=decision_time)


def test_future_prices_cannot_change_past_v2_decisions(market, config):
    original = make_signal(market, config)
    frame = market[1].copy()
    frame.loc[frame.session_date > "2024-07-31", "adj_close"] *= 5
    later = make_signal(market, config, frame=frame)
    assert original.signal_id == later.signal_id
    assert original.target_weights == later.target_weights
    assert decode_signal(original.content()).content() == original.content()


def test_missing_and_unpublished_prices_do_not_become_cash_signal(market, config):
    frame = market[1].copy()
    frame = frame.loc[~((frame.session_date == "2024-07-31") & (frame.symbol == "SPY"))]
    blocked = make_signal(market, config, frame=frame)
    assert blocked.status == "INSUFFICIENT_DATA"
    assert blocked.target_weights is None
    frame = market[1].copy()
    frame.loc[(frame.session_date == "2024-07-31") & (frame.symbol == "SPY"), "available_at"] = pd.Timestamp("2024-08-01T00:00:00Z")
    assert make_signal(market, config, frame=frame).status == "INSUFFICIENT_DATA"
    with pytest.raises(QuantError, match="发布"):
        make_signal(market, config, decision_time="2024-07-31T20:10:00Z")


def test_conflicting_frozen_config_and_unknown_signal_are_rejected(config):
    spec = StrategySpec.create("momentum_rotation", config.symbols)
    adapted = resolve(config, spec).config
    with pytest.raises(QuantError, match="冲突"):
        replace(adapted, lookback=999).validate()
    with pytest.raises(QuantError, match="版本"):
        decode_signal({"schema_version": 99})
