from native_tools import native_engine_root,native_dotnet
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from personal_quant.common import QuantError, canonical
from personal_quant.options.activation import activate
from personal_quant.options.exit_tasks import preview_freeze, freeze_exit, execute_exit, cancel_exit
from personal_quant.options.lifecycle import review
from personal_quant.options.monthly_report import monthly_compare
from personal_quant.options.simulation import execute
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle, verify_bundle, restore_bundle
from test_options_activation_v19 import setup, engine_evidence
from test_options_simulation_v19 import closing_quotes
from test_options_monthly_replay_v19 import ROOT
from test_options_management_v19 import setup_exit


def exit_quote(store, activation, clock, *, late=False):
    contracts, rows, metadata, _ = store.load(activation['quote_snapshot_id'])
    selected = {leg['contract']['contract_id'] for leg in activation['monthly_signal']['selection']['legs']}
    for row in rows:
        if row['contract_id'] in selected:
            row.update(exchange_timestamp=clock, underlying_timestamp=clock,
                       available_at=clock, received_at='2024-12-02T21:02:00Z' if late else clock)
    return store.save(list(contracts.values()), pd.DataFrame(rows), metadata)['snapshot_id']


@pytest.mark.parametrize('template,shares,loss', [
    ('cash_secured_put', 0, 14), ('protective_put', 100, 14), ('collar', 100, 28),
    ('long_call', 0, 14), ('long_put', 0, 14), ('covered_call', 100, 14),
    ('bull_call_debit_spread', 0, 28), ('bear_put_debit_spread', 0, 28)])
