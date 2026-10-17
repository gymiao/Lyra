from pathlib import Path
from personal_quant.portfolio import Ledger
from personal_quant.portfolio.upgrade import enable_v19
from personal_quant.portfolio.backup import create_bundle,restore_bundle
from personal_quant.options.ledger import register_contract
from personal_quant.options.data import OptionDataStore
from test_backup import scenario
from test_options_data_v19 import sample
from conftest import event
import pandas as pd


def test_v4_to_v5_preserves_old_facts_and_option_chain_backup(tmp_path,monkeypatch):
    root,config,_,rows=scenario(tmp_path,monkeypatch)
    book=Ledger(root/'account.sqlite','demo')
    before=book.snapshot('sample','2024-07-31T21:00:00Z',{'SPY':49.5})
    upgraded=enable_v19(book,config)
    assert upgraded['schema_version']==5 and upgraded['backup']
    assert enable_v19(book,config)['backup'] is None
    after=book.snapshot('sample','2024-07-31T21:00:00Z',{'SPY':49.5})
    assert {k:after[k] for k in before}==before
    c,q,m=sample();register_contract(book,c.content())
    saved=OptionDataStore(root/'options/chains').save([c],pd.DataFrame([q]),m)
    book.close()
    bundle=tmp_path/'bundle';create_bundle(root,config,bundle)
    restored=tmp_path/'restored';restore_bundle(bundle,restored,'demo')
    restored_book=Ledger(restored/root/'account.sqlite','demo')
    assert restored_book.import_events('sample',rows)['added']==0
    assert restored_book.snapshot('sample','2024-07-31T21:00:00Z',{'SPY':49.5})['equity']=='998.5'
    assert OptionDataStore(restored/root/'options/chains').load(saved['snapshot_id'])[3]['rows']==1
    restored_book.close()
