"""Engine acceptance tests: skipped explicitly until the real bt/ffn are installed."""
from dataclasses import replace
import json
import pandas as pd
import pytest

pytest.importorskip("bt", reason="主回测依赖未安装，此模块跳过不代表回测验收通过")
pytest.importorskip("ffn", reason="绩效依赖未安装")

from personal_quant.research.backtest import run_research


def frozen_research(market, config, tmp_path, *, fee=0, gap=False):
    store, frame, _, calendar = market
    frame = frame.copy()
    frame[["open", "high", "low", "close", "adj_close"]] = 100.0
    if gap:
        frame.loc[frame.session_date >= "2024-08-01", ["open", "high", "low", "close", "adj_close"]] = 200.0
    store.save(frame, calendar)
    config = replace(config, symbols=("SPY", "IEF"), weights=(0.5, 0.5),
                     evaluation_start="2024-07-31", evaluation_end="2024-08-06",
                     commission_bps=0, slippage_bps=0, fixed_fee=fee, research_capital=1000,
                     price_jump_threshold=1.1 if gap else config.price_jump_threshold)
    return store, config, tmp_path / "reports"


def test_next_day_jump_belongs_to_old_cash_not_new_positions(market, config, tmp_path):
    store, config, root = frozen_research(market, config, tmp_path, gap=True)
    result = run_research(store, config, root)
    nav = pd.read_csv(root / result["run_id"] / "nav.csv", index_col=0)
    assert nav.index[0] == "2024-07-31"
    assert nav.index[-1] == "2024-08-06"
    assert nav["fixed"].tolist() == pytest.approx([1000] * len(nav))
    trades = pd.read_csv(root / result["run_id"] / "trades.csv")
    assert set(pd.to_datetime(trades.iloc[:, 0]).dt.strftime("%Y-%m-%d")) == {"2024-08-01"}


def test_flat_prices_include_initial_fees_in_return_and_fair_comparison(market, config, tmp_path):
    store, config, root = frozen_research(market, config, tmp_path, fee=1)
    result = run_research(store, config, root)
    nav = pd.read_csv(root / result["run_id"] / "nav.csv", index_col=0)
    assert nav["fixed"].iloc[0] == pytest.approx(1000)
    assert nav["fixed"].iloc[-1] == pytest.approx(998)
    assert result["metrics"]["fixed"]["total_return"] == pytest.approx(-0.002)
    assert result["metrics"]["fixed"]["cost"] == pytest.approx(2)
    assert result["metrics"]["trend"]["total_return"] == pytest.approx(0)
    for key in ["initial_capital", "start", "end", "observations"]:
        assert result["metrics"]["fixed"][key] == result["metrics"]["trend"][key]
    again = run_research(store, config, root)
    second = pd.read_csv(root / again["run_id"] / "nav.csv", index_col=0)
    pd.testing.assert_frame_equal(nav, second)
    assert result["metrics"] == again["metrics"]


def test_first_observation_cost_is_not_discarded(market, config, tmp_path, monkeypatch):
    store, config, root = frozen_research(market, config, tmp_path, fee=1)
    config = replace(config, evaluation_start="2024-07-01", evaluation_end="2024-07-05")
    # Exercise the engine adapter with a supplied, already frozen June signal.
    # Default research history starts decisions inside the evaluation interval;
    # this controlled input checks the normalization contract independently.
    from personal_quant.strategies import signal
    monkeypatch.setattr("personal_quant.research.backtest.history",
        lambda frame, calendar, cfg, strategy, snapshot_id:
            [signal(frame, calendar, cfg, "2024-06-28", strategy, snapshot_id)])
    result = run_research(store, config, root)
    nav = pd.read_csv(root / result["run_id"] / "nav.csv", index_col=0)
    # June's frozen signal executes on the first evaluation day. Two fixed
    # one-dollar charges are losses, even though no pre-trade NAV row is displayed.
    assert nav["fixed"].tolist() == pytest.approx([998] * len(nav))
    metrics = result["metrics"]["fixed"]
    assert metrics["total_return"] == pytest.approx(-0.002)
    assert metrics["max_drawdown"] == pytest.approx(-0.002)
    assert metrics["cost"] == pytest.approx(2)


def test_rebalance_turnover_uses_current_pre_trade_equity(market, config, tmp_path):
    store, frame, _, calendar = market
    frame = frame.copy()
    frame[["open", "high", "low", "close", "adj_close"]] = 100.0
    frame.loc[(frame.symbol == "SPY") & (frame.session_date >= "2024-08-01"),
              ["open", "high", "low", "close", "adj_close"]] = 200.0
    store.save(frame, calendar)
    config = replace(config, symbols=("SPY", "IEF"), weights=(0.5, 0.5),
                     evaluation_start="2024-06-28", evaluation_end="2024-08-06",
                     development_start=None, development_end=None,
                     commission_bps=0, slippage_bps=0, fixed_fee=0, research_capital=1000,
                     price_jump_threshold=1.1)
    result = run_research(store, config, tmp_path / "research")
    # First build: 5 units each at $100; turnover 1000/(2*1000)=1/2.
    # Aug 1: old holdings are worth $1500; sell $250 SPY, buy $250 IEF.
    # Its turnover is 500/(2*1500)=1/6, not 500/(2*1000)=1/4.
    assert result["metrics"]["fixed"]["turnover"] == pytest.approx(2 / 3)
