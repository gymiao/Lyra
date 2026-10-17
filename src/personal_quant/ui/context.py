"""Persist view choices independently from Streamlit's transient widget storage."""
import json
from pathlib import Path
import pandas as pd
import streamlit as st


def view_context(config,config_path,root):
    workspace=root/'simulation/workspace.json'
    body=json.loads(workspace.read_text()) if workspace.exists() else None
    identity=str(Path(config_path).absolute())+'|'+config.environment+'|'+config.hash+'|'+(body['workspace_id'] if body else 'legacy')
    key='lyrax-view-context'
    current=st.session_state.get(key)
    if current is None or current['workspace']!=identity:
        for name in list(st.session_state):
            if name.startswith(('view-','v195-','v20-','import_')) or name in {'preview_account','price_preview_hash'}:
                del st.session_state[name]
        default=pd.Timestamp(config.evaluation_end,tz='UTC')+pd.Timedelta(hours=21,minutes=30)
        if body:
            default=pd.Timestamp(body.get('view_at',default))
            account=body.get('account_id','demo-account')
            if (root/'reports/account-latest/latest.json').exists():
                from ..portfolio.report import load_account_report
                from ..common import QuantError
                try:
                    report=load_account_report(root/'reports/account-latest')
                    if report['account_id']==account:default=pd.Timestamp(report['as_of'])
                except (QuantError,OSError,ValueError,KeyError):pass
        else:account='demo-account' if config.environment=='demo' else ''
        current={'workspace':identity,'account':account,
                 'clock':default.isoformat()}
        st.session_state[key]=current
    return current


def field(context,label,name,widget_key,*,sidebar=False):
    if widget_key not in st.session_state:st.session_state[widget_key]=context[name]
    def sync():context[name]=st.session_state[widget_key]
    container=st.sidebar if sidebar else st
    value=container.text_input(label,key=widget_key,on_change=sync)
    context[name]=value
    return value
