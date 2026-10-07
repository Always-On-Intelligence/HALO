"""Per-work counts and the channel and evidence table, computed from the votes.

A work is one case folder. When a work has several variants (VisualClaw has one per Arena
backend), a cell counts as reported or stated if any variant has it, and as absent only if every
variant is absent. The counts are the ones Section 7.1 of the survey reports.

Usage: python -m halo.read.tables [--votes results/read/votes.json] [--out results/read]
"""
import argparse, csv, json
from collections import defaultdict
from pathlib import Path
from halo.read.vote import CHANNELS, STEPS

DOMAINS = ('wearable', 'physical', 'digital')
MARK = {'reported': '●', 'absent': '✕', 'insufficient': '–', 'stated': '■', 'not_stated': '·', None: '?'}


def merge(labels, kind):
    if kind == 'channel':
        if 'reported' in labels:
            return 'reported'
        return 'absent' if labels and all(x == 'absent' for x in labels) else 'insufficient'
    return 'stated' if 'stated' in labels else 'not_stated'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--votes', default='results/read/votes.json')
    ap.add_argument('--out', default='results/read')
    a = ap.parse_args()
    votes = json.loads(Path(a.votes).read_text())
    works = defaultdict(list)
    for vid, row in votes['variants'].items():
        works[row['work']].append((vid, row))
    per_work = {}
    for w, rows in works.items():
        per_work[w] = {
            'name': rows[0][1]['name'], 'domain': rows[0][1]['domain'], 'kind': rows[0][1]['kind'],
            'channels': {c: merge([r['channels'][c]['label'] for _, r in rows], 'channel') for c in CHANNELS},
            'steps': {s: merge([r['steps'][s]['label'] for _, r in rows], 'step') for s in STEPS},
        }
    n = len(per_work)
    counts = {
        'works': n,
        'channels': {c: {lab: sum(w['channels'][c] == lab for w in per_work.values())
                         for lab in ('reported', 'insufficient', 'absent')} for c in CHANNELS},
        'steps': {s: sum(w['steps'][s] == 'stated' for w in per_work.values()) for s in STEPS},
        'A->M with outcome': sum(w['channels']['A->M'] == 'reported' and w['steps']['outcome'] == 'stated'
                                 for w in per_work.values()),
        'agents': votes['agents'], 'complete': votes['complete'],
    }
    dst = Path(a.out); dst.mkdir(parents=True, exist_ok=True)
    (dst / 'counts.json').write_text(json.dumps(counts, indent=1) + '\n')

    order = sorted(votes['variants'].items(),
                   key=lambda kv: (DOMAINS.index(kv[1]['domain']) if kv[1]['domain'] in DOMAINS else 9,
                                   kv[1]['kind'] != 'research', kv[0]))
    header = ['variant', 'system', 'domain', 'kind'] + list(CHANNELS) + ['Rec.', 'Out.', 'Attr.', 'Rev.', 'Use.']
    with open(dst / 'table.csv', 'w', newline='') as f:
        wr = csv.writer(f); wr.writerow(header)
        for vid, r in order:
            wr.writerow([vid, r['label'], r['domain'], r['kind']] + [r['channels'][c]['label'] for c in CHANNELS]
                        + [r['steps'][s]['label'] for s in STEPS])
    md = ['# Read-mode table', '',
          f'Agents: {", ".join(votes["agents"])}; votes complete: {votes["complete"]}. '
          '● reported, – insufficient, ✕ absent; ■ stated, · not stated.', '',
          '| System | Domain | ' + ' | '.join(header[4:]) + ' |', '|' + '---|' * (len(header) - 2)]
    for vid, r in order:
        md.append(f'| {r["label"]} | {r["domain"]} | ' + ' | '.join(MARK[r['channels'][c]['label']] for c in CHANNELS)
                  + ' | ' + ' | '.join(MARK[r['steps'][s]['label']] for s in STEPS) + ' |')
    md += ['', f'## Counts over {n} works', '']
    for c in CHANNELS:
        x = counts['channels'][c]
        md.append(f'- {c}: {x["reported"]} reported, {x["insufficient"]} insufficient, {x["absent"]} absent')
    md.append('- Evidence steps: ' + ', '.join(f'{s} {counts["steps"][s]}' for s in STEPS))
    md.append(f'- A->M reported and outcome stated: {counts["A->M with outcome"]}')
    (dst / 'table.md').write_text('\n'.join(md) + '\n')
    print(json.dumps(counts, indent=1))


if __name__ == '__main__':
    main()
