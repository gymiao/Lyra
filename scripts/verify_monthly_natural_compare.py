"""Run the public natural-expiry comparison CLI on a frozen synthetic path."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from personal_quant.options.monthly_report import load_monthly_report
from personal_quant.strategies.archive import source_fingerprint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--engine-root', type=Path, required=True)
    parser.add_argument('--dotnet', type=Path, required=True)
    args = parser.parse_args()
    root = args.workspace.absolute()
    root.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    cases = json.loads((project / 'examples/options/monthly-natural-fixtures.json').read_text())
    request = next(case['request'] for case in cases if case['name'] == '1-protective_put')
    (root / 'request.json').write_text(json.dumps(request))
    (root / 'demo.toml').write_bytes((project / 'configs/demo.toml').read_bytes())
    fingerprint = source_fingerprint()
    command = [sys.executable, '-m', 'personal_quant.cli', '--config', 'demo.toml',
               'options', '--action', 'monthly-compare', '--file', 'request.json',
               '--engine-root', str(args.engine_root.absolute()), '--dotnet', str(args.dotnet.absolute()),
               '--destination', str(root / 'comparison'), '--capital', '100000',
               '--fee-per-contract', '2', '--stock-commission-bps', '2']
    result = subprocess.run(command, cwd=root, capture_output=True, text=True,
                            env=dict(os.environ, PYTHONPATH=str(project / 'src')))
    (root / 'stdout.json').write_text(result.stdout)
    (root / 'stderr.log').write_text(result.stderr)
    assert result.returncode == 0, result.stderr
    report = load_monthly_report(root / 'comparison')
    assert report == json.loads(result.stdout)
    assert report['metrics']['protective_put']['net_trading_pnl'] == -1246
    assert abs(report['metrics']['stock']['net_trading_pnl'] + 2011.6) < .000001
    assert report['metrics']['cash']['total_return'] == 0
    assert report['final_lifecycle'] == 'natural_expiry'
    assert fingerprint == source_fingerprint() == report['source_fingerprint']
    proof = dict(status='PASSED', source_fingerprint=fingerprint,
                 data_type='synthetic_natural_expiry', checks=1,
                 command=command, exit_code=result.returncode,
                 no_user_account_writes=True, report=str(root / 'comparison/report.md'))
    (root / 'verification.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2))
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
