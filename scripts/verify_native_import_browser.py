"""Actual Chromium upload/retry/four-page check in a restored synthetic workspace."""
import argparse,csv,hashlib,json,os,sqlite3,subprocess
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True);parser.add_argument('--csv',type=Path,required=True);parser.add_argument('--url',default='http://127.0.0.1:8506');args=parser.parse_args()
    assert urlsplit(args.url).hostname in {'127.0.0.1','localhost'}
    root=args.workspace.absolute();db=root/'runtime/demo/account.sqlite'
    assert db.is_file() and all(row['evidence_type']=='test' for row in csv.DictReader(args.csv.open()))
    def facts():
        connection=sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)
        try:
            rows=connection.execute('SELECT seq,event_id,content_hash,effective_at,recorded_at,payload FROM events ORDER BY seq').fetchall()
            assert len(rows)==5 and all(json.loads(r[-1])['evidence_type']=='test' for r in rows)
            return hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()
        finally:connection.close()
    python='/mnt/c/quant/project/lyra/.conda/v19-clean/bin/python'
    def fingerprint():return subprocess.check_output([python,'-c','from personal_quant.strategies.archive import source_fingerprint;print(source_fingerprint())'],text=True,env=dict(os.environ,MPLCONFIGDIR='/tmp/lyrax-mpl',PYTHONDONTWRITEBYTECODE='1')).strip()
    original=facts();source=fingerprint();checks=[]
    with sync_playwright() as driver:
        browser=driver.chromium.launch(executable_path='/home/mgy/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome',headless=True,
            env=dict(os.environ,LD_LIBRARY_PATH='/tmp/lyra-browser-libs/root/usr/lib/x86_64-linux-gnu',XDG_CACHE_HOME='/tmp/lyrax-browser-cache',XDG_CONFIG_HOME='/tmp/lyrax-browser-config'))
        page=browser.new_page(viewport=dict(width=1440,height=1100));page.goto(args.url)
        page.get_by_role('heading',name='LyraX 个人投资系统',exact=True).wait_for(timeout=30000)
        assert page.get_by_test_id('stException').count()==0
        page.get_by_label('账户 ID',exact=True).fill('sample');page.get_by_label('账户 ID',exact=True).press('Enter')
        page.get_by_role('button',name='更新账户报告',exact=True).click()
        page.get_by_test_id('stMetricValue').first.wait_for(timeout=30000)
        assert Decimal(page.get_by_test_id('stMetricValue').first.inner_text().replace(',',''))==100386
        uploader=page.get_by_test_id('stFileUploader').filter(has_text='标准事件 CSV（成交/资金/公司行动）')
        uploader.locator('input[type=file]').set_input_files(str(args.csv.absolute()))
        for attempt in [1,2]:
            page.get_by_role('button',name='预检导入',exact=True).click()
            page.get_by_role('button',name='提交已预检的账单',exact=True).click()
            page.get_by_text('账本及关联计划已同步更新，报告已重建；请核对实际成交与独立快照。',exact=True).wait_for(timeout=30000)
            assert page.get_by_test_id('stException').count()==0 and facts()==original
            assert Decimal(page.get_by_test_id('stMetricValue').first.inner_text().replace(',',''))==100386
            checks.append(dict(action='upload-preview-submit',attempt=attempt,financial_events=5,cash='100386'))
        for index,name in enumerate(['策略研究','调仓计划','运行状态','账户总览']):
            page.get_by_test_id('stSidebar').get_by_text(name,exact=True).click()
            assert page.get_by_role('radio',name=name,exact=True).is_checked()
            page.wait_for_timeout(1200)
            assert page.get_by_test_id('stException').count()==0 and facts()==original
            page.screenshot(path=str(root/f'browser-page-{index}.png'),full_page=True)
            checks.append(dict(action='page',name=name,financial_events=5))
        page.reload();page.get_by_role('heading',name='LyraX 个人投资系统',exact=True).wait_for(timeout=30000)
        assert page.get_by_test_id('stException').count()==0 and facts()==original
        checks.append(dict(action='refresh',financial_events=5));browser.close()
    assert fingerprint()==source
    proof=dict(status='PASSED',source_fingerprint=source,data_type='synthetic_native_engine_facts',checks=checks,
        financial_hash=original,financial_events=5,final_cash='100386',no_user_account_writes=True,tool_environment='read-only agent-reach Python/Playwright; app runs v19-clean Conda')
    (root/'browser-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2));print(json.dumps(dict(status='PASSED',checks=len(checks),verification=str(root/'browser-verification.json'))))


if __name__=='__main__':main()
