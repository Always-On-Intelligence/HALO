"""Shallow-clone every reviewed work that has public code into .upstream/<id>/ and record the commit."""
import json, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
UP = ROOT / '.upstream'
REPOS = [  # id, owner/repo, pinned commit (None = default branch head), sparse paths
    ('vinci', 'OpenGVLab/vinci', None, None),
    ('vinci2', 'SitongGong/EgoMemo', None, None),
    ('visionclaw', 'Intent-Lab/VisionClaw', None, None),
    ('contextagent', 'openaiotlab/ContextAgent', None, None),
    ('aiget', 'Synteraction-Lab/AiGet', '92b17f8', None),
    ('m3-agent', 'ByteDance-Seed/M3-Agent', None, None),
    ('lightmem-ego', 'zjunlp/LightMem-Ego', None, None),
    ('egocentric-copilot', 'YoungSeng/Egocentric-Co-Pilot', None, None),
    ('ipi-agent', 'lijinzhao30/IPI', None, None),
    ('omi', 'BasedHardware/omi', None, ['backend']),
    ('assistantx', 'AssistantX-Agent/AssistantX', None, None),
    ('abot-claw', 'amap-cvlab/ABot-Claw', None, None),
    ('pask', 'xzf-thu/Pask', None, None),
    ('user-as-code', '19PINE-AI/user-as-code', None, None),
    ('ouroboros', 'razzant/ouroboros', None, None),
    ('visualclaw', 'UCSC-VLAA/VisualClaw', None, None),
    ('proactive-agent', 'thunlp/ProactiveAgent', None, None),
    ('pahf', 'facebookresearch/PAHF', None, None),
    ('proact', 'AgentACE-AI/ProAct', None, None),
    ('properassistant', 'jiho283/ProPerSim', None, None),
    ('eaia', 'langchain-ai/executive-ai-assistant', '758db71', None),
]
def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
manifest = {}
for cid, repo, pin, sparse in REPOS:
    dst = UP / cid
    url = f'https://github.com/{repo}.git'
    t0 = time.time()
    if not dst.exists():
        if pin:
            dst.mkdir(parents=True)
            run(['git', 'init', '-q'], dst); run(['git', 'remote', 'add', 'origin', url], dst)
            full = run(['git', 'ls-remote', url]).stdout  # resolve short sha via a full fetch of history if needed
            r = run(['git', 'fetch', '-q', '--filter=blob:none', 'origin'], dst)
            r = run(['git', 'checkout', '-q', pin], dst)
        elif sparse:
            r = run(['git', 'clone', '-q', '--depth', '1', '--filter=blob:none', '--sparse', url, str(dst)])
            if r.returncode == 0:
                run(['git', 'sparse-checkout', 'set'] + sparse, dst)
        else:
            r = run(['git', 'clone', '-q', '--depth', '1', url, str(dst)])
        if r.returncode != 0:
            manifest[cid] = {'repo': repo, 'error': r.stderr.strip()[-300:]}
            print(cid, 'ERROR', r.stderr.strip()[-200:], flush=True); continue
    sha = run(['git', 'rev-parse', 'HEAD'], dst).stdout.strip()
    size = run(['du', '-sh', str(dst)]).stdout.split('\t')[0]
    manifest[cid] = {'repo': repo, 'url': f'https://github.com/{repo}', 'commit': sha, 'pinned': bool(pin), 'sparse': sparse, 'size': size}
    print(f'{cid:20s} {sha[:10]} {size:>6s} {time.time()-t0:5.1f}s', flush=True)
(ROOT / 'cases').mkdir(exist_ok=True)
(ROOT / 'cases' / 'upstream_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('done', len([m for m in manifest.values() if 'commit' in m]), 'of', len(REPOS))
