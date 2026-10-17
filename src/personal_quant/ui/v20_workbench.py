"""v2 workspace inputs, operator jobs and read-only capital allocation controls."""
import json
from pathlib import Path
from uuid import uuid4
import pandas as pd
import streamlit as st
from ..common import QuantError,digest


def submit(workspace,request,key):
    from ..workspace.operations import submit as enqueue
    budget=st.session_state.get('v20-task-seconds',3600.)
    intent=digest({'request':request,'max_seconds':budget});state=st.session_state.setdefault('v20-operation-intents',{})
    request_id=state.setdefault(key+intent,uuid4().hex)
    result=enqueue(workspace,request,request_id=request_id,max_seconds=budget)
    st.info('任务已登记：'+result['job_id']+'；运行状态页查看实际结果，重复提交返回同一任务。')


def controls(workspace,config,page,clock):
    root=Path(workspace)
    with st.expander('后台任务总预算'):
        st.number_input('配置/研究/维护总预算秒数（含排队与启动）',min_value=.1,max_value=86400.,value=3600.,key='v20-task-seconds')
        st.caption('到期只停止本任务的自有进程组；已提交事实或发布目录必须核实，不假定操作未发生。批量推进另用其交易日/时间/容量预算。')
    if page=='运行状态':
        capability_controls(root)
        workspace_controls(root,config)
        operation_controls(root)
        recovery_controls(root)
    if page=='调仓计划':capital_controls(root,config,clock)
    if page=='策略研究':research_controls(root,config)


def workspace_controls(workspace,config):
    from ..workspace.service import create,read_workspace
    from ..workspace.packages import verify
    from ..workspace.servers import open_viewer
    with st.expander('v2.0 工作区与通用输入'):
        st.caption('每个实验独立模拟资金和账本。先核验输入，再建立工作区；打开新窗口不切换当前账户或写入成交。')
        target=st.text_input('新实验目录',value=str(workspace.parent/'LyraX-new-experiment'),key='v20-new-directory')
        kind=st.selectbox('实验类型',['etf','options'],format_func=lambda v:'ETF模拟' if v=='etf' else '期权模拟',key='v20-new-kind')
        account=st.text_input('模拟账户名称',value='demo-account',key='v20-new-account')
        capital=st.number_input('初始模拟资金 USD',min_value=1.,value=100000.,key='v20-new-capital')
        source=st.text_input('冻结输入包目录（留空使用旧固定示例）',key='v20-input-package')
        if st.button('只读核验输入包',key='v20-preview-package'):
            try:submit(workspace,{'operation':'verify-input','source':source},'verify-input')
            except (QuantError,OSError,ValueError) as exc:st.error(str(exc))
        if st.button('建立独立模拟实验',key='v20-create-workspace'):
            try:
                spec={'schema_version':1,'account_id':account,'initial_cash':str(capital),'kind':kind}
                if source:spec['input_bundle']=source
                result=create(target,spec,config);st.success('工作区已建立，尚未产生策略成交。');st.json(result,expanded=False)
            except (QuantError,OSError,ValueError) as exc:st.error(str(exc))
        port=st.number_input('新窗口本地端口',min_value=1024,max_value=65535,value=8502,key='v20-new-port')
        if st.button('打开该实验的独立看板',key='v20-open-workspace'):
            try:st.session_state['v20-workspace-link']=open_viewer(target,port)
            except (QuantError,OSError,ValueError) as exc:st.error(str(exc))
        link=st.session_state.get('v20-workspace-link')
        if link:st.link_button('进入独立实验看板',link['url'])
    scenario_controls(workspace,config)
    csv_controls(workspace,config)


