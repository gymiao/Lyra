"""Frozen-clock engineering fixtures; no natural forward cycle or vendor access."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from personal_quant.common import QuantError,digest
from personal_quant.data.calendar import Calendar
from personal_quant.options.contracts import OptionContract
from personal_quant.options.data import OptionDataStore
from personal_quant.options.forward import freeze_forward,validate_forward,verify_snapshot
from personal_quant.options.activation import activate
from personal_quant.options.plans import draft
from personal_quant.options.lifecycle import review
from personal_quant.options.permissions import register as register_permissions,series_id as permission_series
from personal_quant.options.source import register_source,series_id
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.backup import create_bundle,verify_bundle,restore_bundle
from personal_quant.portfolio.schema import apply_workbench_schema,apply_v18_schema,apply_v19_schema
from test_options_monthly_replay_v19 import monthly_signals
from test_options_activation_v19 import engine_evidence
from test_options_plans_v19 import RISK
from conftest import event


def setup(tmp_path,monkeypatch):
    historical=monthly_signals(tmp_path/'historical',template='long_put')[0]
    original=OptionDataStore(tmp_path/'historical/chains')
    contracts,quotes,_,_=original.load(historical['input']['snapshot_id'])
    book=Ledger(tmp_path/'runtime/paper/account.sqlite','paper');book.account('sample')
    with book.transaction():
        apply_workbench_schema(book.connection);apply_v18_schema(book.connection);apply_v19_schema(book.connection)
    archive=book.path.parent/'options/monthly-forward'
    quote_store=OptionDataStore(book.path.parent/'options/chains');versions={};qualified=[]
    proof_root=book.path.parent/'options/contract-evidence';proof_root.mkdir(parents=True)
    for old in contracts.values():
        evidence=('ISOLATED TEST CONTRACT '+old.contract_id).encode()
        evidence_hash=hashlib.sha256(evidence).hexdigest();(proof_root/evidence_hash).write_bytes(evidence)
        contract=OptionContract.from_dict({**old.content(),'evidence_hash':evidence_hash})
        versions[old.contract_id]=contract.version_hash;qualified.append(contract)
    quotes=[row for row in quotes if row['received_at'].startswith('2024-10-31')]
    for row in quotes:
        row['contract_version']=versions[row['contract_id']];row['source']='fixture-provider'
    metadata=dict(schema_version=1,source='fixture-provider',data_type='real_market',license_terms='ISOLATED TEST ONLY',
        unit_evidence='fabricated contract files for engineering test',available_time_basis='frozen test timestamps')
    monkeypatch.setattr('personal_quant.options.data.now_utc',lambda:'2024-10-31T20:29:00Z')
    snapshot=quote_store.save(qualified,pd.DataFrame(quotes),metadata)['snapshot_id']
    request=historical['input']['request'];calendar=Calendar.market('2024-10-01','2024-12-15')
    monkeypatch.setattr('personal_quant.options.forward.now_utc',lambda:'2024-10-31T20:31:00Z')
    return book,quote_store,snapshot,request,calendar,archive,qualified,metadata


def qualify(book,tmp_path,contracts,metadata,monkeypatch):
    evidence=tmp_path/'vendor-evidence';evidence.mkdir()
    (evidence/'provider.txt').write_text('ISOLATED TEST: fabricated source policy, no vendor access')
    body=dict(schema_version=2,asset_type='OPTION_QUOTES',series_id=series_id(metadata['source']),source=metadata['source'],
        market='OPRA',currency='USD',timezone='America/New_York',price_basis='premium_per_quote_unit',
        scope_contract_versions=[c.version_hash for c in contracts],quote_convention='fixture bid/ask',
        time_convention='fixture observed timestamps',corporate_actions='fixture standard contracts',
        license_terms='engineering test only',reviewed_at='2024-10-31T20:20:00Z',valid_until='2025-12-31T00:00:00Z',
        decision='QUALIFIED',reviewer='fixture',reason='isolated test',evidence_type='actual',
        evidence_files={'provider.txt':hashlib.sha256((evidence/'provider.txt').read_bytes()).hexdigest()})
    monkeypatch.setattr('personal_quant.data.qualification.now_utc',lambda:'2024-10-31T20:29:30Z')
    return register_source(book,body,evidence)


def freeze(book,store,snapshot,request,calendar,archive):
    return freeze_forward(book,store,snapshot,request,calendar,archive,'sample',
        publication_delay_minutes=30,max_generation_delay_minutes=10)


def test_forward_requires_source_and_cannot_be_backdated(tmp_path,monkeypatch):
    book,store,snapshot,request,calendar,archive,contracts,metadata=setup(tmp_path,monkeypatch)
    try:
        blocked=freeze(book,store,snapshot,request,calendar,archive)
        assert blocked['status']=='BLOCKED' and not list(archive.glob('*.json'))
        qualify(book,tmp_path,contracts,metadata,monkeypatch)
        signal=freeze(book,store,snapshot,request,calendar,archive)
        assert validate_forward(signal)==signal and signal['status']=='FROZEN_FOR_FORWARD_RESEARCH'
        assert signal['data_type']=='real_market' and not signal['executable']
        assert signal['source_assessment']['status']=='QUALIFIED' and book.sequence('sample')==0
        monkeypatch.setattr('personal_quant.options.forward.now_utc',lambda:'2024-11-02T00:00:00Z')
        assert freeze(book,store,snapshot,request,calendar,archive)==signal
        with pytest.raises(QuantError) as exc:
            freeze_forward(book,store,'0'*64,request,calendar,archive,'sample',
                publication_delay_minutes=30,max_generation_delay_minutes=10)
        assert exc.value.code=='MONTHLY_INPUT_CHANGED'
        with pytest.raises(QuantError) as exc:
            freeze_forward(book,store,snapshot,request,calendar,archive,'another-account',
                publication_delay_minutes=30,max_generation_delay_minutes=10)
        assert exc.value.code=='UNKNOWN_ACCOUNT'
    finally:book.close()


def test_forward_missed_window_and_tamper_are_rejected(tmp_path,monkeypatch):
    book,store,snapshot,request,calendar,archive,contracts,metadata=setup(tmp_path,monkeypatch)
    try:
        qualify(book,tmp_path,contracts,metadata,monkeypatch)
        monkeypatch.setattr('personal_quant.options.forward.now_utc',lambda:'2024-10-31T21:30:00Z')
        with pytest.raises(QuantError) as exc:freeze(book,store,snapshot,request,calendar,archive)
        assert exc.value.code=='MISSED_FORWARD_WINDOW' and not list(archive.glob('*.json'))
        monkeypatch.setattr('personal_quant.options.forward.now_utc',lambda:'2024-10-31T20:31:00Z')
        signal=freeze(book,store,snapshot,request,calendar,archive)
        changed={**signal,'generated_at':'2024-10-31T20:22:00Z'}
        with pytest.raises(QuantError) as exc:validate_forward(changed)
        assert exc.value.code=='FORWARD_ARCHIVE_CHANGED'
        path=archive/(signal['monthly_signal_id']+'.json');path.write_text(json.dumps(changed))
        with pytest.raises(QuantError) as exc:freeze(book,store,snapshot,request,calendar,archive)
        assert exc.value.code=='FORWARD_ARCHIVE_CHANGED'
        resealed={**signal,'source_assessment':{**signal['source_assessment'],'qualification_id':'0'*64}}
        resealed['content_hash']=digest({k:v for k,v in resealed.items() if k!='content_hash'})
        path.write_text(json.dumps(resealed))
        cfg=tmp_path/'paper.toml';cfg.write_text((Path(__file__).resolve().parents[1]/'configs/demo.toml').read_text()
            .replace('environment = "demo"','environment = "paper"').replace('runtime_dir = "runtime/demo"','runtime_dir = "runtime/paper"'))
        monkeypatch.chdir(tmp_path)
        with pytest.raises(QuantError) as exc:create_bundle(book.path.parent,cfg,tmp_path/'invalid-bundle')
        assert exc.value.code=='CORRUPT_FORWARD_SIGNAL'
    finally:book.close()


def test_resealed_capture_time_cannot_replace_original_chain_manifest(tmp_path,monkeypatch):
    book,store,snapshot,request,calendar,archive,contracts,metadata=setup(tmp_path,monkeypatch)
    try:
        qualify(book,tmp_path,contracts,metadata,monkeypatch)
        signal=freeze(book,store,snapshot,request,calendar,archive)
        changed={**signal,'snapshot_created_at':'2024-10-31T20:28:00Z'}
        changed['content_hash']=digest({k:v for k,v in changed.items() if k!='content_hash'})
        assert validate_forward(changed)==changed
        with pytest.raises(QuantError) as exc:verify_snapshot(store,changed)
        assert exc.value.code=='CORRUPT_FORWARD_SIGNAL'
        path=archive/(signal['monthly_signal_id']+'.json')
        path.write_text(json.dumps(changed))
        with pytest.raises(QuantError) as exc:freeze(book,store,snapshot,request,calendar,archive)
        assert exc.value.code=='CORRUPT_FORWARD_SIGNAL'
        forged={**signal,'source_assessment':{**signal['source_assessment'],'qualification_id':'0'*64}}
        forged['content_hash']=digest({k:v for k,v in forged.items() if k!='content_hash'})
        path.write_text(json.dumps(forged))
        with pytest.raises(QuantError) as exc:freeze(book,store,snapshot,request,calendar,archive)
        assert exc.value.code=='CORRUPT_FORWARD_SIGNAL'
    finally:book.close()


def test_cached_forward_activation_rechecks_its_local_archive(tmp_path,monkeypatch):
    book,store,snapshot,request,calendar,archive,contracts,metadata=setup(tmp_path,monkeypatch)
    try:
        qualify(book,tmp_path,contracts,metadata,monkeypatch)
        signal=freeze(book,store,snapshot,request,calendar,archive)
        monkeypatch.setattr('personal_quant.options.plans.now_utc',lambda:'2024-10-31T20:32:00Z')
        plan=draft(book,store,snapshot,'sample',dict(selection=request,packages=1,risk=RISK,revision=1))
        command=dict(request_id='blocked-forward',plan_id=plan['plan_id'],as_of='2024-11-01T19:40:00Z',
            valid_until='2024-11-01T20:00:00Z',expected_sequence=0,monthly_signal=signal,
            engine_evidence_file=str(tmp_path/'missing-engine.json'),quote_snapshot_id=snapshot,reconciliation_max_days=1)
        first=activate(book,store,command)
        assert first['status']=='BLOCKED' and activate(book,store,command)==first
        changed={**signal,'snapshot_created_at':'2024-10-31T20:28:00Z'}
        changed['content_hash']=digest({k:v for k,v in changed.items() if k!='content_hash'})
        (archive/(signal['monthly_signal_id']+'.json')).write_text(json.dumps(changed))
        with pytest.raises(QuantError) as exc:activate(book,store,command)
        assert exc.value.code=='CORRUPT_FORWARD_SIGNAL' and book.sequence('sample')==0
        forged={**signal,'source_assessment':{**signal['source_assessment'],'qualification_id':'0'*64}}
        forged['content_hash']=digest({k:v for k,v in forged.items() if k!='content_hash'})
        (archive/(signal['monthly_signal_id']+'.json')).write_text(json.dumps(forged))
        fresh=activate(book,store,{**command,'request_id':'forged-original-source','monthly_signal':forged})
        assert fresh['status']=='BLOCKED' and 'FORWARD_SIGNAL_NOT_BOUND' in fresh['checks']
        assert book.sequence('sample')==0
    finally:book.close()


def test_forward_paper_plan_uses_archived_signal_and_current_qualified_quote(tmp_path,monkeypatch,engine_evidence):
    book,store,snapshot,request,calendar,archive,contracts,metadata=setup(tmp_path,monkeypatch)
    try:
        qualify(book,tmp_path,contracts,metadata,monkeypatch)
        signal=freeze(book,store,snapshot,request,calendar,archive)
        book.import_events('sample',[event('paper-capital','DEPOSIT',amount=100000)])
        monkeypatch.setattr('personal_quant.options.plans.now_utc',lambda:'2024-10-31T20:32:00Z')
        plan=draft(book,store,snapshot,'sample',dict(selection=request,packages=1,risk={**RISK,
            'maximum_loss_budget':30000,'maximum_notional':30000},revision=1))
        book.reconcile('sample',{'account_id':'sample','currency':'USD','as_of':'2024-11-01T19:38:00Z',
            'cash_basis':'settled','cash':100000,'positions':{},'equity':100000},{})
        evidence=tmp_path/'permission-evidence';evidence.mkdir()
        (evidence/'policy.txt').write_text('ISOLATED TEST ONLY: fabricated account permission')
        permission=dict(schema_version=2,asset_type='ACCOUNT_OPTION_PERMISSIONS',
            series_id=permission_series('sample','paper'),account_id='sample',environment='paper',broker='fixture',
            market='OPRA',currency='USD',scope_templates=['long_put'],scope_operations=['OPEN','CLOSE'],
            settlement_policy='cash_account_no_margin',exercise_policy='close_before_expiry',
            maximum_contracts=1,maximum_physical_cash='0',minimum_exit_days=7,
            reviewed_at='2024-10-31T20:25:00Z',valid_until='2025-12-31T00:00:00Z',decision='QUALIFIED',
            reviewer='fixture',reason='engineering test only',evidence_type='actual',
            evidence_files={'policy.txt':hashlib.sha256((evidence/'policy.txt').read_bytes()).hexdigest()})
        monkeypatch.setattr('personal_quant.data.qualification.now_utc',lambda:'2024-10-31T20:33:00Z')
        register_permissions(book,permission,evidence)
        registered,rows,_,_=store.load(snapshot)
        selected={leg['contract']['contract_id'] for leg in signal['selection']['legs']}
        for row in rows:
            if row['contract_id'] in selected:
                row.update(exchange_timestamp='2024-11-01T19:39:00Z',underlying_timestamp='2024-11-01T19:39:00Z',
                           available_at='2024-11-01T19:39:02Z',received_at='2024-11-01T19:39:04Z')
        monkeypatch.setattr('personal_quant.options.data.now_utc',lambda:'2024-11-01T19:39:05Z')
        current=store.save(list(registered.values()),pd.DataFrame(rows),metadata)['snapshot_id']
        activation=dict(request_id='paper-forward',plan_id=plan['plan_id'],as_of='2024-11-01T19:40:00Z',
            valid_until='2024-11-01T20:00:00Z',expected_sequence=1,monthly_signal=signal,
            engine_evidence_file=str(engine_evidence),quote_snapshot_id=current,reconciliation_max_days=1)
        audit=activate(book,store,activation)
        assert audit['status']=='ACTIVATED',audit['checks']
        assert audit['result']['activation']['data_type']=='forward_paper'
        assert audit['result']['status']=='READY' and book.sequence('sample')==1
        assert activate(book,store,activation)==audit and book.sequence('sample')==1
        template=(Path(__file__).resolve().parents[1]/'configs/demo.toml').read_text()
        cfg=tmp_path/'paper.toml';cfg.write_text(template.replace('environment = "demo"','environment = "paper"')
            .replace('runtime_dir = "runtime/demo"','runtime_dir = "runtime/paper"'))
        monkeypatch.chdir(tmp_path)
        create_bundle(book.path.parent,cfg,tmp_path/'bundle');verify_bundle(tmp_path/'bundle','paper')
        restore_bundle(tmp_path/'bundle',tmp_path/'restored','paper')
        recovered=Ledger(tmp_path/'restored/runtime/paper/account.sqlite','paper')
        try:
            assert recovered.sequence('sample')==1
            assert review(recovered,plan['plan_id'],activation['as_of'])['status']=='READY'
            frozen=json.loads((tmp_path/'restored/runtime/paper/options/monthly-forward'/
                (signal['monthly_signal_id']+'.json')).read_text())
            assert validate_forward(frozen)==signal
        finally:recovered.close()
    finally:book.close()
