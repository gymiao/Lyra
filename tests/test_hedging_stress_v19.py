import copy
from datetime import date
import pytest
from personal_quant.common import QuantError,decimal as D
from personal_quant.hedging.stress import evaluate,analyze
from personal_quant.hedging.option_sizing import option_candidate
from personal_quant.hedging.spec import HedgeSpec
from personal_quant.options.pricing import price
from test_hedging_option_sizing_v19 import selected,account,share_spec,LIMITS,option_request
from test_hedging_archive_v19 import frozen_risk
from test_hedging_exposure_v19 import risk_market


def fixture_risk():
    r=account();r.update(account_id='sample',environment='demo',ledger_seq=2)
    return r


def scenarios(selection):
    expiry=selection['legs'][0]['contract']['expiry']
    def row(name,ret,day=expiry,iv=1,mult=1):
        return dict(name=name,horizon_date=day,benchmark_return=ret,beta_multiplier=mult,
            residual_returns={'SPY':0},volatility_multiplier=iv)
    return [row('flat',0,'2026-10-09'),row('down',-.2),row('up',.2),
            row('iv_up',0,'2026-10-09',2),row('time',0,'2026-11-09'),
            row('basis_break',-.2,mult=0)]


def request(selection):
    return dict(scenarios=scenarios(selection),models={leg['contract_version']:
        dict(volatility=.2,rate=0,dividend_yield=0) for leg in selection['legs']})


@pytest.mark.parametrize('method', ['protective_put','collar'])
def test_whole_account_anchor_cost_and_expiry_hand_values(selected,method):
    r=fixture_risk();sel=selected[method]
    candidate=option_candidate(r,share_spec(),method,sel,[],[],LIMITS)
    candidate['preview_hash']='frozen-candidate'
    report=evaluate(r,candidate,{},request(sel));points={p['name']:p for p in report['points']}
    # Flat same-day theory delta is zero: only the measured bid/ask and fees remain.
    friction=14 if method=='protective_put' else 28
    assert D(points['flat']['unhedged_equity'])==26000
    assert D(points['flat']['candidate_equity'])==26000-friction
    assert D(points['down']['unhedged_equity'])==21000
    leg=sel['legs'][0]['contract']
    initial=D(price(right='PUT',style=leg['style'],spot=100,strike=95,
        valuation_date='2026-10-09',expiry=leg['expiry'],volatility=.2,rate=0,
        dividend_yield=0,multiplier=1,contracts=1)['unit_price'])
    change=(D(15)-initial)*200
    if method=='collar':
        call=sel['legs'][1]['contract']
        call_initial=D(price(right='CALL',style=call['style'],spot=100,strike=105,
            valuation_date='2026-10-09',expiry=call['expiry'],volatility=.2,rate=0,
            dividend_yield=0,multiplier=1,contracts=1)['unit_price'])
        change+=call_initial*200
    assert abs(D(points['down']['candidate_equity'])-(D(21000)-friction+change))<D('.0000001')
    assert report['maximum_loss']=='NOT_INFERRED_FROM_FINITE_GRID' and not report['executable']
    assert D(points['iv_up']['candidate_option_change'])>0 if method=='protective_put' else True
    assert D(points['basis_break']['unhedged_stock_change'])==0
    assert D(points['time']['candidate_option_change'])<0 if method=='protective_put' else True


def test_existing_put_is_in_both_baselines_not_counted_as_new(selected):
    r=fixture_risk();c=selected['protective_put']['legs'][0]['contract']
    r['account']['option_positions']={c['contract_id']:'1'}
    candidate=dict(status='KEEP',trades=[],preview_hash='keep')
    req=request(selected['protective_put'])
    out=evaluate(r,candidate,{c['contract_id']:c},req)
    for row in out['points']:
        assert row['unhedged_equity']==row['candidate_equity']
    assert D(out['points'][1]['unhedged_option_change'])>0


