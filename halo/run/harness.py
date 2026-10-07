"""A/B harness: run each input unmodified and with selected sites cut, then compare.

Usage: python -m halo.run.harness cases/<id> [--workers 4] [--items 1] [--samples 1] [--out runs]
"""
import argparse, json, os, queue, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import yaml
from halo.run.llm import LLM
from halo.run.judge import judge_pair

ROOT = Path(__file__).resolve().parents[2]

class Worker:
    def __init__(self, case_dir, backbone, effort, cache):
        py = case_dir / '.venv' / 'bin' / 'python'
        env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUNBUFFERED='1')
        self.p = subprocess.Popen([str(py if py.exists() else sys.executable), '-m', 'halo.run.worker', str(case_dir),
                                   backbone, effort, str(cache)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=open(cache.parent / 'worker.stderr.log', 'a'), text=True, env=env, cwd=str(ROOT))
        self.n = 0

    def call(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({'id': self.n, 'method': method, 'params': params or {}}) + '\n'); self.p.stdin.flush()
        while True:   # skip anything that is not this request's reply
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError('worker exited; see worker.stderr.log')
            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(resp, dict) and resp.get('id') == self.n:
                break
        if 'error' in resp:
            raise RuntimeError(resp['error'] + '\n' + resp.get('trace', ''))
        return resp['result']

    def close(self):
        self.p.stdin.close(); self.p.wait(timeout=60)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('case'); ap.add_argument('--config', default='run.yaml')
    ap.add_argument('--workers', type=int, default=4); ap.add_argument('--items', type=int)
    ap.add_argument('--samples', type=int); ap.add_argument('--out', default='runs'); ap.add_argument('--name')
    ap.add_argument('--judge-workers', type=int, default=6)
    a = ap.parse_args()
    case_dir = Path(a.case).resolve(); cfg = yaml.safe_load((case_dir / a.config).read_text())
    samples = a.samples or cfg.get('samples', 1)
    bb = cfg['models']['backbone']; jd = cfg['models'].get('judge')
    out = Path(a.out).resolve() / case_dir.name / (a.name or time.strftime('%Y%m%d-%H%M%S'))
    cache = out.parent / 'cache'; out.mkdir(parents=True, exist_ok=True); cache.mkdir(exist_ok=True)
    (out / 'config.json').write_text(json.dumps({'run': cfg, 'samples': samples, 'items_limit': a.items}, indent=2))
    workers = [Worker(case_dir, bb['backend'], bb.get('effort', 'medium'), cache) for _ in range(a.workers)]
    info = workers[0].call('info'); items = workers[0].call('items')[: a.items or None]
    tests = [sorted(t['cut']) for t in cfg['tests']]
    tasks = [(tuple(), it, s) for it in items for s in range(samples)] + \
            [(tuple(t), it, s) for t in tests for it in items for s in range(samples)]
    print(f'{case_dir.name}: {len(items)} items x {samples} samples, {len(tests)} tests, {len(tasks)} runs, {len(workers)} workers', flush=True)
    q, results, lock, t0 = queue.Queue(), {}, threading.Lock(), time.time()
    for t in tasks: q.put(t)
    arms = open(out / 'arms.jsonl', 'w')
    def loop(w):
        while True:
            try: cut, it, s = q.get_nowait()
            except queue.Empty: return
            key = ('+'.join(cut) or 'original', it['id'], s)
            try:
                r = w.call('run', {'item': it, 'cut': list(cut), 'sample': s}); err = None
            except Exception as e:
                r, err = None, str(e)[:2000]
            with lock:
                results[key] = r
                arms.write(json.dumps({'arm': key[0], 'item': key[1], 'sample': s, 'result': r, 'error': err}, ensure_ascii=False) + '\n'); arms.flush()
                print(f'[{time.time()-t0:6.0f}s] {"ERR " if err else "ok  "} {key[0]:20s} {key[1]} s{s}' + (f'  {err[:160]}' if err else ''), flush=True)
    ths = [threading.Thread(target=loop, args=(w,)) for w in workers]
    for th in ths: th.start()
    for th in ths: th.join()
    for w in workers: w.close()
    # comparisons: metrics per test, then all judge calls in parallel
    judge = LLM(jd['backend'], jd.get('effort', 'high'), cache) if jd else None
    report = {'case': case_dir.name, 'channels': info['channels'], 'steps': info['steps'], 'tests': []}
    rows, jobs = [], []
    for spec in cfg['tests']:
        t = sorted(spec['cut']); name = '+'.join(t)
        field, cfield = spec.get('field', 'output'), spec.get('context_field')
        rubric = spec.get('rubric', cfg.get('rubric', ''))
        row = {'cut': t, 'field': field, 'pairs': 0, 'original': 0, 'modified': 0, 'tie': 0, 'metrics': {}}
        for it in items:
            for s in range(samples):
                o, m = results.get(('original', it['id'], s)), results.get((name, it['id'], s))
                if not o or not m: continue
                for k in set(o.get('metrics', {})) | set(m.get('metrics', {})):
                    d = row['metrics'].setdefault(k, {'original': [], 'modified': []})
                    if o.get('metrics', {}).get(k) is not None: d['original'].append(o['metrics'][k])
                    if m.get('metrics', {}).get(k) is not None: d['modified'].append(m['metrics'][k])
                if judge and cfg.get('compare', 'judge') == 'judge' and field in o and field in m:
                    # the context comes from the unmodified run, so the judge sees the same situation for both
                    ctx = o.get(cfield) if cfield and o.get(cfield) else it.get('judge_context', json.dumps(it)[:4000])
                    jobs.append((row, name, field, it['id'], s, rubric, ctx, o[field], m[field]))
        for k, d in row['metrics'].items():
            row['metrics'][k] = {arm: (round(sum(x) / len(x), 4) if x else None) for arm, x in d.items()}
        rows.append(row)
    if jobs:
        print(f'judging {len(jobs)} pairs', flush=True)
        def run_judge(j):
            row, name, field, iid, s, rubric, ctx, a, b = j
            return judge_pair(judge, rubric, ctx, a, b, tag=f'{name}|{field}|{iid}|{s}')
        with ThreadPoolExecutor(max(a.workers, a.judge_workers)) as ex:
            verdicts = list(ex.map(run_judge, jobs))
        with open(out / 'judge.jsonl', 'w') as jl:
            for (row, name, field, iid, s, *_), (v, raw) in zip(jobs, verdicts):
                row['pairs'] += 1; row[v] += 1
                jl.write(json.dumps({'cut': name, 'field': field, 'item': iid, 'sample': s, 'verdict': v, 'raw': raw[:500]}) + '\n')
    report['tests'] = rows
    (out / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
    lines = [f'# {case_dir.name} run-mode report', '', f'{len(items)} items x {samples} samples; backbone {bb["backend"]} ({bb.get("effort", "medium")}); judge {jd["backend"] if jd else "-"} ({jd.get("effort", "high") if jd else "-"})', '',
             '| cut | judged output | pairs | prefer original | prefer cut | tie | metrics (original -> cut) |', '|---|---|---|---|---|---|---|']
    for r in report['tests']:
        mt = '; '.join(f'{k}: {v["original"]} -> {v["modified"]}' for k, v in sorted(r['metrics'].items()))
        lines.append(f'| {"+".join(r["cut"])} | {r["field"]} | {r["pairs"]} | {r["original"]} | {r["modified"]} | {r["tie"]} | {mt} |')
    (out / 'report.md').write_text('\n'.join(lines) + '\n'); print('\n'.join(lines))

if __name__ == '__main__':
    main()
