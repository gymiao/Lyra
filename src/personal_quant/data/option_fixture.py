"""Fixed, declared synthetic chains; never presented as historical market data."""
import pandas as pd
from ..common import decimal as D
from ..options.contracts import OptionContract
from ..options.data import OptionDataStore

VERSION='synthetic-monthly-world/1.95.1'


def create(root,underlying,calendar):
    store=OptionDataStore(root);months=[];prices={}
    metadata={'schema_version':1,'source':VERSION,'data_type':'synthetic','license_terms':'locally generated engineering fixture',
        'unit_evidence':'fictional standard 100-share American physical terms; not OCC or broker evidence',
        'available_time_basis':'frozen synthetic month-end timestamps; not real-time collection'}
    strikes=[90,95,100,105,110];bids={'CALL':['11','6','2','1','0.5'],'PUT':['0.5','1','2','6','11']}
    for session,expiry,listed in [('2024-10-31','2024-12-18','2024-10-01'),('2024-11-29','2025-01-17','2024-11-01')]:
        contracts=[];rows=[];at=calendar.close(session)-pd.Timedelta(minutes=1)
        for right in ['CALL','PUT']:
            for strike,bid in zip(strikes,bids[right]):
                body={'contract_id':f'SYNTHETIC-{underlying}-{expiry}-{right}{strike}','revision':VERSION,
                    'underlying':underlying,'currency':'USD','market_timezone':'America/New_York','right':right,'strike':str(strike),
                    'expiry':expiry,'listed_at':listed+'T13:30:00Z','last_trade_at':calendar.close(expiry).isoformat(),
                    'exercise_cutoff_at':(calendar.close(expiry)+pd.Timedelta(minutes=90)).isoformat(),
                    'quote_multiplier':'100','deliverable_shares':'100','deliverable_cash':'0','exercise_cash':str(strike*100),
                    'settlement':'PHYSICAL','style':'AMERICAN','tick_size':'0.01','evidence_hash':'synthetic_standard_terms_not_actual_evidence'}
                contract=OptionContract.from_dict(body);contracts.append(body)
                ask=str(D(bid)+D('.05'));prices[contract.contract_id]={'bid':bid,'ask':ask,'known_session':session,'expiry':expiry}
                row={'contract_id':contract.contract_id,'contract_version':contract.version_hash,'source':VERSION,
                    'bid':bid,'ask':ask,'last':bid,'underlying_price':'100','bid_size':'100','ask_size':'100',
                    'volume':'1000','open_interest':'2000'}
                for key in ['exchange_timestamp','available_at','received_at','last_timestamp','underlying_timestamp','open_interest_available_at']:row[key]=at.isoformat()
                rows.append(row)
        identity=store.save(contracts,pd.DataFrame(rows),metadata)['snapshot_id'];months.append({'session':session,'snapshot_id':identity})
    return store,months,prices
