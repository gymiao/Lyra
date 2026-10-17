from dataclasses import replace
import json

import pandas as pd
import pytest

from personal_quant.common import QuantError
from personal_quant.research.backtest import run_research
from personal_quant.strategies.spec import StrategySpec


def members(config):
    return {"benchmark": StrategySpec.create("fixed", config.symbols,
                weights=dict(zip(config.symbols, [.3, .3, .3])), invested_budget=.9),
            "momentum_63": StrategySpec.create("momentum_rotation", config.symbols,
                name="相同展示名", parameters={"lookback": 63, "top_k": 2}),
            "momentum_126": StrategySpec.create("momentum_rotation", config.symbols,
                name="相同展示名", parameters={"lookback": 126, "top_k": 2})}


def test_same_template_versions_have_separate_engine_results(market, config, tmp_path):
    result = run_research(market[0], config, tmp_path / "research", members=members(config), benchmark="benchmark")
    assert set(result["metrics"]) == {"benchmark", "momentum_63", "momentum_126"}
    path = tmp_path / "research" / result["run_id"]
    nav = pd.read_csv(path / "nav.csv", index_col=0)
    assert list(nav.columns) == ["benchmark", "momentum_63", "momentum_126"]
    assert result["members"]["momentum_63"]["spec_hash"] != result["members"]["momentum_126"]["spec_hash"]
    for metric in ["initial_capital", "start", "end", "observations"]:
        assert len({m[metric] for m in result["metrics"].values()}) == 1
    signals = json.loads((path / "signals.json").read_text())
    assert len(signals["momentum_63"]) == len(signals["momentum_126"]) == 6


def test_blocked_middle_month_cannot_silently_hold_and_publish(market, config, tmp_path):
    store, frame, _, calendar = market
    changed = frame.copy()
    # Only availability is delayed; the eventual complete price matrix still exists.
    mask = (changed.symbol == "SPY") & (changed.session_date == "2024-08-30")
    changed.loc[mask, "available_at"] = pd.Timestamp("2024-09-03T20:30:00Z")
    store.save(changed, calendar)
    with pytest.raises(QuantError, match="受阻月份"):
        run_research(store, config, tmp_path / "research", members=members(config), benchmark="benchmark")
    assert not (tmp_path / "research/latest.json").exists()


def test_duplicate_spec_and_unknown_benchmark_fail_before_engine(market, config, tmp_path):
    specs = members(config)
    specs["copy"] = specs["momentum_63"]
    with pytest.raises(QuantError, match="重复"):
        run_research(market[0], config, tmp_path / "research", members=specs, benchmark="benchmark")
    with pytest.raises(QuantError, match="基准"):
        run_research(market[0], config, tmp_path / "research", members=members(config), benchmark="missing")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, -1])
def test_bad_budget_cannot_enter_spec(bad):
    with pytest.raises(QuantError):
        StrategySpec.create("momentum_rotation", ["SPY", "IEF"], invested_budget=bad)
