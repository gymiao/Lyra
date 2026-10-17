import pandas as pd
import pytest

from personal_quant.common import QuantError
from personal_quant.data.factors import FactorStore
from personal_quant.strategies.spec import StrategySpec


def metadata(real=False):
    return {"source": "independent_factor_test", "source_reference": "independent synthetic test, not a live provider",
        "permission_note": "test fixture", "qualification": "reviewed_source" if real else "test",
        "availability_evidence": "offline contract fixture only", "definitions": {
            name: {"unit": "ratio", "version": "test.v1", "description": "independently supplied ratio"}
            for name in ("book_to_market", "roe_ttm")}}


def rows(real=False):
    return pd.DataFrame([{ "asset_id": symbol, "factor_name": name, "value": value,
        "unit": "ratio", "period_end": "2024-06-30", "published_at": "2024-07-20T12:00:00Z",
        "available_at": "2024-07-31T20:30:00Z", "value_as_of": "2024-07-31", "source": "independent_factor_test",
        "source_record_id": f"{symbol}-{name}-q2", "revision": 1, "currency": "USD",
        "data_type": "real_factors" if real else "synthetic", "definition_version": "test.v1"}
        for symbol, value in [("A", .2), ("B", .4)] for name in ("book_to_market", "roe_ttm")])


def spec():
    return StrategySpec.create("multi_factor", ["A", "B"], parameters={"mode": "fundamental"})


def test_publication_and_revision_do_not_rewrite_prior_evidence(tmp_path):
    store = FactorStore(tmp_path / "factors")
    first = store.save(rows(), metadata())
    with pytest.raises(QuantError, match="尚不可用"):
        store.select(first["snapshot_id"], spec(), "2024-07-31T20:29:00Z")
    earlier = store.select(first["snapshot_id"], spec(), "2024-07-31T20:30:00Z")
    revised = rows().iloc[[0]].copy()
    revised["revision"] = 2; revised["value"] = .8
    revised["published_at"] = revised["available_at"] = "2024-08-01T20:30:00Z"
    second = store.save(revised, metadata())
    before_revision = store.select(second["snapshot_id"], spec(), "2024-07-31T20:30:00Z")
    pd.testing.assert_frame_equal(earlier, before_revision)
    assert earlier.attrs["evidence"] == before_revision.attrs["evidence"]
    after_revision = store.select(second["snapshot_id"], spec(), "2024-08-02T20:30:00Z")
    assert after_revision.loc["A", "book_to_market"] == .8
    assert earlier.loc["A", "book_to_market"] == .2


def test_late_old_quarter_cannot_override_known_new_quarter(tmp_path):
    store = FactorStore(tmp_path / "factors")
    store.save(rows(), metadata())
    old = rows().iloc[[0]].copy()
    old["period_end"] = "2024-03-31"; old["source_record_id"] = "A-book-q1"
    old["published_at"] = old["available_at"] = "2024-08-01T20:30:00Z"
    old["value_as_of"] = "2024-08-01"; old["value"] = 99
    latest = store.save(old, metadata())
    assert store.select(latest["snapshot_id"], spec(), "2024-08-02T20:30:00Z").loc["A", "book_to_market"] == .2


def test_duplicate_import_keeps_first_receipt_and_identity(tmp_path, monkeypatch):
    store = FactorStore(tmp_path / "factors")
    monkeypatch.setattr("personal_quant.data.factors.now_utc", lambda: "2024-07-31T20:45:00Z")
    first = store.save(rows(), metadata())
    original, _ = store.load()
    monkeypatch.setattr("personal_quant.data.factors.now_utc", lambda: "2024-08-02T20:45:00Z")
    second = store.save(rows().iloc[::-1], metadata())
    assert second["snapshot_id"] == first["snapshot_id"]
    pd.testing.assert_frame_equal(original, store.load()[0])
    conflict = rows(); conflict.loc[0, "value"] = 5
    with pytest.raises(QuantError, match="冲突"):
        store.save(conflict, metadata())


def test_real_forward_requires_actual_receipt_time(tmp_path, monkeypatch):
    # Artificially labeled records test the contract, not a real provider connection.
    store = FactorStore(tmp_path / "factors")
    monkeypatch.setattr("personal_quant.data.factors.now_utc", lambda: "2024-07-31T20:45:00Z")
    snapshot = store.save(rows(real=True), metadata(real=True))
    with pytest.raises(QuantError, match="尚不可用"):
        store.select(snapshot["snapshot_id"], spec(), "2024-07-31T20:40:00Z", forward=True)
    assert len(store.select(snapshot["snapshot_id"], spec(), "2024-07-31T20:50:00Z", forward=True)) == 2


def test_test_factors_cannot_enter_forward_and_stale_factors_fail(tmp_path):
    store = FactorStore(tmp_path / "factors"); snapshot = store.save(rows(), metadata())
    with pytest.raises(QuantError, match="真实来源"):
        store.select(snapshot["snapshot_id"], spec(), "2024-07-31T20:50:00Z", forward=True)
    with pytest.raises(QuantError, match="年龄"):
        store.select(snapshot["snapshot_id"], spec(), "2024-08-20T20:50:00Z")


def test_user_cannot_supply_receipt_time_or_mix_definitions(tmp_path):
    frame = rows(); frame["recorded_at"] = "2000-01-01T00:00:00Z"
    with pytest.raises(QuantError, match="recorded_at"):
        FactorStore(tmp_path).save(frame, metadata())
    frame = rows(); frame.loc[0, "unit"] = "percent"
    with pytest.raises(QuantError, match="定义"):
        FactorStore(tmp_path).save(frame, metadata())


def test_snapshot_tampering_detected(tmp_path):
    store = FactorStore(tmp_path); snapshot = store.save(rows(), metadata())
    path = tmp_path / snapshot["snapshot_id"] / "factors.parquet"
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(QuantError, match="不匹配"):
        store.load()
