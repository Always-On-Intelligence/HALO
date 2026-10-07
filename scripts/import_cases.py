"""One-time import: build cases/<id>/case.yaml for the 40 works reviewed in the survey.

Usage: python3 scripts/import_cases.py <path-to-survey-records.json>
"""
import json, re, sys, unicodedata
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
records = json.load(open(sys.argv[1]))['records']
clones = json.load(open(ROOT / 'cases' / 'upstream_manifest.json'))
by_repo = {v['url'].lower(): (k, v) for k, v in clones.items() if 'url' in v}

def slug(name):
    s = unicodedata.normalize('NFKD', name.replace('²', '2')).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def q(s):  # YAML double-quoted scalar
    return '"' + str(s).replace('\\', '\\\\').replace('"', '\\"') + '"'

cases = {}
for r in records:
    code = (r.get('source_links') or {}).get('code')
    cid = by_repo.get(code.lower().rstrip('/'), (None,))[0] if code else None
    cid = cid or slug(r['name'].split('/')[0])
    c = cases.setdefault(cid, {'name': r['name'].split('/')[0].strip(), 'domain': r['group'].lower().replace('embodied', 'physical'),
                               'kind': 'product' if r.get('product') else 'research', 'variants': [], 'sources': [],
                               'report': (r.get('source_links') or {}).get('report'), 'code': code})
    c['variants'].append({'id': r['id'], 'label': r['name'], 'configuration': r['configuration']})
    for s in r.get('sources', []):
        u = s.get('version_url') or s.get('url')
        if u and all(u != x['url'] for x in c['sources']):
            c['sources'].append({'url': u, 'kind': s.get('source_kind', ''), 'version': s.get('version', ''), 'sha256': s.get('text_sha256', '')})

for cid, c in cases.items():
    d = ROOT / 'cases' / cid
    d.mkdir(parents=True, exist_ok=True)
    lines = [f'id: {cid}', f'name: {q(c["name"])}', f'domain: {c["domain"]}', f'kind: {c["kind"]}']
    if c['report']:
        lines.append(f'report: {c["report"]}')
    lines.append('sources:')
    for s in c['sources']:
        lines += [f'  - url: {s["url"]}', f'    kind: {s["kind"] or "paper"}', f'    version: {q(s["version"])}'] + ([f'    sha256: {s["sha256"]}'] if s['sha256'] else [])
    if c['code'] and cid in clones and 'commit' in clones[cid]:
        m = clones[cid]
        lines += ['code:', f'  repo: {m["url"]}', f'  commit: {m["commit"]}'] + ([f'  sparse: [{", ".join(m["sparse"])}]'] if m.get('sparse') else [])
    elif c['code']:
        lines += ['code:', f'  repo: {c["code"]}', '  commit: null  # not cloned']
    lines.append('variants:')
    for v in c['variants']:
        lines += [f'  - id: {v["id"]}', f'    label: {q(v["label"])}', f'    configuration: {q(v["configuration"])}']
    lines.append(f'modes: [read{", run" if c["code"] and cid in clones else ""}]')
    (d / 'case.yaml').write_text('\n'.join(lines) + '\n')
print(len(cases), 'cases;', sum(1 for c in cases if c in clones), 'with cloned code;', sum(len(c['variants']) for c in cases.values()), 'variants')
