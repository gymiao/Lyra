"""Real Chromium study-mode workflow and read-only risk/diagnostic operations."""
import argparse,hashlib,json,os,sqlite3,time
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);p.add_argument('--url',default='http://127.0.0.1:8522');p.add_argument('--engine-root',required=True);p.add_argument('--dotnet',required=True);p.add_argument('--read-only',action='store_true');p.add_argument('--output',type=Path);args=p.parse_args()
    assert args.url.startswith('http://127.0.0.1:')
    root=args.workspace.absolute();out=args.output.absolute() if args.output else root.parent
    if args.output:out.mkdir(parents=True,exist_ok=False)
    db=root/'runtime/demo/account.sqlite';checks=[]
    def state():
        c=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
        try:
            events=c.execute('SELECT event_id,content_hash FROM events ORDER BY seq').fetchall()
            exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='simulation_runs'").fetchone()
            runs=c.execute('SELECT run_id,status,through_session FROM simulation_runs').fetchall() if exists else []
            return {'events':len(events),'hash':hashlib.sha256(json.dumps(events).encode()).hexdigest(),'runs':runs}
        finally:c.close()
    def wait(page,condition,seconds=300):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            assert not page.get_by_test_id('stException').count(),page.get_by_test_id('stException').all_text_contents()
            if condition():return
            page.wait_for_timeout(500)
        raise AssertionError('Browser step did not reach expected persistent state: '+str(state()))
    def job_ids():return {p.parent.name for p in (root/'runtime/demo/simulation/jobs').glob('*/job.json')}
    def idle():return all((p.parent/'result.json').is_file() for p in (root/'runtime/demo/simulation/jobs').glob('*/job.json'))
    def record(name):checks.append({'action':name,**state()});print(name,flush=True)
    with sync_playwright() as driver:
        browser=driver.chromium.launch(executable_path='/home/mgy/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome',headless=True,
            env=dict(os.environ,LD_LIBRARY_PATH='/tmp/lyra-browser-libs/root/usr/lib/x86_64-linux-gnu',XDG_CACHE_HOME='/tmp/lyrax-browser-cache',XDG_CONFIG_HOME='/tmp/lyrax-browser-config',FONTCONFIG_FILE=os.environ.get('FONTCONFIG_FILE','/tmp/lyrax-browser-fonts/fonts.conf')))
        page=browser.new_page(viewport={'width':1440,'height':1100});page.set_default_timeout(15000);page.goto(args.url)
        page.get_by_role('heading',name='LyraX 个人投资系统',exact=True).wait_for(timeout=30000)
        if args.read_only:
            assert state()['events']==7 and state()['runs'][0][1]=='COMPLETED'
            page.get_by_test_id('stSidebar').get_by_text('运行状态',exact=True).click()
        else:
            initial=state();assert initial['events']==1 and all(r[1]=='CREATED' for r in initial['runs'])
            page.get_by_test_id('stSidebar').get_by_text('运行状态',exact=True).click()
            page.get_by_text('期权模拟配置：固定合成两月示例',exact=True).click()
            old_jobs=job_ids()
            page.get_by_role('button',name='后台冻结合成配置',exact=True).click()
            wait(page,lambda:bool(job_ids()-old_jobs) and idle(),90)
            page.get_by_role('button',name='核验并使用该配置',exact=True).wait_for(timeout=90000)
            assert state()['events']==1 and state()['runs']==initial['runs'];record('background-prepare-no-financial-events')
            page.get_by_role('button',name='核验并使用该配置',exact=True).click()
            page.get_by_label('冻结期权请求文件（绝对路径）',exact=True).wait_for()
            wait(page,lambda:page.get_by_label('冻结期权请求文件（绝对路径）',exact=True).input_value().endswith('/request.json'),30)
            for label,value in [('LEAN 源码目录（绝对路径）',args.engine_root),('dotnet 可执行文件（绝对路径）',args.dotnet)]:
                page.get_by_label(label,exact=True).fill(value);page.get_by_label(label,exact=True).press('Enter')
            page.get_by_role('button',name='建立模拟运行',exact=True).click()
            wait(page,lambda:bool(state()['runs']) and idle())
            page.wait_for_timeout(4000)
            page.get_by_label('推进至交易日',exact=True).wait_for(timeout=30000)
            record('background-start-one-deposit')
            def advance(day,pause=False):
                for segment,value in zip(('year','month','day'),day.split('-')):
                    field=page.get_by_role('spinbutton',name=segment+', 推进至交易日',exact=True)
                    field.click();field.press_sequentially(str(int(value)),delay=50);field.press('Tab')
                wait(page,lambda:all(page.get_by_role('spinbutton',name=segment+', 推进至交易日',exact=True).get_attribute('aria-valuenow')==str(int(value)) for segment,value in zip(('year','month','day'),day.split('-'))),30)
                page.get_by_role('button',name='后台继续模拟',exact=True).focus()
                page.wait_for_timeout(1500)
                old_jobs=job_ids()
                page.get_by_role('button',name='后台继续模拟',exact=True).click()
                try:wait(page,lambda:bool(job_ids()-old_jobs),20)
                except AssertionError:
                    raise AssertionError('UI did not submit a job: '+str(page.get_by_test_id('stAlert').all_text_contents()))
                if pause:
                    page.get_by_role('button',name='请求安全暂停',exact=True).click()
                    wait(page,lambda:idle() and state()['runs'][0][1]=='PAUSED')
                    assert state()['runs'][0][2]!=day,'Pause must stop before the requested final checkpoint'
                    page.wait_for_timeout(4000)
                    record('safe-pause-before-final-checkpoint')
                    return
                wait(page,lambda:bool(state()['runs']) and state()['runs'][0][2]==day and state()['runs'][0][1] in {'PAUSED','COMPLETED'})
                # Wait for the durable job receipt and parent refresh after commit.
                page.wait_for_timeout(4000)
            advance('2025-01-13',pause=True)
            advance('2025-01-13');assert state()['events']==7;record('native-market-close')
            advance('2025-01-14');assert state()['runs'][0][1]=='COMPLETED' and state()['events']==7;record('cash-settlement')
            original=state()['hash']
            advance('2025-01-14');assert state()['hash']==original;record('repeat-no-financial-events')
        original=state()['hash']
        page.get_by_role('button',name='准备脱敏诊断',exact=True).click()
        with page.expect_download() as download:
            page.get_by_role('button',name='下载脱敏诊断JSON',exact=True).click()
        diagnostic=json.loads(Path(download.value.path()).read_text());assert diagnostic['event_count']==7
        assert 'accounts' not in diagnostic and 'settings' not in diagnostic and 'read_only' in diagnostic
        record('whitelisted-diagnostic-download')
        for index,name in enumerate(['账户总览','策略研究','调仓计划','运行状态']):
            page.get_by_test_id('stSidebar').get_by_text(name,exact=True).click();page.wait_for_timeout(1500)
            assert page.get_by_role('radio',name=name,exact=True).is_checked()
            assert not page.get_by_test_id('stException').count() and state()['hash']==original
            if name=='运行状态':
                page.get_by_text('诊断状态 READY_FOR_REVIEW',exact=False).wait_for()
                assert 'UNASSIGNED_DATA_ROLE' not in page.locator('body').inner_text()
                record('option-readiness-no-unused-etf-block')
            page.locator('[data-testid=stMain]').evaluate('(e)=>e.scrollTo(0,0)')
            page.screenshot(path=str(out/f'page-{index}.png'),full_page=True);record('page-'+name)
        page.get_by_test_id('stSidebar').get_by_text('策略研究',exact=True).click()
        page.get_by_text('同资本保护Put、Collar、持股与现金',exact=True).click()
        page.get_by_role('button',name='比较同资本风险情景',exact=True).click()
        page.get_by_text('下方为上次提交的完整同资本模型；查看/切换IV不产生新计算或账户事件。',exact=True).wait_for(timeout=30000)
        assert state()['hash']==original and not page.get_by_test_id('stException').count()
        page.get_by_text('下方为上次提交的完整同资本模型；查看/切换IV不产生新计算或账户事件。',exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(out/'risk-controls.png'),full_page=True);record('risk-comparison-no-financial-events')
        page.set_viewport_size({'width':420,'height':900});page.screenshot(path=str(out/'mobile.png'),full_page=True)
        page.reload();page.get_by_role('heading',name='LyraX 个人投资系统',exact=True).wait_for(timeout=30000)
        assert state()['hash']==original and not page.get_by_test_id('stException').count();record('mobile-refresh')
        browser.close()
    proof={'status':'PASSED','source_hash':diagnostic['source_hash'],'data_type':'synthetic','checks':checks,'events':7,'source_scope':'installed final 1.95.0 wheel; verification remains scoped until all gates pass','complete_version':False,'read_only_rerun':args.read_only,'fontconfig':os.environ.get('FONTCONFIG_FILE','/tmp/lyrax-browser-fonts/fonts.conf')}
    (out/'browser-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