def scenario_controls(workspace,config):
    with st.expander('v2.0 多月模型场景生成器'):
        st.caption('QuantLib美式模型 + 固定种子；不是实际行情或可成交报价。节点在对应日期才生效，缺价不补成可交易。')
        with st.form('v20-scenario-form'):
            start=st.date_input('场景开始',value=pd.Timestamp(config.evaluation_start).date(),key='v20-scenario-start')
            end=st.date_input('场景结束',value=pd.Timestamp(config.evaluation_end).date(),key='v20-scenario-end')
            symbol=st.selectbox('模型期权标的',list(config.symbols),key='v20-scenario-symbol')
            initial=st.number_input('模型标的初始价格',min_value=.01,value=100.,key='v20-scenario-price')
            iv=st.number_input('模型初始隐含波动率',min_value=.01,max_value=4.,value=.25,key='v20-scenario-iv')
            vol=st.number_input('每日价格波动参数',min_value=0.,max_value=.2,value=.005,key='v20-scenario-vol')
            seed=st.number_input('固定随机种子',value=20261017,step=1,key='v20-scenario-seed')
            dte=st.number_input('生成合约到期天数',min_value=7,max_value=90,value=21,key='v20-scenario-dte')
            width=st.number_input('行权价间隔 USD',min_value=.01,value=5.,key='v20-scenario-width')
            spread=st.number_input('模型买卖总价差 USD',min_value=.01,value=.10,key='v20-scenario-spread')
            nodes=st.data_editor(pd.DataFrame(columns=['交易日期','标的价格','隐含波动率']),num_rows='dynamic',key='v20-scenario-nodes')
            destination=st.text_input('新场景包目录',value=str(workspace.parent/'LyraX-model-input'),key='v20-scenario-destination')
            clicked=st.form_submit_button('后台生成冻结场景包')
        if clicked:
            try:
                prices={};ivs={str(start):iv}
                for row in nodes.to_dict('records'):
                    day=str(pd.Timestamp(row['交易日期']).date())
                    if pd.notna(row['标的价格']):prices[day]=float(row['标的价格'])
                    if pd.notna(row['隐含波动率']):ivs[day]=float(row['隐含波动率'])
                spec={'schema_version':1,'start':str(start),'end':str(end),'initial_prices':{s:initial for s in config.symbols},
                    'price_nodes':{s:prices if s==symbol else {} for s in config.symbols},'daily_volatility':vol,'iv_nodes':ivs,
                    'option_underlying':symbol,'expiry_days':dte,'strike_step':width,'spread':spread,'seed':seed,'missing_quotes':[],'corporate_actions':[]}
                submit(workspace,{'operation':'scenario','spec':spec,'destination':destination},'scenario')
            except (QuantError,OSError,ValueError,TypeError) as exc:st.error(str(exc))


def operation_controls(workspace):
    with st.expander('v2.0 后台备份、核验、恢复与导出'):
        st.caption('耗时操作在独立持久任务执行。页面刷新只读取状态；已完成任务不会重复执行。恢复目标必须是新目录。')
        op=st.selectbox('维护操作',['backup','verify','restore','export'],format_func=lambda v:{'backup':'完整备份','verify':'核验当前工作区备份','restore':'核验并隔离恢复','export':'导出运行完整包'}[v],key='v20-maintenance-op')
        source=st.text_input('维护源目录',key='v20-maintenance-source')
        destination=st.text_input('维护目标新目录',key='v20-maintenance-destination')
        from ..workspace.service import status
        runs=status(workspace)['runs']
        run=st.selectbox('选择导出的模拟运行',[r['run_id'] for r in runs],format_func=lambda identity:identity[:12]+' · '+next(r['status'] for r in runs if r['run_id']==identity),key='v20-maintenance-run') if runs else None
        if st.button('提交后台维护',key='v20-maintenance-submit'):
            request={'operation':op}
            if op in {'verify','restore'}:request['source']=source
            if op in {'backup','restore','export'}:request['destination']=destination
            if op=='export':request['run_id']=run
            try:submit(workspace,request,'maintenance')
            except (QuantError,OSError,ValueError) as exc:st.error(str(exc))


