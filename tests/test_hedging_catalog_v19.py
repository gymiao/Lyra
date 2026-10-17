import json
from pathlib import Path

from personal_quant.cli import main
from personal_quant.hedging.catalog import catalog


def test_catalog_does_not_grant_permission_or_claim_conditional_execution():
    result=catalog();rows={r['method_id']:r for r in result['methods']}
    assert len(rows)==16 and not result['executable']
    core={k for k,r in rows.items() if r['hedge_spec_tool']}
    assert core=={'reduce_stock','inverse_etf','protective_put','collar','proxy_put'}
    assert all(not r['executable'] for r in rows.values())
    assert rows['covered_call']['support']=='OPTION_TEMPLATE_ONLY'
    assert not rows['covered_call']['hedge_spec_tool']
    assert '完整下跌保护' in rows['covered_call']['risks']
    for key in ['short_etf','index_futures','pairs_trading','factor_neutral','dynamic_delta','put_spread']:
        assert rows[key]['support']=='CONDITIONAL_NOT_IMPLEMENTED'
        assert rows[key]['paper']==rows[key]['real']=='UNSUPPORTED'
    assert '每日重置' in rows['inverse_etf']['risks']
    assert '基差' in rows['proxy_put']['risks']
    assert all(r['required_inputs'] and r['risks'] for r in rows.values())


def test_catalog_cli_works_without_account_prices_or_runtime(tmp_path,monkeypatch,capsys):
    config=Path(__file__).resolve().parents[1]/'configs/demo.toml'
    monkeypatch.chdir(tmp_path)
    assert main(['--config',str(config),'hedge-catalog'])==0
    result=json.loads(capsys.readouterr().out)
    assert result==catalog()
    assert not (tmp_path/'runtime').exists()
