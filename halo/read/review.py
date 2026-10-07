"""Run one oversight agent on one variant of a case and save a validated review."""
import json, re, sys, time
from pathlib import Path
import jsonschema, yaml
from halo.backends import run_prompt, BackendError

PKG = Path(__file__).resolve().parent
ROOT = PKG.parents[1]
PROTOCOL = (PKG / 'protocol' / 'PROTOCOL.md').read_text()
SCHEMA = json.loads((PKG / 'schema.json').read_text())

def load_case(case_dir):
    return yaml.safe_load((Path(case_dir) / 'case.yaml').read_text())

def build_prompt(case, variant, code_dir):
    src = '\n'.join(f'- {s["url"]} ({s.get("kind","paper")}, version {s.get("version","")})' for s in case.get('sources', []))
    code = (f'The code repository {case["code"]["repo"]} at commit {case["code"]["commit"]} is checked out in your '
            f'working directory ({code_dir}). Read it alongside the text; it is read-only.') if code_dir else \
           'This work has no code repository for you to read; judge from the text sources alone.'
    return f"""You are an oversight agent in HALO read mode. Follow the protocol below exactly.

{PROTOCOL}

## Your assignment
- Work: {case['name']} (case id `{case['id']}`, domain {case['domain']}, kind {case['kind']}).
- Configuration to judge (variant id `{variant['id']}`): {variant['configuration']}
- Primary text sources (fetch and read them; use the listed version):
{src}
- {code}

Work independently. Do not modify any file. When you are done, reply with ONLY the JSON object
(no prose, no code fence) that validates against this JSON Schema, with "id" set to "{variant['id']}":

{json.dumps(SCHEMA)}
"""

def relativize(obj, root=ROOT):
    """Replace local absolute paths with repository-relative ones, so saved reviews carry no machine paths."""
    if isinstance(obj, dict):
        return {k: relativize(v, root) for k, v in obj.items()}
    if isinstance(obj, list):
        return [relativize(v, root) for v in obj]
    if isinstance(obj, str):
        return obj.replace(str(root) + '/', '').replace(str(root), '.')
    return obj

def extract_json(text):
    t = text.strip()
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', t)
    i, j = t.find('{'), t.rfind('}')
    if i < 0 or j < 0:
        raise ValueError('no JSON object in reply')
    return json.loads(t[i:j + 1])

def review(case_dir, variant_id, backend, out_dir, effort='max', retries=1, timeout=1800):
    case_dir = Path(case_dir); case = load_case(case_dir)
    variant = next(v for v in case['variants'] if v['id'] == variant_id)
    code_dir = ROOT / '.upstream' / case['id'] if case.get('code', {}).get('commit') else None
    cwd = code_dir if code_dir and code_dir.exists() else case_dir
    prompt = build_prompt(case, variant, code_dir if cwd == code_dir else None)
    out = Path(out_dir) / backend.replace(':', '_') / f'{variant_id}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return json.loads(out.read_text())
    last = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            text = run_prompt(backend, prompt, cwd=cwd, effort=effort, read_dirs=[case_dir], timeout=timeout)
            obj = relativize(extract_json(text))
            obj['id'] = variant_id
            jsonschema.validate(obj, SCHEMA)
            obj['_meta'] = {'backend': backend, 'effort': effort, 'seconds': round(time.time() - t0),
                            'code_commit': case.get('code', {}).get('commit')}
            out.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')
            return obj
        except (BackendError, ValueError, jsonschema.ValidationError, json.JSONDecodeError) as e:
            last = e
            (out.parent / f'{variant_id}.error.txt').write_text(f'attempt {attempt}: {type(e).__name__}: {str(e)[:2000]}\n')
    raise RuntimeError(f'{backend} {variant_id}: {last}')

if __name__ == '__main__':
    case_dir, variant_id, backend, out_dir = sys.argv[1:5]
    print(json.dumps(review(case_dir, variant_id, backend, out_dir)['channels'], indent=1))