def recovery_controls(workspace):
    from ..workspace.jobs import list_jobs,review
    with st.expander('v2.0 任务核实与恢复'):
        if st.button('重建任务排序索引',key='v20-job-index'):
            from ..workspace.job_index import rebuild
            try:st.json(rebuild(workspace))
            except (QuantError,OSError,ValueError) as exc:st.error(str(exc))
        offset=st.number_input('任务起始记录',min_value=0,value=0,step=20,key='v20-job-offset')
        rows=list_jobs(workspace,limit=20,offset=offset)
        st.dataframe(pd.DataFrame(job_rows(rows)),hide_index=True)
        blocked={r['job_id']:r for r in rows if r['status'] in {'INTERRUPTED','UNVERIFIED','SUBMITTED'}}
        if blocked:
            job=st.selectbox('待核实任务',list(blocked),key='v20-review-job')
            reason=st.text_input('核实依据（检查进程及已提交事实后填写）',key='v20-review-reason')
            confirmed=st.checkbox('已核实原任务不再运行；保留全部原始凭据与账户事实',key='v20-review-confirm')
            if st.button('记录人工核实',key='v20-review-submit'):
                try:st.json(review(workspace,job,{'files_hash':blocked[job]['files_hash'],'reason':reason,'confirm_no_inflight':confirmed}))
                except (QuantError,OSError,ValueError) as exc:st.error(str(exc))
        failed={r['job_id']:r for r in rows if r['status']=='FAILED'}
        if failed:
            job=st.selectbox('失败任务的新尝试',list(failed),key='v20-retry-job')
            if st.button('按原始请求重试失败任务',key='v20-retry-submit'):
                try:
                    from ..workspace.jobs import retry
                    intents=st.session_state.setdefault('v20-retry-intents',{})
                    result=retry(workspace,job,files_hash=failed[job]['files_hash'],request_id=intents.setdefault(job,uuid4().hex))
                    st.info('已登记新尝试：'+result['job_id'])
                except (QuantError,OSError,ValueError) as exc:st.error(str(exc))
        normal={r['job_id']:r for r in rows}
        if normal:
            job=st.selectbox('查看任务日志',list(normal),key='v20-log-job')
            from ..workspace.service import read_workspace
            root,_,config,_=read_workspace(workspace);log=root/config.runtime_dir/'simulation/jobs'/job/'worker.log'
            if log.is_file() and not log.is_symlink():
                with log.open('rb') as stream:
                    stream.seek(max(0,log.stat().st_size-65536));tail=stream.read(65536).decode('utf-8',errors='replace')
                # Financial request and tool credentials are never intentionally printed by workers.
                import re
                tail=re.sub(r'(?i)((?:api[_-]?key|token|password|secret)\s*[=:]\s*)[^\s,;]+',r'\1[REDACTED]',tail)
                st.download_button('下载任务日志末尾（最多64 KiB）',tail,file_name='LyraX-task.log',key='v20-log-download')


def capital_controls(workspace,config,clock):
    from ..workspace.capital import preview,validate
    with st.expander('v2.0 多策略资金分配预演（只读）'):
        st.caption('不生成成交、不预留或调拨。共享现金/股份冲突会阻断；账户变化后预演失效。金额均USD。')
        rows=st.data_editor(pd.DataFrame([{'strategy_id':'strategy-1','cash_budget':1000.,'premium':100.,'collateral':0.,'fees':10.,'buffer':10.,'symbol':config.symbols[0],'shares':0.}]),num_rows='dynamic',key='v20-capital-editor')
        prices=st.data_editor(pd.DataFrame([{'symbol':s,'price':100.} for s in config.symbols]),key='v20-capital-prices')
        if st.button('只读计算资金分配',key='v20-capital-submit'):
            try:
                from ..workspace.service import read_workspace
                _,identity,_,_=read_workspace(workspace)
                request={'schema_version':1,'account_id':identity['account_id'],'as_of':clock,
                    'prices':{r['symbol']:r['price'] for r in prices.to_dict('records')},'allocations':[
                        {'strategy_id':r['strategy_id'],'cash_budget':r['cash_budget'],
                         'requirements':{k:r[k] for k in ('premium','collateral','fees','buffer')},
                         'coverage_shares':{r['symbol']:r['shares']} if r['shares'] else {}} for r in rows.to_dict('records')]}
                st.session_state['v20-capital-result']=(request,preview(workspace,request))
            except (QuantError,OSError,ValueError,KeyError) as exc:st.error(str(exc))
        saved=st.session_state.get('v20-capital-result')
        if saved:
            state=validate(workspace,*saved)
            if state['status']=='STALE':st.warning('账本或计划已变化，请重新计算预演。')
            st.json(saved[1],expanded=False)


