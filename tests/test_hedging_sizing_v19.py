import copy
import json
from pathlib import Path
import subprocess
import sys
import pytest
from personal_quant.common import QuantError,decimal as D
from personal_quant.hedging.spec import HedgeSpec
from personal_quant.hedging.sizing import stock_candidate


def policy(**changes):
    return {'schema_version':1,'name':'test-only','version':'1.0.0','mode':'beta_target','scope':['BASE','PROXY'],
        'benchmark':'INDEX','tools':['reduce_stock','inverse_etf','protective_put','collar','proxy_put'],
        'target_beta':.5,'protection_fraction':None,'funding':'cash_only','funding_symbol':None,
        'max_cash':100000,'max_premium':10000,'max_notional':1000000,'max_contracts':10,'max_trade_units':1000,
        'residual_beta_tolerance':.000001,'max_overhedge_fraction':.05,'commission_bps':0,'fixed_trade_fee':0,
        'option_fee_per_contract':2,'min_abs_proxy_beta':.01,'exit_days_before_expiry':7,
        'min_days_to_expiry':30,'max_days_to_expiry':60,**changes}


def quote(symbol='PROXY',price=100,beta=-1,kind='inverse_etf'):
    return {'symbol':symbol,'execution_price':price,'market_price':price,'beta':beta,'trade_unit':1,
        'product_type':kind,'product_evidence':'explicit synthetic product test; not provider verification'}


def risk(B=100000,E=100000,cash=0,positions=None):
    positions={'BASE':'1000'} if positions is None else positions
    return {'exposure_id':'frozen-test-risk','account':{'equity':str(E),'available_cash':str(cash),
        'positions':positions,'prices':{'BASE':100,'PROXY':100},'reserved_positions':{}},
        'risk':{'beta_amount':str(B)},'valuation':{'prices':{'BASE':100,'PROXY':100}},
        'beta_model':{'benchmark':'INDEX','estimates':{'BASE':{'status':'CHECKED','beta':1},'PROXY':{'status':'CHECKED','beta':-1}}}}


def test_funded_inverse_recomputes_sold_base_and_reaches_hand_target():
    spec=HedgeSpec.from_dict(policy(funding='sell_scope',funding_symbol='BASE'))
    result=stock_candidate(risk(),spec,'inverse_etf',quote(),funding_quote=quote('BASE',100,1,'stock'))
    assert result['status']=='SELECTED_FOR_RESEARCH' and result['incremental_quantity']=='250'
    assert [t['quantity'] for t in result['trades']]==['-250','250']
    assert result['B_post']=='50000' and result['E_post']=='100000' and result['beta_post']=='0.5'
    assert result['requires_sell_settlement'] and result['dependencies'][1]=='SELL_SETTLEMENT_CONFIRMED'
    assert not result['executable']


def test_cash_cannot_be_inferred_from_future_sell_and_fee_equity_is_once():
    denied=stock_candidate(risk(),HedgeSpec.from_dict(policy()),'inverse_etf',quote())
    assert denied['status']=='NO_FEASIBLE_HEDGE' and 'INSUFFICIENT_AVAILABLE_CASH' in denied['checks']
    result=stock_candidate(risk(),HedgeSpec.from_dict(policy(funding='sell_scope',funding_symbol='BASE',
        commission_bps=10,residual_beta_tolerance=.001)), 'inverse_etf',quote(),funding_quote=quote('BASE',100,1,'stock'))
    assert result['incremental_quantity']=='250' and result['trades'][0]['quantity']=='-251'
    assert result['fees']=='50.1' and result['E_post']=='99949.9' and result['B_post']=='49900'
    assert float(result['beta_post'])==pytest.approx(49900/99949.9)


def test_incremental_sale_distinguishes_existing_position_from_short():
    r=risk(B=70000,E=100000,positions={'PROXY':'100'});r['account']['prices']['PROXY']=500
    r['valuation']['prices']['PROXY']=500;r['beta_model']['estimates']['PROXY']['beta']=1
    result=stock_candidate(r,HedgeSpec.from_dict(policy(target_beta=.3)),'reduce_stock',quote(price=500,beta=1,kind='etf'))
    assert result['incremental_quantity']=='-80' and result['target_position']=='20'
    absent=copy.deepcopy(r);absent['account']['positions']={};absent['risk']['beta_amount']='120000'
    denied=stock_candidate(absent,HedgeSpec.from_dict(policy(target_beta=.3)),'reduce_stock',quote(price=500,beta=1,kind='etf'))
    assert D(denied['ideal_incremental_quantity'])==-180 and 'UNSUPPORTED_SHORT' in denied['checks']


