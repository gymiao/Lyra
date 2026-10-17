"""Read-only preflight of an entire decision grid, without running bt."""
from pathlib import Path

from ..common import QuantError
from ..data.factors import FactorStore
from ..data.store import DataStore
from ..strategies.adapter import history_v2


def preview(config, spec, bundle):
    frame, metadata, calendar = DataStore(Path(config.runtime_dir) / "data").load(bundle.signal_snapshot_id)
    selector = None
    if bundle.factor_snapshot_id:
        factors = FactorStore(Path(config.runtime_dir) / "factors")
        selector = lambda strategy, instant: factors.select(bundle.factor_snapshot_id, strategy, instant)
    signals = history_v2(frame, calendar, config, spec, bundle, factor_selector=selector)
    ready = [item for item in signals if item.status == "READY"]
    result = {"status": "PASSED" if signals and len(ready) == len(signals) else "BLOCKED",
        "required_prices": spec.required_prices, "snapshot_id": metadata["snapshot_id"],
        "data_type": metadata["data_type"], "data_as_of": metadata["end"], "source": metadata["source"],
        "execution_data": "RESEARCH_ONLY_EXECUTION_DATA_REQUIRED" if set(metadata["price_basis"]) != {"unadjusted"} else "DECLARED_UNADJUSTED_RECHECK_BEFORE_PLAN",
        "first_decision": ready[0].decision_session if ready else None,
        "first_execution": ready[0].eligible_session if ready else None,
        "months": [{"decision_session": item.decision_session, "eligible_session": item.eligible_session,
                    "status": item.status, "reasons": item.reasons} for item in signals]}
    return result