def launch_simulation(workspace,action,*args,**kwargs):
    from ..workspace.jobs import launch
    if action!='batch':kwargs.setdefault('max_seconds',st.session_state.get('v20-task-seconds',3600.))
    request={'workspace':str(workspace),'action':action,'args':args,'kwargs':{k:str(v) for k,v in kwargs.items()}}
    file=kwargs.get('input_file')
    if file and Path(file).is_file():
        import hashlib
        request['input_sha256']=hashlib.sha256(Path(file).read_bytes()).hexdigest()
    intent=digest(request)
    identities=st.session_state.setdefault('v20-simulation-intents',{})
    request_id=identities.setdefault(intent,uuid4().hex)
    return launch(workspace,action,*args,request_id=request_id,**kwargs)


def research_controls(workspace,config):
    from .options import LABELS
    from ..options.catalog import MONTHLY_RESEARCH
    with st.expander('v2.0 预声明期权研究协议'):
        st.caption('先冻结问题和开发/评估窗口，再运行。最多24组实验；同窗口、成本、资本内与股票/现金比较，不跨窗口拼接净值。')
        with st.form('v20-research-form'):
            question=st.text_input('研究问题',value='固定月度规则在分离窗口与费用压力下的差异',key='v20-research-question')
            source=st.text_input('研究冻结输入包',key='v20-research-input')
            destination=st.text_input('新研究目录',value=str(Path(workspace).parent/'LyraX-option-study'),key='v20-research-destination')
            templates=st.multiselect('预声明候选模板',sorted(MONTHLY_RESEARCH),default=['long_call'],format_func=lambda v:LABELS[v],key='v20-research-templates')
            initial=st.number_input('研究初始资金 USD',min_value=1.,value=100000.,key='v20-research-capital')
            packages=st.number_input('研究每月包数',min_value=1,max_value=100,value=1,key='v20-research-packages')
            start=pd.Timestamp(config.evaluation_start).date();end=pd.Timestamp(config.evaluation_end).date()
            middle=(pd.Timestamp(start)+(pd.Timestamp(end)-pd.Timestamp(start))/2).date()
            dev_start=st.date_input('开发窗口首决策日',value=start,key='v20-research-dev-start')
            dev_end=st.date_input('开发窗口末决策日',value=middle,key='v20-research-dev-end')
            eval_start=st.date_input('评估窗口首决策日',value=middle+pd.Timedelta(days=1),key='v20-research-eval-start')
            eval_end=st.date_input('评估窗口末决策日',value=end,key='v20-research-eval-end')
            target=st.number_input('研究目标到期天数',min_value=1,value=21,key='v20-research-dte')
            minimum=st.number_input('研究最小到期天数',min_value=1,value=14,key='v20-research-min-dte')
            maximum=st.number_input('研究最大到期天数',min_value=1,value=35,key='v20-research-max-dte')
            put=st.number_input('研究Put阈值/标的价',min_value=.01,max_value=.99,value=.95,key='v20-research-put')
            call=st.number_input('研究Call阈值/标的价',min_value=1.01,value=1.05,key='v20-research-call')
            width=st.number_input('研究信用价差/四腿最小翼宽',min_value=.01,value=5.,key='v20-research-width')
            exit_days=st.number_input('研究到期前退出自然日数',min_value=0,value=3,key='v20-research-exit')
            spread=st.number_input('研究最大报价价差比例',min_value=0.,max_value=1.,value=.25,key='v20-research-spread')
            base_fee=st.number_input('基础期权佣金 USD/张/次',min_value=0.,value=2.,key='v20-research-fee')
            stress_fee=st.number_input('压力期权佣金 USD/张/次',min_value=0.,value=4.,key='v20-research-fee-stress')
            bps=st.number_input('股票佣金 bps',min_value=0.,value=2.,key='v20-research-stock-fee')
            st.caption('报价年龄3600秒、标的时差60秒、腿间时差10秒、标的偏离1%；零现金利息、统一约定平仓。以上研究假设随协议冻结。')
            clicked=st.form_submit_button('后台冻结研究协议')
        if clicked:
            parameters={'minimum_dte':minimum,'target_dte':target,'maximum_dte':maximum,'put_moneyness':put,'call_moneyness':call,
                'exit_days_before_expiry':exit_days,'max_age_seconds':3600,'max_underlying_skew_seconds':60,'max_leg_skew_seconds':10,
                'max_underlying_price_fraction':.01,'max_spread_fraction':spread}
            spec={'schema_version':1,'question':question,'input_bundle':source,'initial_cash':initial,'templates':templates,
                'windows':[{'name':'development','purpose':'development','decision_start':str(dev_start),'decision_end':str(dev_end)},
                           {'name':'assessment','purpose':'assessment','decision_start':str(eval_start),'decision_end':str(eval_end)}],
                'costs':[{'name':name,'fee_per_contract':fee,'stock_commission_bps':bps,'spread_multiplier':1} for name,fee in [('base',base_fee),('fee-stress',stress_fee)]],
                'selection_parameters':{name:{**parameters,**({'minimum_spread_width':width} if name.endswith('credit_spread') or name in {'iron_condor','iron_butterfly'} else {})} for name in templates},
                'packages':packages,'exit_policy':'scheduled_close','cash_interest':0}
            try:submit(workspace,{'operation':'research-freeze','spec':spec,'destination':destination},'research-freeze')
            except (QuantError,OSError,ValueError) as exc:st.error(str(exc))
        st.caption('执行使用工作台已选择的LEAN/SDK，参数改变需新研究目录；不会用结果自动选参。')
        if st.button('后台运行已冻结研究',key='v20-research-run'):
            try:submit(workspace,{'operation':'research-run','source':destination,'engine_root':st.session_state.get('v195-engine',''),
                    'dotnet':st.session_state.get('v195-dotnet','')},'research-run')
            except (QuantError,OSError,ValueError) as exc:st.error(str(exc))
        file=Path(destination)/'result.json'
        if file.is_file() and not file.is_symlink():
            try:
                result=json.loads(file.read_text());st.caption(result['data_type']+' · '+result['completed_at'])
                st.dataframe(pd.DataFrame([{k:r.get(k) for k in ('template_id','window','cost','status','covered_decisions','candidate_decisions','code','reason')} for r in result['experiments']]))
                st.download_button('下载研究协议结果',json.dumps(result,ensure_ascii=False,indent=2),file_name='LyraX-research-result.json',key='v20-research-download')
            except (ValueError,KeyError,TypeError,OSError) as exc:st.error('研究结果无法核验：'+str(exc))


