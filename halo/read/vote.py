"""Majority vote over the oversight agents' reviews.

Every cell (one channel or one evidence step of one variant) takes the label that at least two of
the three agents give. A three-way split on a channel is recorded as `insufficient`. With two
reviews that disagree, a channel is `insufficient` and a step is `not_stated`. With one review the
cell takes that review's label and is marked as a single review.

Usage: python -m halo.read.vote [--reviews results/read/reviews] [--backends B1 B2 B3] [--out results/read]
"""
import argparse, json
from collections import Counter
from pathlib import Path
import yaml

CHANNELS = ('S->M', 'M->A', 'A->S', 'M->S', 'A->M')
STEPS = ('record', 'outcome', 'attribution', 'revision', 'later_use')
FALLBACK = {'channel': 'insufficient', 'step': 'not_stated'}


def vote_cell(votes, kind):
    """votes: {backend: label}. Returns (label, rule)."""
    labels = list(votes.values())
    if not labels:
        return None, 'missing'
    if len(labels) == 1:
        return labels[0], 'single review'
    label, n = Counter(labels).most_common(1)[0]
    if n == len(labels):
        return label, 'unanimous'
    if n >= 2:
        return label, f'{n} of {len(labels)}'
    return FALLBACK[kind], 'no majority'


def variant_index(cases_dir):
    """Map each variant id to its work (the case folder) and the case metadata."""
    index = {}
    for d in sorted(Path(cases_dir).iterdir()):
        f = d / 'case.yaml'
        if f.exists():
            case = yaml.safe_load(f.read_text())
            for v in case['variants']:
                index[v['id']] = {'work': d.name, 'name': case['name'], 'label': v.get('label', case['name']),
                                  'domain': case.get('domain'), 'kind': case.get('kind'),
                                  'configuration': v.get('configuration', '')}
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--reviews', default='results/read/reviews')
    ap.add_argument('--backends', nargs='*', help='review folders to use (default: all)')
    ap.add_argument('--cases', default='cases')
    ap.add_argument('--out', default='results/read')
    a = ap.parse_args()
    root = Path(a.reviews)
    backends = a.backends or sorted(p.name for p in root.iterdir() if p.is_dir())
    index = variant_index(a.cases)
    reviews = {b: {p.stem: json.loads(p.read_text()) for p in (root / b).glob('*.json')} for b in backends}
    out = {'agents': backends, 'variants': {}}
    disagreements = []
    for vid, meta in index.items():
        row = {**meta, 'reviews': [b for b in backends if vid in reviews[b]], 'channels': {}, 'steps': {}}
        for kind, names, key in (('channel', CHANNELS, 'channels'), ('step', STEPS, 'steps')):
            for name in names:
                votes = {b: reviews[b][vid][key][name]['label'] for b in backends if vid in reviews[b]}
                label, rule = vote_cell(votes, kind)
                row[key][name] = {'label': label, 'rule': rule, 'votes': votes}
                if rule not in ('unanimous', 'single review', 'missing'):
                    disagreements.append((vid, name, label, rule, {b: (reviews[b][vid][key][name]['label'],
                                          reviews[b][vid][key][name]['rationale']) for b in votes}))
        out['variants'][vid] = row
    out['complete'] = len(backends) >= 3 and all(len(r['reviews']) == len(backends) for r in out['variants'].values())
    dst = Path(a.out); dst.mkdir(parents=True, exist_ok=True)
    (dst / 'votes.json').write_text(json.dumps(out, indent=1, ensure_ascii=False) + '\n')
    lines = ['# Cells without a unanimous vote', '', f'Agents: {", ".join(backends)}', '']
    for vid, name, label, rule, why in disagreements:
        lines.append(f'## {vid} / {name}: {label} ({rule})')
        lines += [f'- **{b}** ({lab}): {txt}' for b, (lab, txt) in why.items()]
        lines.append('')
    (dst / 'disagreements.md').write_text('\n'.join(lines))
    missing = sum(len(backends) - len(r['reviews']) for r in out['variants'].values())
    print(f'{len(out["variants"])} variants, {len(backends)} agents, {missing} missing reviews, '
          f'{len(disagreements)} cells without unanimity -> {dst / "votes.json"}')


if __name__ == '__main__':
    main()
