"""Copy a finished run into results/run/<case>/ (outputs, verdicts, and summary; never the cache).

Usage: python scripts/collect_run_results.py runs/<case>/<name> [...]
"""
import shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for arg in sys.argv[1:]:
    src = Path(arg).resolve()
    dst = ROOT / 'results' / 'run' / src.parent.name
    dst.mkdir(parents=True, exist_ok=True)
    for name in ('config.json', 'arms.jsonl', 'judge.jsonl', 'report.json', 'report.md'):
        if (src / name).exists():
            shutil.copy2(src / name, dst / name)
    (dst / 'RUN.txt').write_text(f'run: {src.parent.name}/{src.name}\n')
    print(f'{src} -> {dst}')
