import os, shutil, subprocess, tempfile
from pathlib import Path

class BackendError(RuntimeError):
    pass

EFFORT = {'codex': {'max': 'ultra'}, 'claude': {}}

def _bin(kind):
    env = os.environ.get('HALO_CODEX_BIN' if kind == 'codex' else 'HALO_CLAUDE_BIN')
    path = env or shutil.which(kind)
    if not path:
        raise BackendError(f'{kind} CLI not found; set HALO_{kind.upper()}_BIN')
    return path

def _clean_env():
    keep = ('HOME', 'USER', 'LANG', 'PATH', 'TMPDIR', 'SHELL', 'LOGNAME')
    return {k: v for k, v in os.environ.items() if k in keep or k.startswith('CODEX_')}

def _mock(model, prompt):
    """Offline backend for tests. `mock:echo` returns the prompt's last line, `mock:A` answers A."""
    if model == 'echo':
        return prompt.strip().splitlines()[-1]
    return model

def _run(cmd, prompt, timeout, **kw):
    try:
        return subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, env=_clean_env(), **kw)
    except subprocess.TimeoutExpired:
        raise BackendError(f'no reply within {timeout}s')

def run_prompt(backend, prompt, cwd, effort='max', web=True, timeout=7200, read_dirs=(), ephemeral=False):
    """Run one prompt headlessly. backend = 'codex:<model>' or 'claude:<model>'.

    The model runs without the user's own configuration, memories, or rules, so that
    nothing from the local account enters a review or a run."""
    kind, model = backend.split(':', 1)
    cwd = str(Path(cwd).resolve())
    if kind == 'mock':
        return _mock(model, prompt)
    if kind == 'codex':
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'final.txt'
            cmd = [_bin('codex')] + (['--search'] if web else []) + [
                'exec', '-m', model, '-c', f'model_reasoning_effort="{EFFORT["codex"].get(effort, effort)}"',
                '-s', 'read-only', '--skip-git-repo-check', '--ignore-user-config', '--ignore-rules'] + \
                (['--ephemeral'] if ephemeral else []) + ['-C', cwd, '-o', str(out), '-']
            p = _run(cmd, prompt, timeout)
            if p.returncode != 0 or not out.exists():
                raise BackendError(f'codex exit {p.returncode}: {p.stderr[-400:]}')
            return out.read_text()
    if kind == 'claude':
        cmd = [_bin('claude'), '-p', '--model', model, '--effort', effort, '--output-format', 'text',
               '--setting-sources', 'project', '--strict-mcp-config', '--disable-slash-commands',
               '--permission-mode', 'dontAsk', '--allowedTools', 'Read,Grep,Glob' + (',WebFetch,WebSearch' if web else '')] + \
              (['--no-session-persistence'] if ephemeral else [])
        for d in read_dirs:
            cmd += ['--add-dir', str(d)]
        p = _run(cmd, prompt, timeout, cwd=cwd)
        if p.returncode != 0:
            raise BackendError(f'claude exit {p.returncode}: {(p.stderr or p.stdout)[-400:]}')
        return p.stdout
    raise BackendError(f'unknown backend {backend}')