def test_frozen_engine_exit_preserves_account_stock_and_history(tmp_path, monkeypatch, engine_evidence, template, shares, loss):
    monkeypatch.chdir(tmp_path)
    runtime = tmp_path/'runtime/demo'; book = Ledger(runtime/'account.sqlite', 'demo'); book.account('sample')
    try:
        inputs = runtime/'options'
        store, plan, activation = setup(book, inputs, engine_evidence, cash=100000, packages=1, template=template, shares=shares)
        # The shared fixture helper uses inputs/chains. Place it at the runtime's
        # standard chains location so the complete recovery verifier sees it.
        activate(book, store, activation)
        signals = sorted((json.loads(p.read_text()) for p in (inputs/'monthly').glob('*.json')), key=lambda s:s['decision_at'])
        monthly_compare(native_engine_root(), native_dotnet(), inputs/'monthly-research/comparison', signals,
                        initial_cash=100000, fee_per_contract=2, stock_commission_bps=2)
        entry = {'plan_id':plan['plan_id'], 'report_id':'comparison', 'execution_snapshot_id':closing_quotes(store, activation),
                 'as_of':'2024-11-01T20:01:00Z', 'expected_sequence':activation['expected_sequence']}
        execute(book, store, entry)
        selected = plan['selection']['legs']
        # Independent cash: sell one Put receives 98; buy one Put pays 112;
        # collar net pays 14. Existing stock was purchased once at 100 with no fee.
        cash = {'cash_secured_put':100098, 'protective_put':89888, 'collar':89986,
                'long_call':99788, 'long_put':99788, 'covered_call':90098,
                'bull_call_debit_spread':99886, 'bear_put_debit_spread':99886}[template]
        positions = {'SPY':100} if shares else {}
        option_positions = {leg['contract']['contract_id']:leg['quantity_per_package'] for leg in selected}
        marks = {leg['contract']['contract_id']:
                 2.05 if template in {'long_call','long_put'} or
                 (template in {'bull_call_debit_spread','bear_put_debit_spread'} and leg['quantity_per_package'] > 0)
                 else 1.05 for leg in selected}
        marks.update({'SPY':100} if shares else {})
        equity = 100000-(14 if len(selected) == 2 else 7)
        book.reconcile('sample', {'account_id':'sample', 'currency':'USD', 'as_of':'2024-12-02T20:33:00Z',
                                 'cash_basis':'settled', 'cash':cash, 'positions':positions,
                                 'option_positions':option_positions, 'equity':equity}, marks)
        reference = exit_quote(store, activation, '2024-12-02T20:34:00Z')
        check = {'plan_id':plan['plan_id'], 'as_of':'2024-12-02T20:35:00Z', 'snapshot_id':reference,
                 'trigger':'RISK_REDUCTION', 'exit_days':7, 'fee_per_contract':2, 'max_age_seconds':900,
                 'max_underlying_skew_seconds':10, 'max_spread_fraction':.2, 'max_leg_skew_seconds':10,
                 'max_underlying_price_fraction':.01, 'reconciliation_max_days':1}
        request = {'request_id':'exit', 'review':check, 'execution_at':'2024-12-02T21:00:00Z',
                   'purpose':'OBLIGATION_CLOSE' if template in {'cash_secured_put','covered_call'} else 'PROTECTION_WITHDRAWAL',
                   'expected_sequence':book.sequence('sample')}
        preview = preview_freeze(book, store, request)
        assert preview['status'] == 'CHECKED', preview['checks']
        with pytest.raises(QuantError, match='已变化'):
            freeze_exit(book, store, request, expected_hash='outdated')
        frozen = freeze_exit(book, store, request, expected_hash=preview['preview_hash'])
        assert freeze_exit(book, store, request, expected_hash=preview['preview_hash']) == frozen
        pending = book.snapshot('sample', check['as_of'], marks)
        assert pending['pending_option_exits'] == [preview['exit_id']]
        assert pending['equity'] == str(equity) or float(pending['equity']) == equity
        assert pending['anomalies'] == []
        # Commitments block new risk, but are not accounting differences.
        book.check_reconciliation('sample', check['as_of'], 1)
        from personal_quant.execution.plans import size_orders
        from personal_quant.config import Config
        with pytest.raises(QuantError, match='退出意图'):
            size_orders(pending, {'SPY':.5}, {'SPY':100}, Config.load(ROOT/'configs/demo.toml'))
        assert book.snapshot('sample', '2024-12-02T20:34:59Z', marks)['pending_option_exits'] == []
        # Cancellation affects only the unexecuted intent, never actual holdings
        # or collateral; a new explicitly reviewed request can replace it.
        cancellation = {'exit_id':preview['exit_id'], 'as_of':'2024-12-02T20:36:00Z',
                        'expected_sequence':request['expected_sequence'], 'reason':'重新核对退出建议'}
        cancelled = cancel_exit(book, cancellation)
        assert cancel_exit(book, cancellation) == cancelled
        state = book.snapshot('sample', cancellation['as_of'], marks)
        assert state['pending_option_exits'] == [] and state['option_positions'] == pending['option_positions']
        assert state['option_cash_collateral'] == pending['option_cash_collateral']
        assert book.snapshot('sample', check['as_of'], marks)['pending_option_exits'] == [preview['exit_id']]
        request = {**request, 'request_id':'replacement', 'review':{**check, 'as_of':'2024-12-02T20:37:00Z'}}
        preview = preview_freeze(book, store, request)
        assert preview['status'] == 'CHECKED'
        freeze_exit(book, store, request, expected_hash=preview['preview_hash'])
        closing = exit_quote(store, activation, '2024-12-02T21:00:00Z')
        execute_request = {'exit_id':preview['exit_id'], 'report_id':'comparison', 'execution_snapshot_id':closing,
                           'as_of':'2024-12-02T21:01:00Z', 'expected_sequence':request['expected_sequence']}
        with pytest.raises(QuantError, match='尚未到达'):
            execute_exit(book, store, {**execute_request, 'as_of':'2024-12-02T20:59:00Z'})
        late = exit_quote(store, activation, '2024-12-02T21:00:00Z', late=True)
        with pytest.raises(QuantError, match='退出成交报价'):
            execute_exit(book, store, {**execute_request, 'execution_snapshot_id':late})
        assert book.sequence('sample') == request['expected_sequence']
        # A plan/manual resource mutation must invalidate frozen execution even
        # if no new account event has changed the ledger sequence.
        class Rollback(Exception): pass
        with pytest.raises(Rollback):
            with book.transaction():
                row = book.connection.execute('SELECT payload FROM option_plans WHERE plan_id=?', (plan['plan_id'],)).fetchone()
                changed = json.loads(row[0]); changed['resource_test'] = 'manual-state-changed'
                book.connection.execute('UPDATE option_plans SET payload=? WHERE plan_id=?', (canonical(changed), plan['plan_id']))
                with pytest.raises(QuantError, match='资源或人工状态变化'):
                    execute_exit(book, store, execute_request)
                assert book.sequence('sample') == request['expected_sequence']
                raise Rollback()
        result = execute_exit(book, store, execute_request)
        assert result['status'] == 'SIMULATED' and result['result']['status'] == 'FILLED'
        assert result['result']['lifecycle']['position_status'] == 'CLOSED'
        assert result['account']['option_positions'] == {} and result['account']['option_cash_collateral'] == '0'
        assert result['account']['positions'] == ({'SPY':'100'} if shares else {})
        assert float(result['account']['equity']) == 100000-loss
        assert result['account']['pending_option_exits'] == []
        assert execute_exit(book, store, execute_request) == result
        with pytest.raises(QuantError, match='不能换输入'):
            execute_exit(book, store, {**execute_request, 'as_of':'2024-12-02T21:02:00Z'})
        assert book.sequence('sample') == request['expected_sequence']+len(selected)
        # Later imports never make an earlier holding disappear; a ledger cutoff
        # also preserves the old pending intent at the same historical clock.
        historical = review(book, plan['plan_id'], '2024-12-02T20:59:00Z')
        assert historical['lifecycle']['position_status'] == 'OPEN'
        cutoff = book.snapshot('sample', execute_request['as_of'], marks, ledger_seq=request['expected_sequence'])
        assert cutoff['pending_option_exits'] == [preview['exit_id']]
        after = book.snapshot('sample', '2024-12-03T21:01:00Z', {'SPY':100} if shares else {})
        assert float(after['settled_cash']) == 100000-loss-shares*100
        assert after['payables'] == after['receivables'] == '0'
        assert review(book, plan['plan_id'], '2024-12-03T21:01:00Z')['lifecycle']['status'] == 'CLOSED'
        stock_events = [e for e in book.active_events('sample', execute_request['as_of']) if e['kind'] in {'BUY','SELL'}]
        assert len(stock_events) == bool(shares)
        with pytest.raises(QuantError, match='事实不能取消'):
            cancel_exit(book, {**cancellation, 'exit_id':preview['exit_id'], 'as_of':execute_request['as_of'],
                               'expected_sequence':book.sequence('sample')})
        if template == 'cash_secured_put':
            config = tmp_path/'demo.toml'; config.write_bytes((ROOT/'configs/demo.toml').read_bytes())
            create_bundle(runtime, config, tmp_path/'bundle')
            verify_bundle(tmp_path/'bundle', 'demo')
            restore_bundle(tmp_path/'bundle', tmp_path/'recovered', 'demo')
            recovered = Ledger(tmp_path/'recovered/runtime/demo/account.sqlite', 'demo')
            try:
                restored = recovered.snapshot('sample', '2024-12-03T21:01:00Z')
                assert restored['settled_cash'] == after['settled_cash']
                assert restored['pending_option_exits'] == []
                assert recovered.snapshot('sample', check['as_of'], marks)['pending_option_exits'] == [cancellation['exit_id']]
            finally: recovered.close()
    finally:
        book.close()


