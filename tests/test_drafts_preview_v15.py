from pathlib import Path
from shutil import copytree
import json

import pytest

from personal_quant.common import QuantError, digest, write_json
from personal_quant.strategies.drafts import DraftStore, differences
from personal_quant.strategies.spec import StrategySpec, DataBundle
from personal_quant.research.preview import preview
from personal_quant.data.imports import price_csv_preview


def test_editable_drafts_are_distinct_from_versions_and_detect_stale_writes(tmp_path):
    store = DraftStore(tmp_path)
    spec = StrategySpec.create("momentum_rotation", ["SPY", "IEF"], strategy_id="a" * 80)
    first = store.save(spec)
    assert len(store.list()) == 1
    assert store.load(first["draft_id"])["spec"]["parameters"]["lookback"] == 126
    changed = spec.content(); changed["parameters"]["lookback"] = 63
    second_spec = StrategySpec.from_dict(changed)
    with pytest.raises(QuantError, match="草稿已存在"):
        store.save(second_spec)
    second = store.save(second_spec, expected_hash=first["hash"])
    assert second["hash"] != first["hash"]
    assert spec.content()["parameters"]["lookback"] == 126
    assert differences(spec.content(), second_spec.content()) == [{"字段": "parameters.lookback", "原值": "126", "新值": "63"}]


def test_preview_shows_history_and_first_execution_without_account_writes(market, config, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    copytree(market[0].root, Path(config.runtime_dir) / "data")
    spec = StrategySpec.create("momentum_rotation", config.symbols)
    bundle = DataBundle(market[2]["snapshot_id"], market[3].hash)
    result = preview(config, spec, bundle)
    assert result["status"] == "PASSED"
    assert result["required_prices"] == 127
    assert result["first_decision"] == "2024-07-31"
    assert result["first_execution"] == "2024-08-01"
    assert not (Path(config.runtime_dir) / "account.sqlite").exists()
    bad = StrategySpec.create("momentum_rotation", config.symbols, parameters={"lookback": 2520})
    assert preview(config, bad, bundle)["status"] == "BLOCKED"


def test_csv_preflight_has_stable_identity_and_rejects_synthetic_forward(market):
    _, frame, _, calendar = market
    content = frame.to_csv(index=False).encode()
    schedule = calendar.schedule.to_csv(index_label="session_date").encode()
    first, normalized, actual_calendar = price_csv_preview(content, calendar_content=schedule, calendar_kind="synthetic_test_sessions")
    second, _, _ = price_csv_preview(content, calendar_content=schedule, calendar_kind="synthetic_test_sessions")
    assert first["input_hash"] == second["input_hash"]
    assert first["price_basis"] == ["unadjusted"]
    assert actual_calendar.hash == calendar.hash
    with pytest.raises(QuantError, match="前向目录"):
        price_csv_preview(content, calendar_content=schedule, calendar_kind="synthetic_test_sessions", environment="paper")
