"""Review every variant of every case with one backend, in parallel. Skips reviews that already exist."""
import argparse, concurrent.futures as cf, json, sys, threading, time
from pathlib import Path
from halo.read.review import review, load_case

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--backend', required=True)
    ap.add_argument('--cases', default='cases')
    ap.add_argument('--out', default='results/read/reviews')
    ap.add_argument('--workers', type=int, default=5)
    ap.add_argument('--only', nargs='*')
    a = ap.parse_args()
    jobs = []
    for d in sorted(Path(a.cases).iterdir()):
        if (d / 'case.yaml').exists() and (not a.only or d.name in a.only):
            jobs += [(d, v['id']) for v in load_case(d)['variants']]
    print(f'{len(jobs)} variants with {a.backend}', flush=True)
    t0 = time.time()
    stop = threading.Event()   # set when the account hits its usage limit: later jobs are skipped, not failed

    def guarded(d, vid):
        if stop.is_set():
            raise RuntimeError('skipped after a usage-limit error; rerun later')
        try:
            return review(d, vid, a.backend, a.out)
        except Exception as e:
            if 'limit' in str(e).lower() and ('session' in str(e).lower() or 'usage' in str(e).lower()):
                stop.set()
            raise

    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(guarded, d, vid): vid for d, vid in jobs}
        for f in cf.as_completed(futs):
            vid = futs[f]
            try:
                r = f.result(); lab = ''.join({'reported': 'R', 'absent': 'A', 'insufficient': '-'}[r['channels'][c]['label']] for c in ('S->M', 'M->A', 'A->S', 'M->S', 'A->M'))
                st = ''.join('1' if r['steps'][s]['label'] == 'stated' else '0' for s in ('record', 'outcome', 'attribution', 'revision', 'later_use'))
                print(f'[{time.time()-t0:6.0f}s] ok   {vid:40s} {lab} {st}', flush=True)
            except Exception as e:
                print(f'[{time.time()-t0:6.0f}s] FAIL {vid:40s} {str(e)[:200]}', flush=True)

if __name__ == '__main__':
    main()
