import copy
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import pandas as pd
import pytest
from personal_quant.common import QuantError
from personal_quant.hedging.exposure import estimate_betas,normalize_delta,aggregate_exposure
from personal_quant.hedging.service import exposure
from personal_quant.data.store import DataStore
from personal_quant.portfolio import Ledger
from test_options_data_v19 import sample
from conftest import event


@pytest.fixture
def risk_market(market):
    store,frame,metadata,calendar=market
    dates=calendar.sessions;r=.002*np.sin(np.arange(len(dates)-1))+0.0001
    for symbol,beta,end in [('SPY',.5,100),('IEF',1.5,200),('GLD',1,150)]:
        p=np.r_[1,np.cumprod(1+beta*r)];p=p*end/p[-1]
        rows=frame.symbol==symbol
        for field in ['open','high','low','close','adj_close']:frame.loc[rows,field]=p
    return store,frame,metadata,calendar


def estimate(frame,cal,clock,window=126):
    return estimate_betas(frame,cal,['SPY','IEF'],'GLD',clock,clock,window=window,min_r2=.9,max_standard_error=.1)


def test_common_126_returns_exact_ols_and_future_invariance(risk_market):
    _,frame,_,cal=risk_market;day=cal.sessions[180];clock=(cal.close(day)+pd.Timedelta(minutes=30)).isoformat()
    result=estimate(frame,cal,clock)
    assert result['status']=='COMPLETE' and result['observations']==126
    assert result['estimates']['SPY']['beta']==pytest.approx(.5,abs=1e-10)
    assert result['estimates']['IEF']['beta']==pytest.approx(1.5,abs=1e-10)
    changed=frame.copy();changed.loc[changed.session_date>day,'adj_close']*=10
    assert estimate(changed,cal,clock)==result


def test_missing_dates_never_become_bridged_daily_returns(risk_market):
    _,frame,_,cal=risk_market;clock=(cal.close(cal.sessions[-1])+pd.Timedelta(minutes=30)).isoformat()
    missing=frame.loc[~((frame.symbol=='SPY')&(frame.session_date==cal.sessions[-10]))]
    result=estimate(missing,cal,clock);assert result['checks']==['INCOMPLETE_COMMON_PRICES']
    late=frame.copy();late.loc[(late.symbol=='IEF')&(late.session_date==cal.sessions[-3]),'available_at']=pd.Timestamp(clock)+pd.Timedelta(days=1)
    assert estimate(late,cal,clock)['status']=='INCOMPLETE'


def test_127_prices_required_zero_variance_and_quality(risk_market):
    _,frame,_,cal=risk_market
    clock=(cal.close(cal.sessions[125])+pd.Timedelta(minutes=30)).isoformat()
    assert estimate(frame,cal,clock)['checks']==['INSUFFICIENT_COMMON_PRICES']
    clock=(cal.close(cal.sessions[-1])+pd.Timedelta(minutes=30)).isoformat()
    fixed=frame.copy();fixed.loc[fixed.symbol=='GLD','adj_close']=100
    assert estimate(fixed,cal,clock)['checks']==['ZERO_BENCHMARK_VARIANCE']
    zero=frame.copy();zero.loc[zero.session_date==cal.sessions[-1],'volume']=0
    assert estimate(zero,cal,clock)['checks']==['NONTRADABLE_RISK_PRICE']


def test_dollar_weighted_beta_not_share_average_and_deposits(risk_market):
    _,frame,_,cal=risk_market;clock=(cal.close(cal.sessions[-1])+pd.Timedelta(minutes=30)).isoformat()
    betas=estimate(frame,cal,clock)['estimates']
    state={'positions':{'SPY':'100','IEF':'100'},'prices':{'SPY':100,'IEF':200},'equity':'30000'}
    result=aggregate_exposure(state,betas,{},{});
    assert float(result['beta_amount'])==pytest.approx(35000)
    assert float(result['account_beta'])==pytest.approx(7/6)
    more=aggregate_exposure({**state,'equity':'40000'},betas,{},{});
    assert more['beta_amount']==result['beta_amount'] and float(more['account_beta'])==pytest.approx(.875)
    missing=aggregate_exposure({**state,'prices':{'SPY':100}},betas,{},{});
    assert missing['beta_amount'] is None and missing['stock_valuation_count_coverage']=={
        'marked':1,'total':2,'meaning':'按持仓证券数统计；缺价时无法声称完整市值覆盖率'}


@pytest.mark.parametrize('unit,value',[('per_share',-.5),('per_contract',-50),('position_total',-100)])
def test_delta_units_normalized_once(unit,value):
    from personal_quant.options.contracts import OptionContract
    c=OptionContract.from_dict({**sample()[0].content(),'right':'PUT'})
    item={'contract_version':c.version_hash,'unit':unit,'value':value,'signed_contracts':2,'source':'explicit_test',
        'data_type':'synthetic','as_of':'2026-10-09T19:45:00Z','available_at':'2026-10-09T19:45:02Z',
        'received_at':'2026-10-09T19:45:04Z','model_inputs':{}}
    result=normalize_delta(item,c,2,'2026-10-09T19:46:00Z','2026-10-09T19:46:00Z',120)
    assert result['delta_shares']=='-100.0' if unit=='per_share' else result['delta_shares']=='-100'
    with pytest.raises(QuantError):normalize_delta({**item,'signed_contracts':1},c,2,'2026-10-09T19:46:00Z','2026-10-09T19:46:00Z',120)
    with pytest.raises(QuantError):normalize_delta({**item,'received_at':'2026-10-09T20:00:00Z'},c,2,'2026-10-09T19:46:00Z','2026-10-09T19:46:00Z',120)


