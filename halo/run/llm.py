"""A cached text model used inside adapted systems (backbone), as judge, or as a simulated user.

Replies are cached by backend, effort, tag, and prompt. Concurrent requests for the same key, from
threads or from other worker processes, wait on a per-key file lock, so the first reply is the one
every arm reads and arms with identical prompts stay paired.
"""
import fcntl, hashlib, json, tempfile
from pathlib import Path
from halo.backends import run_prompt, BackendError


class LLM:
    def __init__(self, backend, effort='medium', cache_dir=None, web=False, timeout=600, retries=2):
        self.backend, self.effort, self.web, self.timeout, self.retries = backend, effort, web, timeout, retries
        self.cache = Path(cache_dir) if cache_dir else None
        self._workdir = tempfile.mkdtemp(prefix='halo-llm-')
        if self.cache:
            (self.cache / '.locks').mkdir(parents=True, exist_ok=True)

    def _call(self, prompt):
        for attempt in range(self.retries + 1):
            try:
                return run_prompt(self.backend, prompt, cwd=self._workdir, effort=self.effort, web=self.web,
                                  timeout=self.timeout, ephemeral=True).strip()
            except BackendError:
                if attempt == self.retries:
                    raise

    def __call__(self, system, user, tag=''):
        prompt = ('You are the language model inside another program. Follow the system instructions and answer the '
                  'user message. Output only your answer, with no preamble and no code fence unless the instructions '
                  f'ask for one.\n\n[System instructions]\n{system}\n\n[User message]\n{user}\n')
        if not self.cache:
            return self._call(prompt)
        key = hashlib.sha256(json.dumps([self.backend, self.effort, tag, prompt]).encode()).hexdigest()
        f = self.cache / f'{key}.json'
        if f.exists():
            return json.loads(f.read_text())['text']
        with open(self.cache / '.locks' / key, 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)   # released when the file closes
            if f.exists():                      # another worker answered while we waited
                return json.loads(f.read_text())['text']
            text = self._call(prompt)
            tmp = f.with_suffix('.tmp')
            tmp.write_text(json.dumps({'backend': self.backend, 'effort': self.effort, 'tag': tag, 'text': text},
                                      ensure_ascii=False))
            tmp.replace(f)                      # readers never see a half-written reply
            return text