def csv_controls(workspace,config):
    from ..workspace.csv_package import preview
    from ..common import write_json
    with st.expander('v2.0 标准CSV导入预检'):
        upload=st.file_uploader('日线行情CSV（含原价、复权价、行动和可用时间）',type='csv',key='v20-csv-upload')
        st.caption('标准字段保持原名；自定义列可映射。不填补缺价或时区，available_at必须带时区。预检不写账本。')
        mapping=st.data_editor(pd.DataFrame(columns=['源列名','标准列名']),num_rows='dynamic',key='v20-csv-mapping')
        calendar=st.text_input('可选显式交易日历CSV路径',key='v20-csv-calendar')
        calendar_kind=st.selectbox('CSV日历类型',['verified_market_sessions','synthetic_test_sessions'],key='v20-csv-calendar-kind')
        destination=st.text_input('CSV输入包新目录',value=str(Path(workspace).parent/'LyraX-csv-input'),key='v20-csv-destination')
        if st.button('预检行情CSV',key='v20-csv-preview'):
            try:
                if upload is None:raise QuantError('CSV_REQUIRED','请上传CSV')
                fields={r['源列名']:r['标准列名'] for r in mapping.to_dict('records')}
                result=preview(upload.getvalue(),fields,calendar_file=calendar or None,calendar_kind=calendar_kind)
                st.session_state['v20-csv-result']=result
            except (QuantError,OSError,ValueError,KeyError) as exc:
                st.session_state.pop('v20-csv-result',None);st.error(str(exc))
        result=st.session_state.get('v20-csv-result')
        if result:
            st.json(result,expanded=False)
            if st.button('后台导入已预检CSV',key='v20-csv-commit'):
                try:
                    if upload is None:raise QuantError('CSV_REQUIRED','上传文件已清除，请重新预检')
                    import hashlib
                    if hashlib.sha256(upload.getvalue()).hexdigest()!=result['csv_sha256']:raise QuantError('CSV_PREVIEW_CHANGED','上传文件已改变，请重新预检')
                    file=Path(workspace)/config.runtime_dir/'simulation/import-requests'/(result['csv_sha256']+'.csv')
                    file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(upload.getvalue())
                    submit(workspace,{'operation':'csv-import','source':str(file),'mapping':result['mapping'],'destination':destination,
                        'expected_preview':result['preview_id'],'calendar_file':result['calendar_file'],'calendar_kind':result['calendar_kind']},'csv-import')
                except (QuantError,OSError,ValueError) as exc:st.error(str(exc))
        if st.button('清除未提交的CSV预检',key='v20-csv-cancel'):st.session_state.pop('v20-csv-result',None);st.rerun()