def test_late_processing_cannot_admit_a_greek_observed_after_execution():
    from personal_quant.options.contracts import OptionContract
    c=OptionContract.from_dict({**sample()[0].content(),'right':'PUT'})
    item=dict(contract_version=c.version_hash,unit='per_share',value=-.5,signed_contracts=2,
        source='explicit_test',data_type='synthetic',as_of='2026-10-09T19:47:00Z',
        available_at='2026-10-09T19:47:01Z',received_at='2026-10-09T19:47:02Z',model_inputs={})
    with pytest.raises(QuantError) as exc:
        normalize_delta(item,c,2,'2026-10-09T19:46:00Z','2026-10-12T20:00:00Z',120)
    assert exc.value.code=='HEDGE_GREEK_TIME_MISMATCH'


def test_account_exposure_cli_readonly_and_late_facts(risk_market,config,tmp_path,monkeypatch):
    store,frame,_,cal=risk_market;monkeypatch.chdir(tmp_path)
    raw=DataStore(tmp_path/'runtime/demo/data');metadata=raw.save(frame,cal)
    book=Ledger(tmp_path/'runtime/demo/account.sqlite','demo');book.account('sample')
    book.import_events('sample',[event('capital','DEPOSIT',amount=30000),event('s1','BUY',symbol='SPY',quantity=100,price=100,
        settlement_at='2024-07-02T20:00:00Z'),event('s2','BUY',symbol='IEF',quantity=100,price=200,settlement_at='2024-07-02T20:00:00Z')])
    clock=(cal.close(cal.sessions[-1])+pd.Timedelta(minutes=30)).isoformat()
    request={'schema_version':1,'as_of':clock,'knowledge_cutoff':clock,'ledger_seq':3,'ledger_view':'restated',
        'valuation_snapshot_id':metadata['snapshot_id'],'return_snapshot_id':metadata['snapshot_id'],
        'benchmark':'GLD','window':126,'min_r2':.9,'max_standard_error':.1,'max_mark_skew_seconds':120,
        'max_greek_age_seconds':3600,'greeks':[],'option_valuation':None}
    try:
        result=exposure(book,config,raw,'sample',request)
        assert result['status']=='COMPLETE' and float(result['risk']['account_beta'])==pytest.approx(7/6)
        assert not result['executable']
        assert exposure(book,config,raw,'sample',request)['exposure_id']==result['exposure_id']
        with pytest.raises(QuantError,match='尚未收到'):
            exposure(book,config,raw,'sample',{**request,'ledger_view':'known_then'})
        with pytest.raises(QuantError,match='未来风险'):
            exposure(book,config,raw,'sample',{**request,'as_of':'2099-01-01T00:00:00Z','knowledge_cutoff':'2099-01-01T00:00:00Z'})
        before=book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]
        file=tmp_path/'risk.json';file.write_text(json.dumps(request))
        cfg=tmp_path/'demo.toml';cfg.write_bytes((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_bytes())
        command=[sys.executable,'-m','personal_quant.cli','--config',str(cfg),'hedge-exposure','--account-id','sample','--file',str(file)]
        process=subprocess.run(command,capture_output=True,text=True)
        assert process.returncode==0,process.stderr
        assert json.loads(process.stdout)['exposure_id']==result['exposure_id']
        file.write_text(json.dumps({**request,'ledger_view':'known_then'}))
        failed=subprocess.run(command,capture_output=True,text=True)
        assert failed.returncode==2 and json.loads(failed.stderr)['code']=='LEDGER_NOT_KNOWN'
        file.write_text(json.dumps(request))
        assert book.sequence('sample')==3 and book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]==before
    finally:book.close()


def test_net_zero_market_value_is_not_beta_neutral():
    state={'positions':{'LONG':'100','SHORT':'-100'},'prices':{'LONG':100,'SHORT':100},'equity':'5000'}
    betas={'LONG':{'beta':1.5,'status':'CHECKED'},'SHORT':{'beta':.8,'status':'CHECKED'}}
    result=aggregate_exposure(state,betas,{},{});
    assert result['stock_net_market_value']=='0' and result['stock_gross_market_value']=='20000'
    assert float(result['beta_amount'])==7000 and float(result['account_beta'])==1.4


def test_two_put_position_total_delta_not_multiplied_again():
    state={'positions':{'SPY':'100'},'prices':{'SPY':100},'equity':'10000','option_positions':{'PUT':'2'}}
    result=aggregate_exposure(state,{'SPY':{'beta':1,'status':'CHECKED'}},
        {'PUT':{'underlying':'SPY','delta_shares':'-100'}},{'SPY':100})
    assert float(result['beta_amount'])==0 and result['option_positions'][0]['beta_amount']=='-10000'


def test_missing_option_delta_withholds_full_account_beta():
    state={'positions':{'SPY':'100'},'prices':{'SPY':100},'equity':'10000','option_positions':{'PUT':'1'}}
    result=aggregate_exposure(state,{'SPY':{'beta':1,'status':'CHECKED'}},{},{'SPY':100})
    assert result['known_beta_amount']=='10000' and result['beta_amount'] is None and result['account_beta'] is None
    assert result['checks']==['OPTION_DELTA_REQUIRED:PUT']