def test_reservations_limits_and_no_unverified_beta_override():
    r=risk();r['account']['reserved_positions']={'BASE':'900'}
    result=stock_candidate(r,HedgeSpec.from_dict(policy(funding='sell_scope',funding_symbol='BASE')),
        'inverse_etf',quote(),funding_quote=quote('BASE',100,1,'stock'))
    assert result['status']=='NO_FEASIBLE_HEDGE' and 'INSUFFICIENT_FUNDING_SHARES' in result['checks']
    bad=stock_candidate(risk(),HedgeSpec.from_dict(policy()),'inverse_etf',quote(beta=-2))
    assert bad['checks']==['FROZEN_PROXY_BASIS_MISMATCH']
    r=risk(cash=100000);result=stock_candidate(r,HedgeSpec.from_dict(policy(max_notional=100)),'inverse_etf',quote())
    assert result['status']=='NO_FEASIBLE_HEDGE' and 'NOTIONAL_LIMIT' in result['checks']


def test_keep_and_spec_is_immutable_to_caller_lists():
    raw=policy();spec=HedgeSpec.from_dict(raw);identity=spec.spec_hash;raw['tools'].clear();raw['scope'].append('EXTRA')
    result=stock_candidate(risk(B=50000),spec,'inverse_etf',quote())
    assert result['status']=='KEEP' and result['trades']==[] and spec.spec_hash==identity
    returned=spec.content();returned['scope'].clear();assert spec.content()['scope']==['BASE','PROXY']


def test_funding_preserves_cash_outside_explicit_budget():
    r=risk(E=110000,cash=10000)
    result=stock_candidate(r,HedgeSpec.from_dict(policy(funding='sell_scope',funding_symbol='BASE',max_cash=0)),
        'inverse_etf',quote(),funding_quote=quote('BASE',100,1,'stock'))
    assert result['incremental_quantity']=='225' and result['trades'][0]['quantity']=='-225'
    assert result['available_cash_after_all_settlements']=='10000' and result['B_post']=='55000'
    assert result['E_post']=='110000' and result['beta_post']=='0.5'


@pytest.mark.parametrize('changes',[{'extra':0},{'target_beta':None},{'protection_fraction':.5},
    {'funding':'sell_scope','funding_symbol':'OTHER'},{'max_cash':float('nan')},{'max_trade_units':10001},
    {'tools':[{}]},{'mode':{}},{'min_days_to_expiry':3}])
def test_invalid_or_implicit_policy_rejected(changes):
    with pytest.raises(QuantError):HedgeSpec.from_dict(policy(**changes))


from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market


def test_preview_archive_cli_and_repeat_do_not_change_account(frozen_risk,tmp_path):
    from personal_quant.hedging.archive import publish
    from personal_quant.hedging.preview import preview
    book,config,store,request,_=frozen_risk
    frozen=publish(book,config,store,'sample',request)
    item={'exposure_id':frozen['exposure_id'],'spec':policy(scope=['SPY'],benchmark='GLD',target_beta=.1,tools=['reduce_stock']),
        'method':'reduce_stock','proxy':quote('SPY',100,.5,'etf'),'funding_quote':None}
    result=preview(book,'sample',item)
    assert result['status']=='SELECTED_FOR_RESEARCH' and result['incremental_quantity']=='-40' and result['target_position']=='60'
    assert preview(book,'sample',item)['preview_hash']==result['preview_hash'] and not result['executable']
    file=tmp_path/'preview.json';file.write_text(json.dumps(item))
    config_file=tmp_path/'demo.toml';config_file.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
    command=[sys.executable,'-m','personal_quant.cli','--config',str(config_file),'hedge-preview','--account-id','sample','--file',str(file)]
    before=(book.sequence('sample'),book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0])
    for _ in range(2):
        process=subprocess.run(command,capture_output=True,text=True)
        assert process.returncode==0,process.stderr
        assert json.loads(process.stdout)['preview_hash']==result['preview_hash']
    assert before==(book.sequence('sample'),book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0])
