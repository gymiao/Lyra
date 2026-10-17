"""Actual Chromium v2.0 workspace/Wheel/operator workflow; owned services only."""
import argparse,json,os,sqlite3,time
from pathlib import Path
from dataclasses import replace
from playwright.sync_api import sync_playwright
from personal_quant.common import write_json,now_utc
from personal_quant.config import Config
from personal_quant.strategies.archive import source_fingerprint
from personal_quant.workspace.service import create,status
from personal_quant.workspace.scenarios import generate
from personal_quant.workspace.servers import open_viewer,stop_viewer


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True);parser.add_argument('--engine-root',required=True);parser.add_argument('--dotnet',required=True)
    parser.add_argument('--chromium');a=parser.parse_args()
    root=Path(__file__).absolute().parents[1]
    alias=Path('/mnt/c/quant/project/lyra')
    if alias.is_dir() and alias.samefile(root):root=alias
    out=a.destination.absolute();out.mkdir(parents=True,exist_ok=False)
    config=replace(Config.load(root/'configs/demo.toml'),evaluation_end='2024-10-31')
    scenario=json.loads((root/'configs/v20-scenario.json').read_text());scenario['daily_volatility']=0;scenario['price_nodes']={s:{} for s in scenario['initial_prices']}
    package=out/'inputs';generate(scenario,package)
    harness=out/'launcher';create(harness,{'schema_version':1,'kind':'options','account_id':'demo-account','initial_cash':100000},config)
    source=source_fingerprint();checks=[];owned=[]
    def mark(action,workspace):
        state=status(workspace);checks.append({'action':action,'workspace':str(workspace),'events':state['events'],'runs':state['runs']});write_json(out/'progress.json',checks);print(action,flush=True)
    def wait(page,condition,seconds=180):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            assert not page.get_by_test_id('stException').count(),page.get_by_test_id('stException').all_text_contents()
            if condition():return
            page.wait_for_timeout(500)
        raise AssertionError('Browser condition timed out')
    def idle(workspace):
        return all((p.parent/'result.json').is_file() for p in (workspace/'runtime/demo/simulation/jobs').glob('*/job.json'))
    def pick(page,label,value):
        box=page.get_by_test_id('stSelectbox').filter(has=page.get_by_text(label,exact=True))
        # Current Streamlit renders the selected label as the combobox input
        # value, not a text node. Filter before choosing a virtualized option.
        page.wait_for_timeout(400)
        combo=box.get_by_role('combobox')
        if combo.input_value()==value:return
        combo.fill(value)
        page.get_by_role('option',name=value,exact=True).click()
        page.wait_for_timeout(400)
        assert combo.input_value()==value,('selection did not persist',label,value)
    def fill(page,label,value):
        box=page.get_by_label(label,exact=True);box.fill(str(value));box.press('Tab')
        page.wait_for_timeout(400)
    def open_page(context,workspace,port):
        server=open_viewer(workspace,port);owned.append(workspace);page=context.new_page()
        end=time.monotonic()+30
        while True:
            try:page.goto(server['url']);break
            except Exception:
                if time.monotonic()>end:raise
                time.sleep(.3)
        page.get_by_role('heading',name='LyraX 个人投资系统',exact=True).wait_for(timeout=40000)
        page.get_by_test_id('stSidebar').get_by_text('运行状态',exact=True).click();return page
    try:
        with sync_playwright() as driver:
            browser=driver.chromium.launch(executable_path=a.chromium or driver.chromium.executable_path,headless=True,
                env=dict(os.environ,LD_LIBRARY_PATH=os.environ.get('LYRAX_BROWSER_LIBRARY_PATH',os.environ.get('LD_LIBRARY_PATH','')),FONTCONFIG_FILE=os.environ.get('LYRAX_BROWSER_FONTCONFIG',os.environ.get('FONTCONFIG_FILE','/etc/fonts/fonts.conf')),XDG_CACHE_HOME=str(out/'browser-cache')))
            context=browser.new_context(viewport={'width':1440,'height':1100},accept_downloads=True)
            page=open_page(context,harness,8540)
            page.get_by_text('v2.0 工作区与通用输入',exact=True).click()
            for kind in ['etf','options']:
                target=out/('created-'+kind)
                fill(page,'新实验目录',target);pick(page,'实验类型','ETF模拟' if kind=='etf' else '期权模拟')
                fill(page,'冻结输入包目录（留空使用旧固定示例）',package if kind=='options' else '')
                page.get_by_role('button',name='建立独立模拟实验',exact=True).click()
                wait(page,lambda:target.is_dir())
                assert status(target)['events']==1 and not status(target)['runs'];mark('browser-create-'+kind,target)
            wheel=out/'created-options';wp=open_page(context,wheel,8541)
            for label,value in [('LEAN 源码目录（绝对路径）',a.engine_root),('dotnet 可执行文件（绝对路径）',a.dotnet)]:fill(wp,label,value)
            wp.get_by_text('期权模拟配置：冻结输入与月度规则',exact=True).click()
            fill(wp,'多月场景输入包（留空使用固定两月样例）',package)
            pick(wp,'月度期权模板','Wheel（按实际交割切换Put/Call）')
            for label,value in [('最小到期天数',14),('目标到期天数',21),('最大到期天数',35),('到期前退出自然日数',0)]:fill(wp,label,value)
            wp.get_by_role('button',name='后台冻结合成配置',exact=True).click()
            wait(wp,lambda:bool(list((wheel/'runtime/demo/simulation/setups').glob('*/setup-manifest.json'))) and idle(wheel),240)
            wp.get_by_role('button',name='核验并使用该配置',exact=True).wait_for(timeout=30000)
            wp.get_by_role('button',name='核验并使用该配置',exact=True).click()
            wait(wp,lambda:wp.get_by_label('冻结期权请求文件（绝对路径）',exact=True).input_value().endswith('/request.json'))
            assert status(wheel)['events']==1;mark('browser-wheel-adaptive-freeze-no-trades',wheel)
            wp.get_by_role('button',name='建立模拟运行',exact=True).click();wait(wp,lambda:bool(status(wheel)['runs']) and idle(wheel),300)
            wp.get_by_role('button',name='请求安全暂停',exact=True).wait_for(timeout=15000)
            wp.get_by_role('button',name='请求安全暂停',exact=True).click();mark('browser-safe-pause',wheel)
            wp.reload();wp.get_by_role('heading',name='LyraX 个人投资系统',exact=True).wait_for(timeout=30000)
            wp.get_by_test_id('stSidebar').get_by_text('运行状态',exact=True).click()
            setup=json.loads(next((wheel/'runtime/demo/simulation/setups').glob('*/setup-manifest.json')).read_text())
            through=setup['last_market_session']
            for segment,value in zip(('year','month','day'),through.split('-')):
                field=wp.get_by_role('spinbutton',name=segment+', 推进至交易日',exact=True)
                field.click();field.press_sequentially(str(int(value)),delay=50);field.press('Tab')
            wait(wp,lambda:all(wp.get_by_role('spinbutton',name=segment+', 推进至交易日',exact=True).get_attribute('aria-valuenow')==str(int(value)) for segment,value in zip(('year','month','day'),through.split('-'))),30)
            wp.get_by_role('button',name='后台继续模拟',exact=True).click()
            wait(wp,lambda:idle(wheel) and status(wheel)['runs'][0]['through_session']==through,240);mark('browser-wheel-resume-after-reload',wheel)
            before=status(wheel)['events']
            for name in ['账户总览','策略研究','调仓计划','运行状态']:
                wp.get_by_test_id('stSidebar').get_by_text(name,exact=True).click();wait(wp,lambda:wp.get_by_role('heading',name='LyraX 个人投资系统',exact=True).is_visible())
                assert status(wheel)['events']==before;mark('browser-page-readonly-'+name,wheel)
            wp.get_by_text('v2.0 后台备份、核验、恢复与导出',exact=True).click()
            fill(wp,'维护目标新目录',out/'browser-backup')
            wp.get_by_role('button',name='提交后台维护',exact=True).click();wait(wp,lambda:(out/'browser-backup/manifest.json').exists() and idle(wheel),300)
            assert status(wheel)['events']==before;mark('browser-backup-readonly',wheel)
            # A malformed task remains visible; read-only pages continue operating.
            bad=wheel/'runtime/demo/simulation/jobs/browser-bad';bad.mkdir();(bad/'job.json').write_text('{')
            wp.get_by_role('button',name='刷新模拟状态',exact=True).click();wait(wp,lambda:wp.get_by_text('v2.0 任务核实与恢复',exact=True).is_visible())
            wp.get_by_text('v2.0 任务核实与恢复',exact=True).click()
            wp.get_by_label('核实依据（检查进程及已提交事实后填写）',exact=True).fill('浏览器坏元数据样例，从未创建进程')
            wp.get_by_text('已核实原任务不再运行；保留全部原始凭据与账户事实',exact=True).click()
            wp.get_by_role('button',name='记录人工核实',exact=True).click()
            wait(wp,lambda:(bad/'review.json').exists())
            assert (bad/'job.json').read_text()=='{'
            mark('browser-corrupt-task-reviewed-original-preserved',wheel)
            wp.set_viewport_size({'width':390,'height':844})
            collapse=wp.get_by_test_id('stSidebarCollapseButton').get_by_role('button')
            if collapse.is_visible():collapse.click()
            wp.screenshot(path=str(out/'mobile.png'),full_page=True)
            wp.set_viewport_size({'width':1440,'height':1100});wp.screenshot(path=str(out/'desktop.png'),full_page=True)
            assert source_fingerprint()==source;browser.close()
        write_json(out/'verification.json',{'status':'PASSED','source_hash':source,'source_unchanged':True,'checks':checks,'completed_at':now_utc(),
            'data_type':'synthetic_QuantLib_model_simulation','actual_browser':'Chromium','external_conditions':'UNVERIFIED'})
    finally:
        stopped=[]
        for workspace in reversed(owned):
            try:stopped.append({'workspace':str(workspace),'result':stop_viewer(workspace)})
            except Exception as exc:stopped.append({'workspace':str(workspace),'stop_error':str(exc)})
        write_json(out/'service-cleanup.json',stopped)

if __name__=='__main__':main()