def job_rows(rows):
    states={'SUCCEEDED':'任务已结束','SUCCESS':'任务已结束','RUNNING':'运行中','SUBMITTED':'已提交','FAILED':'失败',
        'INTERRUPTED':'中断待核实','UNVERIFIED':'未知待核实','UNKNOWN':'未知待核实','REVIEWED':'已人工核实','COMPLETED':'模拟完成','CREATED':'已建运行',
        'PREPARED':'配置已冻结','PAUSED':'模拟暂停','BLOCKED':'检查阻断','WAITING_FOR_DATA':'等待数据'}
    actions={'prepare':'冻结配置','start':'建立运行','batch':'批量推进','resume':'继续','step':'推进','operation':'维护/研究'}
    phases={'CLAIMED':'已认领','PRECHECK':'运行前检查','EXECUTING':'执行任务','ENGINE_PRECHECK':'核对引擎输入','ENGINE_EXECUTION':'原生引擎运行','ACCOUNT_VALIDATION':'核对账本','PUBLISHING':'发布回执'}
    result=[]
    for row in rows:
        receipt=row.get('result',{});started=row.get('started_at')
        batch=receipt.get('batch') if isinstance(receipt.get('batch'),dict) else {}
        result.append({'任务':row['job_id'][:12],'动作':actions.get(row.get('action'),'待核实'),
            '任务状态':states.get(row.get('job_status'),row.get('job_status','未知')),
            '业务状态':states.get(row.get('run_status'),row.get('run_status','尚无回执')),
            '开始（上海时间）':str(pd.Timestamp(started).tz_convert('Asia/Shanghai')) if started else '未知',
            '原因代码':receipt.get('code') or batch.get('reason') or row.get('code') or '',
            '阶段':phases.get(row.get('phase'),row.get('phase') or '尚无阶段回执'),'身份核验时间':row.get('owner_verified_at',''),
            '总预算截止（上海时间）':str(pd.Timestamp(row['deadline_at']).tz_convert('Asia/Shanghai')) if row.get('deadline_at') else '未知','索引':row.get('task_index',{}).get('status','未知'),'文件指纹':row.get('files_hash','')[:12]})
    return result


def capability_controls(workspace):
    from ..options.catalog import MONTHLY_RESEARCH
    from .options import LABELS
    with st.expander('v2.0 当前模板能力与独立资格'):
        template=st.selectbox('核验模板',sorted(MONTHLY_RESEARCH),format_func=lambda v:LABELS[v],key='v20-capability-template')
        evidence=st.text_input('模板生命周期证据文件',key='v20-capability-evidence')
        package=st.text_input('模板冻结输入包',key='v20-capability-input')
        st.caption('名称或目录不代表来源、账户权限或资金检查通过；显式任务核对当前源码和模板，不在刷新时扫描引擎。')
        if st.button('后台核验模板分项能力',key='v20-capability-submit'):
            try:submit(workspace,{'operation':'capabilities','template_id':template,'engine_evidence':evidence,'input_bundle':package},'capabilities')
            except (QuantError,OSError,ValueError) as exc:st.error(str(exc))