def test_cash_deposit_changes_equity_not_scenario_investment_pnl(selected):
    r=fixture_risk();candidate=dict(status='KEEP',trades=[],preview_hash='keep')
    req=dict(scenarios=scenarios(selected['protective_put']),models={})
    before=evaluate(r,candidate,{},req)
    funded=copy.deepcopy(r);funded['account']['equity']='36000'
    after=evaluate(funded,candidate,{},req)
    assert [p['unhedged_pnl'] for p in before['points']]==[p['unhedged_pnl'] for p in after['points']]

def test_stock_reduction_keeps_sale_proceeds_and_deducts_cost_once(selected):
    r=fixture_risk()
    candidate=dict(status='SELECTED_FOR_RESEARCH',preview_hash='stock-sale',E_post='25990',
        trades=[dict(symbol='SPY',quantity='-100')])
    req=dict(scenarios=scenarios(selected['protective_put']),models={})
    result=evaluate(r,candidate,{},req);flat,down=result['points'][:2]
    assert D(flat['candidate_equity'])==25990
    assert D(down['unhedged_equity'])==21000 and D(down['candidate_equity'])==22990
    assert D(down['protection_difference'])==1990

def test_existing_collar_signed_call_and_put_in_both_views(selected):
    r=fixture_risk();sel=selected['collar'];terms={l['contract']['contract_id']:l['contract'] for l in sel['legs']}
    r['account']['option_positions']={l['contract']['contract_id']:str(l['quantity_per_package']) for l in sel['legs']}
    result=evaluate(r,dict(status='KEEP',trades=[],preview_hash='keep'),terms,request(sel))
    for point in result['points']:
        assert point['unhedged_equity']==point['candidate_equity']
    assert D(result['points'][2]['candidate_option_change'])<0


@pytest.mark.parametrize('mutation,code',[
    ('missing_model','MODEL_INPUT_REQUIRED'),('missing_residual','INVALID_HEDGE_STRESS'),
    ('cross_expiry','UNOBSERVED_EXPIRY_PATH'),('nonpositive','INVALID_HEDGE_STRESS'),
    ('blocked','HEDGE_CANDIDATE_REQUIRED')])
def test_missing_or_unobserved_inputs_are_rejected(selected,mutation,code):
    r=fixture_risk();sel=selected['protective_put']
    cand=option_candidate(r,share_spec(),'protective_put',sel,[],[],LIMITS);cand['preview_hash']='test'
    req=request(sel)
    if mutation=='missing_model':req['models']={}
    elif mutation=='missing_residual':req['scenarios'][0]['residual_returns']={}
    elif mutation=='cross_expiry':req['scenarios'][0]['horizon_date']='2027-01-01'
    elif mutation=='nonpositive':req['scenarios'][0]['benchmark_return']=-1
    else:cand['status']='NO_FEASIBLE_HEDGE'
    with pytest.raises(QuantError) as exc:evaluate(r,cand,{},req)
    assert exc.value.code==code


def test_service_uses_archived_account_and_does_not_write(frozen_risk):
    book,*_=frozen_risk;req=option_request(frozen_risk)
    from personal_quant.hedging.preview import preview
    p=preview(book,'sample',req);sel=p['selection']
    r=dict(preview_request=req,scenarios=[dict(name='decline',horizon_date=sel['legs'][0]['contract']['expiry'],
        benchmark_return=-.2,beta_multiplier=1,residual_returns={'SPY':0},volatility_multiplier=1)],
        models={l['contract_version']:dict(volatility=.2,rate=0,dividend_yield=0) for l in sel['legs']})
    seq=book.sequence('sample');count=book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]
    first=analyze(book,'sample',r);second=analyze(book,'sample',r)
    assert first==second and first['points'][0]['candidate_equity']
    assert book.sequence('sample')==seq and book.connection.execute('SELECT count(*) FROM tasks').fetchone()[0]==count