def test_freeze_requires_explicit_purpose_and_valid_timing(ledger, tmp_path):
    _, store, check = setup_exit(ledger, tmp_path)
    request = {'request_id':'request', 'review':check, 'execution_at':'2026-10-09T20:00:00Z',
               'purpose':'RISK_REDUCTION', 'expected_sequence':2}
    with pytest.raises(QuantError, match='明确用途'): preview_freeze(ledger, store, request)
    result = preview_freeze(ledger, store, {**request, 'purpose':'PROTECTION_WITHDRAWAL'})
    assert 'INVALID_EXIT_EXECUTION_WINDOW' in result['checks'] # Only 14 minutes to close.
    assert 'ACTIVATED_ENGINE_PLAN_REQUIRED' in result['checks']
    assert ledger.connection.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0


def test_freeze_does_not_claim_put_sale_is_obligation_close(ledger, tmp_path):
    _, store, check = setup_exit(ledger, tmp_path)
    request = {'request_id':'request', 'review':check, 'execution_at':'2026-10-12T20:00:00Z',
               'purpose':'OBLIGATION_CLOSE', 'expected_sequence':2}
    result = preview_freeze(ledger, store, request)
    assert 'PROTECTION_WITHDRAWAL_REQUIRED' in result['checks']
    assert 'INVALID_EXIT_EXECUTION_WINDOW' not in result['checks']


@pytest.mark.parametrize('bad_review', [None, [], {}, {'plan_id':None}])
def test_malformed_freeze_request_never_writes_tasks(ledger, tmp_path, bad_review):
    request = {'request_id':'invalid', 'review':bad_review, 'execution_at':'2024-12-02T21:00:00Z',
               'purpose':'OBLIGATION_CLOSE', 'expected_sequence':0}
    with pytest.raises(QuantError, match='退出冻结需'):
        freeze_exit(ledger, None, request, expected_hash='irrelevant')
    assert ledger.connection.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0


def test_earlier_demo_clock_does_not_bypass_existing_exit_commitment(ledger, tmp_path):
    _, store, check = setup_exit(ledger, tmp_path)
    ledger.record_task('option-exit-freeze:existing', 'SUCCESS', {'proposal':{
        'account_id':'sample', 'as_of':'2026-10-09T20:00:00Z', 'ledger_seq':2, 'exit_id':'existing'}})
    request = {'request_id':'earlier', 'review':check, 'execution_at':'2026-10-12T20:00:00Z',
               'purpose':'PROTECTION_WITHDRAWAL', 'expected_sequence':2}
    # An earlier historical read remains unchanged; committing another exit is
    # a current write and must respect the already frozen later commitment.
    state = ledger.snapshot('sample', check['as_of'])
    assert state['pending_option_exits'] == []
    assert 'PENDING_OPTION_EXIT' in preview_freeze(ledger, store, request)['checks']
