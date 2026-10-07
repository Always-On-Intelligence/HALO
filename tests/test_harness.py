import json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_toy_case_runs_offline(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    p = subprocess.run([sys.executable, '-m', 'halo.run.harness', str(ROOT / 'tests' / 'toycase'), '--workers', '2',
                        '--out', str(tmp_path), '--name', 't'], capture_output=True, text=True, env=env, cwd=ROOT)
    assert p.returncode == 0, p.stderr
    report = json.loads((tmp_path / 'toycase' / 't' / 'report.json').read_text())
    rows = {'+'.join(r['cut']): r for r in report['tests']}
    assert rows['M->A']['pairs'] == 2 and rows['A->M']['pairs'] == 2
    # A->M keeps fewer notes than the original run
    assert rows['A->M']['metrics']['notes']['modified'] < rows['A->M']['metrics']['notes']['original']
    arms = [json.loads(l) for l in open(tmp_path / 'toycase' / 't' / 'arms.jsonl')]
    assert all(a['error'] is None for a in arms) and len(arms) == 6
