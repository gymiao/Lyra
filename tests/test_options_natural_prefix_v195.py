from native_tools import native_engine_root,native_dotnet
import pytest
from test_options_monthly_replay_v19 import monthly_signals,ROOT
from test_options_monthly_natural_v19 import natural_path
from personal_quant.options.monthly_replay import monthly_replay


@pytest.mark.parametrize('cutoff,expected,options',[('2025-01-16',99958,2),('2025-01-17',99748,0)])
def test_natural_prefix_uses_next_local_midnight_and_no_future_prices(tmp_path,cutoff,expected,options):
    signals=monthly_signals(tmp_path,'long_straddle');path=natural_path(signals,100)
    clipped={**path,'stocks':{s:{d:p for d,p in rows.items() if d<=cutoff} for s,rows in path['stocks'].items()},
             'options':{s:{d:p for d,p in rows.items() if d<=cutoff} for s,rows in path['options'].items()}}
    proof=monthly_replay(native_engine_root(),native_dotnet(),tmp_path/'native',signals,
        initial_cash=100000,fee_per_contract=2,execution_path=clipped,
        final_lifecycle='natural_expiry_with_delivery_exit',through=cutoff)
    assert float(proof['ledger_bridge']['equity'])==expected
    assert len(proof['ledger_bridge']['option_positions'])==options
    assert proof['ledger_bridge']['as_of'].endswith('05:00:00+00:00')
