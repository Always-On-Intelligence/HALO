"""HALO run-mode adapter for Ouroboros (razzant/ouroboros at commit 4b37f96, release 7.6.0).

Configuration (case.yaml): "Hope live deployment with reviewed experience-driven core evolution", the
paper's advanced mode. Owner settings for the run (environment, read by upstream config getters):
runtime mode advanced, post-task evolution on with cadence every_n:2, review enforcement blocking,
a two-row packet triad panel, OUROBOROS_REVIEW_MAX_CYCLES=2 (shipped default), OUROBOROS_MAX_ROUNDS=12
(shipped default: no limit).

One item is one owner talking to Ouroboros in its Main room about four of the owner's repositories
(inputs/items.yaml). The owner's organization keeps its default contributing guide in its organization-level
`.github` repository (~/src/.github/CONTRIBUTING.md); the repositories have no guide of their own, and
`make check` in each enforces its section of the organization guide. The adapter simulates `make check` from
declarative rules (no command is ever executed).
  learning  L1, L2: a task turn in the owner's repository, then the upstream post-task stages
            (memory_fallback_draft, scratchpad_consolidation, reflection with the Pattern Register,
            memory actions, improvement backlog, post-task evolution promotion);
  tick      the supervisor applies the durable promotion request (apply_pending_request) and enqueues
            the evolution cycle (enqueue_evolution_task_if_needed, whose admission is captured here);
  evolution the cycle task edits a sandbox copy of Ouroboros's own repository (prompts/SYSTEM.md and the
            release carriers; the reference books are there to read; code is out of reach in this run),
            may call plan_task (upstream plan review on the triad rows), and commits through the upstream
            gate: release sync, _preflight_check, the triad packet, and _dispatch_unified_review in blocking
            mode; a reviewed commit lands in the sandbox copy, which later contexts read;
  test      T1, T2: task turns in two other repositories whose rules differ; no post-task stages.

Executed upstream code (core/, unchanged): Memory, memory_view (story and room), context section
builders, post_task_synthesis stages, reflection, improvement_backlog, post_task_evolution,
supervisor.state / queue / evolution_lifecycle / message_bus.log_chat, tools.review (preflight, packet
templates, verdict), triad_review parser, release_sync, commit_admission, reviewer_slot_config,
tools.plan_review (plan_task and its engine), the tool schemas (tools.core, tools.shell, tools.git,
tools.control, tools.plan_review) and the prompt files.
Ported (reproduced here, see README): the tool loop (round limit and the [ROUND_LIMIT] forced final of
loop.py/loop_round_limits.py), the context composition order of context._capture_context_core and
context_fit._system_blocks, a short runtime block, the four workspace tools and the three evolution
tools over sandbox files, the staged diff (difflib instead of git), the reviewer fan-out transports
(review substrate, for the commit triad and for plan_task) and the landing (file copy instead of git
commit + restart).
Replaced: ouroboros.llm.LLMClient -> HALO backbone (self.llm); the reviewer rows of the commit triad and of
plan_task -> a second HALO LLM role ("reviewer|" tag prefix) with the same backend and cache. Time is frozen per step and
uuid4 is seeded, so rendered memory is identical across arms and the cache keeps arms paired.

Cut sites (core file:line is where the receiver reads the flow; the adapter method cuts it there):
  S->M   supervisor/message_bus.py:1370 log_chat for the owner's message (direction "in") is not written,
         so the room's open conversation (ouroboros/memory_view.py:524 _lanes) never holds the owner's
         words.                                                                    -> Adapter._owner_says
  M->A   the memory blocks of the action context are withheld: story/room (memory_view.py:826,920),
         identity+WORLD and scratchpad (context.py:758), knowledge index + Pattern Register
         (context.py:593), execution reflections (context.py:866), backlog digest (improvement_backlog.py
         :456) - assembled as in context.py:1059-1290 / context_fit.py:352.       -> Adapter._context
  A->M   Ouroboros's reply row (log_chat direction "out"), the reflection writer
         reflection.py:874 append_reflection_routed (task_reflections.jsonl + Pattern Register) and the
         memory actions post_task_synthesis.py:301 are not written. The backlog and the promotion
         request still run (they are the revision path).                           -> Adapter._post_task
  record      reflection input (post_task_synthesis.py:696 _run_reflection -> reflection.py:527
         generate_reflection) loses the agent's own calls/arguments and the sealed final answer; results
         stay.                                                                     -> Adapter._evidence
  outcome     the same input loses every tool result and status (incl. the `make check` verdicts), so
         the trigger (reflection.py:181) and the review see a clean run.             -> Adapter._evidence
  attribution results arrive one task late: L1's review gets no results, L2's gets L1's results attached
         to L2's own calls.                                                         -> Adapter._evidence
  revision    the reviewed commit is not copied into the sandbox repository the runtime loads
         (context reads prompts/SYSTEM.md at context.py:1072); covers later_use.   -> Adapter._commit_reviewed
"""
import contextlib, copy, difflib, fnmatch, hashlib, json, os, random, re, shutil, sys, tempfile, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import yaml
from halo.run.adapter import BaseAdapter

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core'                       # vendored upstream code, see core/SOURCE.md
MODEL_ID = 'openai/gpt-6-astra'            # model id the upstream settings name; every call goes to the backbone
OWNER_CHAT = 1
HOME = '/home/owner'                       # virtual home shown to the model; repositories live in ~/src
ORG_REPO = '.github'                       # the organization's community-health repository, checked out at ~/src/.github
ORG_README = ('# .github\n\nDefault community health files for the {org} organization. GitHub applies each file here '
              'to every {org} repository that does not have its own.\n')
REVIEW_ROWS = ('triad_a', 'triad_b')
OWNER_SETTINGS = {
    'OUROBOROS_RUNTIME_MODE': 'advanced',
    'OUROBOROS_POST_TASK_EVOLUTION': 'true',
    'OUROBOROS_POST_TASK_EVOLUTION_CADENCE': 'every_n:2',
    'OUROBOROS_REVIEW_ENFORCEMENT': 'blocking',
    'OUROBOROS_REVIEW_MAX_CYCLES': '2',
    'OUROBOROS_MAX_ROUNDS': '12',
    'OUROBOROS_TASK_REVIEW_MODE': 'off',
    'OUROBOROS_MODEL': MODEL_ID,
    'OUROBOROS_MODEL_LIGHT': MODEL_ID,
    'OUROBOROS_REVIEWER_SLOTS': json.dumps({
        'triad': [{'slot_id': s, 'route': {'kind': 'api_chat', 'target_id': MODEL_ID}, 'delivery': 'packet'}
                  for s in REVIEW_ROWS],
        'scope': [{'slot_id': 'scope_a', 'route': {'kind': 'api_chat', 'target_id': MODEL_ID}}]}),
}
# Files of Ouroboros's own repository that the run copies into each run's sandbox. The evolution may
# change the first group (application prompt + release carriers); BIBLE.md is protected in advanced mode.
EDITABLE = ('prompts/SYSTEM.md', 'VERSION', 'README.md', 'docs/ARCHITECTURE.md', 'pyproject.toml', 'uv.lock',
            'web/package.json', 'web/package-lock.json', 'web/modules/api_types.js', 'site/install/index.html',
            'docs/install/index.html')   # the prompt and every release carrier that release_sync writes
PROTECTED = ('BIBLE.md',)
# Read-only reference files of the sandbox: the reviewer checklists, the two reference books (entrypoints and
# chapters), which the context names but does not inline, and DESIGN.md (governance of web/ changes).
READ_ONLY_EXTRA = ('docs/CHECKLISTS.md', 'docs/CHECKLISTS_ARCHIVE.md', 'docs/DEVELOPMENT.md', 'docs/DESIGN.md',
                   *sorted(str(p.relative_to(CORE)) for d in ('docs/architecture', 'docs/development')
                           for p in (CORE / d).glob('*.md')))
OUTCOME_KEYS = ('result', 'status', 'is_error', 'exit_code', 'tool_result_code')
DOCS_NOTE = ('## Reference books\n\nThe Architecture and Development books (docs/ARCHITECTURE.md and '
             'docs/DEVELOPMENT.md with their chapters under docs/architecture/ and docs/development/), README.md and '
             'docs/CHECKLISTS.md are not inlined in this run; evolution cycles read them on demand in system_repo.')
# Upstream ouroboros/loop_round_limits.py:484-489 (not vendored: the loop is ported), the forced-final prompt of the
# round-limit rail, entered when round_idx > MAX_ROUNDS (loop.py:527).
ROUND_LIMIT = ('[ROUND_LIMIT] ⚠️ Task exceeded MAX_ROUNDS ({n}). Consider decomposing into subtasks via '
               'schedule_subagent. Produce your best final answer now from the verified work so far; clearly mark '
               'anything unverified or incomplete. An honest best-effort result is the expected outcome here, '
               'not a failure.')
# ouroboros/tools/commit_gate.py:491-500, the paid review-cycle ceiling message (same wording).
CYCLES_EXHAUSTED = (
    '⚠️ REVIEW_CYCLES_EXHAUSTED: this task tree (root {root}) already spent {paid} of {cap} paid triad+scope '
    'review cycle(s) (OUROBOROS_REVIEW_MAX_CYCLES). Refusing to buy another review.\nHonest exits: finalize '
    'honestly with what is already reviewed and committed; escalate to the owner (the ceiling is the owner\'s '
    'Max Review Cycles setting — 3/5/unlimited are one settings change away); or leave the remaining work to a '
    'follow-up task with its own budget. A rebuttal cannot buy past the ceiling — rebuttal cycles count toward it.')


def _prepare_process(proc):
    """Owner settings, a private data root for module constants, and no provider credentials."""
    for key in list(os.environ):
        if key.endswith(('_API_KEY', '_API_TOKEN', '_ACCESS_TOKEN')) or key in ('OPENROUTER_API_KEY', 'GIGACHAT_CREDENTIALS'):
            os.environ.pop(key, None)
    os.environ.update(OWNER_SETTINGS)
    os.environ.update({'OUROBOROS_APP_ROOT': str(proc), 'OUROBOROS_REPO_DIR': str(proc / 'repo'),
                       'OUROBOROS_DATA_DIR': str(proc / 'data'),
                       'OUROBOROS_SETTINGS_PATH': str(proc / 'data' / 'settings.json')})
    sys.dont_write_bytecode = True


def _text_of(content):
    if isinstance(content, list):
        return ''.join(part.get('text', '') if isinstance(part, dict) else str(part) for part in content)
    return '' if content is None else str(content)


def _split_messages(messages):
    """Chat messages -> (system, user) for a text backbone; later turns keep their role labels."""
    system = '\n\n'.join(_text_of(m.get('content')) for m in messages if m.get('role') == 'system')
    rest = [m for m in messages if m.get('role') != 'system']
    if len(rest) == 1:
        return system, _text_of(rest[0].get('content'))
    return system, '\n\n'.join(f"[{m.get('role')}]\n{_text_of(m.get('content'))}" for m in rest)


def _close_brackets(text):
    """The JSON value at the start of `text` with unbalanced brackets closed (outside strings): a mismatched closer
    gets the missing closers inserted before it, missing closers are appended, stray closers are dropped. Upstream's
    native tool calls always carry valid JSON; a text reply can drop a bracket in a long nested call."""
    out, stack, in_str, esc = [], [], False, False
    for ch in text:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in '{[':
            stack.append('}' if ch == '{' else ']')
        elif ch in '}]':
            if ch not in stack:
                continue
            while stack[-1] != ch:
                out.append(stack.pop())
            stack.pop()
            if not stack:
                out.append(ch)
                break
        out.append(ch)
    return ''.join(out + stack[::-1])


def _parse_calls(text):
    """A reply is either {"tool_calls": [...]} (possibly fenced) or a final message."""
    decoder = json.JSONDecoder(strict=False)   # literal newlines inside strings are accepted
    for start in [m.start() for m in re.finditer(r'\{', text or '')][:50]:
        try:
            obj, _end = decoder.raw_decode(text[start:])
        except ValueError:
            if not text[start:].lstrip('{ \n').startswith('"tool_calls"'):
                continue
            try:
                obj, _end = decoder.raw_decode(_close_brackets(text[start:]))
            except ValueError:
                continue
        if isinstance(obj, dict) and isinstance(obj.get('tool_calls'), list):
            calls = []
            for raw in obj['tool_calls']:
                if not isinstance(raw, dict):
                    continue
                name = str(raw.get('name') or (raw.get('function') or {}).get('name') or '').strip()
                args = raw.get('arguments', raw.get('args', raw.get('parameters', (raw.get('function') or {}).get('arguments', {}))))
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {'_raw': args}
                calls.append({'name': name, 'arguments': args if isinstance(args, dict) else {}})
            note = re.sub(r'```[A-Za-z]*\s*$', '', text[:start].strip()).strip()
            return calls, note
    return None, ''


def _is_make_check(line):
    """Whether a command line runs the repository's `make check` (with a cd/shell wrapper or make flags)."""
    text = re.sub(r"^\s*(?:(?:ba)?sh\s+-l?c\s+)?", '', line).strip().strip('\'"').strip()
    text = re.sub(r"^cd\s+\S+\s*&&\s*", '', text)
    text = re.sub(r"\s*2>&1\s*$", '', text)
    words = text.split()
    if not words or words[0] != 'make' or 'check' not in words:
        return False
    rest = [w for i, w in enumerate(words[1:], 1) if w != 'check' and not w.startswith('-') and words[i - 1] != '-C']
    return not rest


def _diff(old, new, path):
    return ''.join(difflib.unified_diff((old or '').splitlines(True), (new or '').splitlines(True),
                                        f'a/{path}', f'b/{path}', n=2))


def _tree_diff(base, current, prefix=''):
    """Unified diff of one checkout ({relative path: text}) against an earlier state of it."""
    return ''.join(_diff(base.get(p), current.get(p), prefix + p)
                   for p in sorted(set(base) | set(current)) if base.get(p) != current.get(p))


def _added_lines(old, new):
    """Indexes of lines of `new` that a line diff marks as inserted or replaced."""
    a, b = (old or '').splitlines(), (new or '').splitlines()
    ops = difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes()
    return {j for op, _i1, _i2, j1, j2 in ops if op in ('insert', 'replace') for j in range(j1, j2)}


def _section(lines, headings):
    """[lo, hi) of the nested Markdown section named by `headings` (each a full heading line), or None."""
    lo, hi = 0, len(lines)
    for heading in headings:
        idx = next((i for i in range(lo, hi) if lines[i].strip() == heading), None)
        if idx is None:
            return None
        level = len(heading) - len(heading.lstrip('#'))
        end = next((i for i in range(idx + 1, hi) if lines[i].startswith('#') and lines[i].lstrip('#').startswith(' ')
                    and len(lines[i]) - len(lines[i].lstrip('#')) <= level), hi)
        lo, hi = idx + 1, end
    return lo, hi


def first_failing_rule(rules, original, current):
    """The repository check of inputs/items.yaml: the first rule the current files break, or None.

    original/current map repo-relative paths to text. A regex may contain {stem}, the file name without
    its last extension, matched literally."""
    new = {p for p in current if p not in original}
    touched = new | {p for p in current if p in original and current[p] != original[p]}
    match = lambda glob, pool: sorted(p for p in pool if fnmatch.fnmatch(p, glob))
    rx = lambda rule, path: rule['regex'].replace('{stem}', re.escape(Path(path).stem))
    for rule in rules:
        kind = rule['type']
        if kind == 'unchanged':
            failed = any(current.get(p) != original.get(p) for p in rule.get('paths') or [rule['path']])
        elif kind == 'changed':
            failed = current.get(rule['path']) in (None, original.get(rule['path']))
        elif kind == 'new_file':
            failed = not match(rule['glob'], new)
        elif kind == 'no_new_file':
            failed = bool(match(rule['glob'], new))
        elif kind == 'path_regex':
            failed = any(not re.fullmatch(rx(rule, p), p) for p in match(rule['glob'], new))
        elif kind == 'content':
            failed = any(not re.fullmatch(rx(rule, p), current[p].strip()) for p in match(rule['glob'], touched))
        elif kind == 'contains':
            failed = any(not re.search(rx(rule, p), current[p]) for p in match(rule['glob'], touched))
        elif kind == 'forbid':
            failed = any(re.search(rx(rule, p), current[p]) for p in match(rule['glob'], touched))
        elif kind == 'added_line':
            lines = (current.get(rule['path']) or '').splitlines()
            span = _section(lines, rule.get('section') or [])
            added = _added_lines(original.get(rule['path']), current.get(rule['path']))
            failed = span is None or not any(span[0] <= j < span[1] and re.fullmatch(rule['regex'], lines[j].strip())
                                             for j in added)
        elif kind == 'sorted_keys':
            keys = re.findall(rule['regex'], current.get(rule['path']) or '', re.M)
            failed = keys != sorted(keys)
        elif kind == 'equals_original_with':
            failed = current.get(rule['path']) != original[rule['path']].replace(rule['old'], rule['new'], 1)
        else:
            raise ValueError(f'unknown rule type {kind}')
        if failed:
            return rule
    return None


class _Clock:
    """Frozen time, moved to a scripted instant at each step; real time inside the HALO backbone."""
    IGNORE = ['halo', 'subprocess', 'selectors', 'threading', 'concurrent', 'asyncio', 'queue', 'fcntl']

    def __init__(self, base):
        from freezegun import freeze_time
        self.base = base
        self._freezer = freeze_time(base, ignore=self.IGNORE, auto_tick_seconds=0.001)
        self._factory, self.position = None, base

    def __enter__(self):
        self._factory = self._freezer.start()
        return self

    def __exit__(self, *exc):
        self._freezer.stop()

    def move(self, minutes):
        self.position = self.base + timedelta(minutes=minutes)
        self._factory.move_to(self.position)


class _Run:
    """One item x sample x arm: paths, the sandbox, the seeded ids, the transcript."""

    def __init__(self, item, cut, sample):
        self.item, self.cut, self.sample = item, set(cut), sample
        self.root = Path(tempfile.mkdtemp(prefix=f"halo-ouroboros-{item['id']}-")).resolve()
        self.drive, self.repo, self.src = self.root / 'drive', self.root / 'repo', self.root / 'src'
        self.labels, self.calls, self.log = {}, [], {'tasks': [], 'post': [], 'evolution': None}
        self.stage = 'boot'
        self._rng = random.Random(0)
        self.prev_outcomes = None
        self.review_history, self.landed, self.proposal = [], False, None
        self.plan_reviews = []

    def step(self, name):
        self.stage = name
        self._rng = random.Random(hashlib.sha256(f"{self.item['id']}|{name}".encode()).hexdigest())

    def uuid4(self):
        return uuid.UUID(int=self._rng.getrandbits(128), version=4)

    def tag(self, label):
        key = f'{self.stage}:{label}'
        self.labels[key] = self.labels.get(key, 0) + 1
        return f"{self.item['id']}|s{self.sample}|{key}|{self.labels[key]}"

    def show(self, path, repo):
        """How a workspace path is shown to the model: relative inside the active repository, else ~/src/..."""
        base = (self.src / repo).resolve()
        if path == base:
            return '.'
        if path == self.src.resolve():
            return '~/src'
        if base in path.parents:
            return str(path.relative_to(base))
        return '~/src/' + str(path.relative_to(self.src.resolve()))


class Adapter(BaseAdapter):
    channels = {
        'S->M': "the owner's messages written to the room's chat log (dialogue memory)",
        'M->A': 'memory blocks (story, room, identity, scratchpad, knowledge, Pattern Register, reflections, '
                'backlog) assembled into the action context',
        'A->M': "Ouroboros's replies, execution reflections and their memory actions written to memory",
    }
    steps = {
        'record': "the experience review receives Ouroboros's own tool calls and final answer",
        'outcome': 'tool results (the `make check` verdicts) reach the experience review and its trigger',
        'attribution': "each task's results are attached to that task's own calls",
        'revision': "a reviewed commit of the application prompt lands in the repository the runtime loads",
        'later_use': 'test tasks build their context from the landed prompts/SYSTEM.md (cut together with revision)',
    }

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        from halo.run.llm import LLM
        # The reviewer is a second model role with the same backend and cache, tagged "reviewer|...".
        self.reviewer = LLM(llm.backend, llm.effort, llm.cache) if hasattr(llm, 'backend') else llm
        self._proc = Path(tempfile.mkdtemp(prefix='halo-ouroboros-proc-'))
        _prepare_process(self._proc)
        if str(CORE) not in sys.path:
            sys.path.insert(0, str(CORE))
        self._import_upstream()
        spec = yaml.safe_load((Path(case_dir) / 'inputs' / 'items.yaml').read_text(encoding='utf-8'))
        self.spec = {it['id']: it for it in spec['items']}
        self.world = spec['world']
        self.R = None

    # ---- upstream modules and the model-client replacement -------------------------------------
    def _import_upstream(self):
        import ouroboros.llm as ou_llm
        from ouroboros import (context, memory, memory_view, reflection, post_task_evolution, improvement_backlog,
                               post_task_synthesis, runtime_limits, review_cycles, owner_words, review_evidence)
        from ouroboros.tools import review as review_tool, core as core_tools, shell as shell_tools, git as git_tools
        from ouroboros.tools import control as control_tools
        from ouroboros.tools import review_helpers, release_sync, review_multi_model, review_response
        from ouroboros.tools import plan_review, plan_review_runtime
        from ouroboros.tools.registry import ToolContext
        from ouroboros.triad_review import REVIEW_JSON_ARRAY_CONTRACT
        from ouroboros.reviewer_slot_config import commit_triad_delivery
        from ouroboros.review_records import ReviewSlot
        from ouroboros.config import get_review_enforcement
        from supervisor import state as sup_state, queue as sup_queue, evolution_lifecycle, message_bus
        self.u = SimpleNamespace(**{k: v for k, v in locals().items() if k != 'self'})
        adapter = self

        class Backbone:
            """Stands in for ouroboros.llm.LLMClient: every chat() goes to the HALO backbone."""
            def __init__(self, *args, **kwargs):
                pass

            def default_model(self):
                return MODEL_ID

            def available_models(self):
                return [MODEL_ID]

            def chat(self, messages=None, model='', tools=None, **kwargs):
                system, user = _split_messages(messages or [])
                text = adapter._model(system, user, adapter._label_for(user))
                return ({'role': 'assistant', 'content': text},
                        {'prompt_tokens': (len(system) + len(user)) // 4, 'completion_tokens': len(text) // 4,
                         'cost': 0.0, 'provider': 'halo', 'resolved_model': MODEL_ID})

        ou_llm.LLMClient = Backbone
        self.Backbone = Backbone
        # Reviewer transport: the triad's fan-out (review substrate) is the only replaced part of the gate; the
        # same holds for plan_task, whose panel runs on the same triad rows.
        review_tool._handle_multi_model_review = self._triad_transport
        plan_review._run_plan_review_slots = plan_review_runtime.run_plan_review_slots = self._plan_transport
        # Git seams on the run's path, answered from the sandbox trees so that no git process ever runs:
        # HEAD is the landed sandbox copy (R.repo), the index is the cycle's working copy (R.worktree).
        from ouroboros.tools import review_file_pack
        from supervisor import git_ops
        review_tool._git_show_staged = lambda repo_dir, path: self._read(Path(repo_dir) / path)   # review.py:571
        review_file_pack._git_blob_text = self._git_blob                                          # review_file_pack.py:339
        git_ops.git_capture = self._git_capture                                                   # git_ops.py:300
        uuid.uuid4 = lambda: self.R.uuid4() if self.R is not None else uuid.UUID(int=random.getrandbits(128), version=4)

    def _git_blob(self, repo_dir, spec):
        """`git show <spec>` for HEAD:<path> (landed sandbox tree) and :<path> (the cycle's working copy)."""
        tree, _, rel = spec.partition(':')
        root = self.R.repo if tree == 'HEAD' else getattr(self.R, 'worktree', self.R.repo)
        return self._read(root / rel) or ''

    def _git_capture(self, cmd, *, timeout=None):
        """The read-only git queries the evolution transaction makes (evolution_lifecycle.py:553-554)."""
        if list(cmd[:3]) == ['git', 'rev-parse', 'HEAD'] and self.R is not None:
            tree = ''.join(f'{rel}\0{self._read(self.R.repo / rel) or ""}\0' for rel in EDITABLE)
            return 0, hashlib.sha1(tree.encode()).hexdigest(), ''
        if list(cmd[:4]) == ['git', 'rev-parse', '--abbrev-ref', 'HEAD']:
            return 0, 'ouroboros', ''
        return 128, '', 'fatal: git does not run in this sandbox'

    @staticmethod
    def _label_for(user):
        for marker, label in (('Review this finished run', 'reflection'), ('maintain a Pattern Register', 'patterns'),
                              ('ONE reviewed self-improvement', 'promotion'), ('You are de-duplicating', 'dedup'),
                              ('grooming Ouroboros', 'groom')):
            if marker in user:
                return label
        return 'light'

    def _model(self, system, user, label, role=''):
        tag = self.R.tag(label)
        llm = self.reviewer if role == 'reviewer' else self.llm
        text = llm(system, user, tag=(f'{role}|{tag}' if role else tag))
        self.R.calls.append({'tag': tag, 'role': role or 'backbone', 'prompt_chars': len(system) + len(user)})
        return text or ''

    # ---- inputs -----------------------------------------------------------------------------------
    def items(self):
        out = []
        for item in self.spec.values():
            lines = [f"Owner: {item['owner']}. Ouroboros works in the owner's repositories under ~/src.",
                     f"The {item['org']} organization's contributing guide (~/src/.github/CONTRIBUTING.md) applies to "
                     'every repository, none of which has a guide of its own; `make check` in each repository enforces '
                     "that repository's section. Test tasks judged here:"]
            for t in item['tasks']:
                if t['phase'] == 'test':
                    lines += ['', f"{t['id']} in ~/src/{t['repo']} (guide section \"{item['repos'][t['repo']]['guide']}\"): "
                                  f"{t['request']}"]
            lines += ['', 'The organization guide:', '', item['org_guide'].strip()]
            out.append({'id': item['id'], 'judge_context': '\n'.join(lines)})
        return out

    # ---- one run ------------------------------------------------------------------------------------
    def run(self, item, cut, sample):
        spec = self.spec[item['id']]
        R = self.R = _Run(spec, cut, sample)
        base = datetime.fromisoformat(f"{spec['date']}T09:00:00+00:00")
        try:
            with _Clock(base) as clock:
                R.clock = clock
                self._boot(R)
                tasks = {t['id']: t for t in spec['tasks']}
                for n, tid in enumerate(('L1', 'L2')):
                    clock.move(60 * n)
                    task, final, trace, rounds = self._task(R, tasks[tid])
                    clock.move(60 * n + 20)
                    self._post_task(R, task, final, trace, rounds)
                clock.move(150)
                evo_task = self._tick(R)
                if evo_task is not None:
                    clock.move(160)
                    self._evolution(R, evo_task)
                for n, tid in enumerate(('T1', 'T2')):
                    clock.move(300 + 60 * n)
                    self._task(R, tasks[tid])
            return self._result(R)
        finally:
            self.R = None
            if not os.environ.get('HALO_KEEP_RUN'):
                shutil.rmtree(R.root, ignore_errors=True)

    def _boot(self, R):
        u = self.u
        R.step('boot')
        for rel in EDITABLE + PROTECTED + READ_ONLY_EXTRA:
            (R.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(CORE / rel, R.repo / rel)
        # The owner's checkouts: the organization's `.github` repository (default community health files, which
        # GitHub applies to every repository without its own) and the four repositories, none with a guide of its own.
        org = R.item['org']
        trees = {ORG_REPO: {'README.md': ORG_README.format(org=org), 'CONTRIBUTING.md': R.item['org_guide']}}
        trees.update({name: repo['files'] for name, repo in R.item['repos'].items()})
        R.originals = {}
        for name, files in trees.items():
            R.originals[name] = dict(files)
            for rel, content in files.items():
                path = R.src / name / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
        (R.drive / 'memory').mkdir(parents=True)
        (R.drive / 'logs').mkdir(parents=True)
        (R.drive / 'memory' / 'WORLD.md').write_text(self.world, encoding='utf-8')
        u.sup_state.init(R.drive)
        u.sup_queue.init(R.drive)
        u.sup_state.init_state(origin='first_boot')
        u.sup_state.update_state(lambda live: live.update({'owner_chat_id': OWNER_CHAT, 'owner_id': OWNER_CHAT}))
        R.memory = u.memory.Memory(drive_root=R.drive, repo_dir=R.repo)
        R.memory.ensure_files()
        R.env = SimpleNamespace(repo_dir=R.repo, drive_root=R.drive, budget_drive_root=R.drive, branch_dev='ouroboros',
                                repo_path=lambda rel: (R.repo / rel).resolve(),
                                drive_path=lambda rel: (R.drive / rel).resolve())
        self._views({'id': 'boot', 'type': 'task', 'chat_id': OWNER_CHAT, 'text': ''})   # activates the chronicle

    # ---- context (ported composition, upstream builders) --------------------------------------------
    def _views(self, task):
        mv = self.u.memory_view
        snapshot = mv.capture_memory_view(self.R.drive, task, mv.view_spec_for_task(task, self.R.drive))
        return mv.render_story(snapshot), mv.render_room(snapshot)

    def _context(self, R, task, kind, repo=None):
        u = self.u
        governance = '\n\n'.join([self._read(R.repo / 'prompts/SYSTEM.md'),
                                  '## BIBLE.md\n\n' + self._read(R.repo / 'BIBLE.md'), DOCS_NOTE])
        runtime = self._runtime(R, task, kind, repo)
        if 'M->A' in R.cut:   # cut site M->A: no retained information reaches the action context
            return '\n\n'.join([governance, runtime])
        story, room = self._views(task)
        stable = u.context.build_memory_sections(R.memory, partition='stable')
        head = u.context.build_knowledge_sections(R.env)
        volatile = u.context.build_memory_sections(R.memory, partition='volatile')
        backlog = [u.improvement_backlog.format_backlog_digest(R.drive)] if kind == 'evolution' else []
        recent = u.context.build_recent_sections(R.memory, R.env, task_id=task['id'])
        blocks = ['\n\n'.join(stable + [story]),
                  '\n\n'.join(head + [room] + volatile + [runtime] + [b for b in backlog if b] + recent)]
        return '\n\n'.join([governance] + [b for b in blocks if b.strip()])

    def _runtime(self, R, task, kind, repo):
        now = R.clock.position.isoformat()   # the scripted instant of this step (the frozen clock)
        lines = ['## Runtime', f'- now: {now}', '- runtime_mode: advanced', '- room: Main (direct dialogue with my human)']
        if kind == 'evolution':
            lines += [f"- task: {task['id']} (type=evolution)",
                      '- active_workspace: system_repo (a sandbox working copy of my own repository)']
        else:
            lines += [f"- task: {task['id']}", f'- active_workspace: ~/src/{repo} (file and process tools default here)']
        return '\n'.join(lines)

    def _tools_block(self, kind):
        u = self.u
        wanted = {'task': [('core_tools', 'list_files', ('path', 'max_entries')),
                           ('core_tools', 'read_file', ('path', 'start_line', 'max_lines')),
                           ('core_tools', 'write_file', ('path', 'content')),
                           ('shell_tools', 'run_command', ('cmd', 'cwd'))],
                  'evolution': [('core_tools', 'read_file', ('path', 'start_line', 'max_lines')),
                                ('core_tools', 'edit_text', ('path', 'old_str', 'new_str')),
                                ('core_tools', 'write_file', ('path', 'content')),
                                ('plan_review', 'plan_task', ('goal', 'plan', 'spec', 'review_disposition')),
                                ('git_tools', 'commit_reviewed', ('commit_message', 'goal', 'scope', 'review_rebuttal',
                                                                  'skip_advisory_review')),
                                ('control_tools', 'request_restart', ('reason',))]}[kind]
        schemas = []
        for module, name, keep in wanted:
            schema = copy.deepcopy(next(e.schema for e in getattr(u, module).get_tools() if e.name == name))
            props = schema.get('parameters', {}).get('properties', {})
            schema['parameters']['properties'] = {k: v for k, v in props.items() if k in keep}
            schema['parameters']['required'] = [k for k in schema['parameters'].get('required', []) if k in keep]
            schemas.append(schema)
        where = ('my human\'s checkouts under ~/src (`root` defaults to active_workspace and relative paths start '
                 'there; ~/src/... paths reach the other checkouts; other roots are not available here); run_command '
                 'executes only a repository\'s `make check` target in this sandbox'
                 if kind == 'task' else
                 'system_repo, the sandbox working copy of my repository; plan_task runs the plan review on the triad '
                 'reviewer rows; commit_reviewed runs the reviewed commit workflow on it (release sync, preflight, '
                 'blocking triad review); the advisory pre-review has no configured route here, so commit_reviewed '
                 'records the audited advisory bypass; tests are not run in this sandbox')
        return ('## Tools in this run\n\nThe host executes these tools (schemas from my registry; arguments that do not '
                f'apply in this sandbox are omitted). File tools work in {where}.\n\n'
                + json.dumps(schemas, ensure_ascii=False, indent=1)
                + '\n\nTo call tools, reply with ONLY a JSON object and no other text: '
                  '{"tool_calls": [{"name": "<tool>", "arguments": {...}}, ...]}. Several calls in one reply run in '
                  'order and their results come back together. When the work is done, reply with my final message '
                  'as plain text (no JSON).')

    # ---- the tool loop (ported from loop.py: rounds 1..MAX_ROUNDS, then one forced final) ------------
    def _loop(self, R, name, system, header, execute, *, forced_final=True, stop=None):
        max_rounds = self.u.runtime_limits.get_max_rounds()
        rounds, trace, final = [], {'reasoning_notes': [], 'tool_calls': []}, ''
        for r in range(1, (max_rounds or 99) + 2):
            forced = max_rounds is not None and r > max_rounds
            if forced and not forced_final:
                break
            tail = ((ROUND_LIMIT.format(n=max_rounds) + '\n(The host executes no tool call in this round.)') if forced
                    else 'Continue: reply with a JSON tool-call object, or with my final message as plain text.')
            reply = self._model(system, self._transcript(header, rounds, tail), f'r{r}')
            calls, note = _parse_calls(reply)
            if calls is not None and not calls:   # an empty tool-call list is a final answer
                calls, reply = None, note or reply
            if forced:   # the forced rail executes nothing; tool calls without text fall back to the finish reason
                final = (note if calls else reply.strip()) or ROUND_LIMIT.format(n=max_rounds).split(' Produce')[0][len('[ROUND_LIMIT] '):]
                break
            if not calls:
                final = reply.strip()
                break
            if note:
                trace['reasoning_notes'].append(note)
            results = [execute(call) for call in calls]
            for call, res in zip(calls, results):
                trace['tool_calls'].append({'tool': call['name'], 'args': call['arguments'], 'round_id': f'{name}:round:{r}',
                                            **{k: res[k] for k in OUTCOME_KEYS if k in res}})
            rounds.append({'calls': calls, 'results': results})
            if stop is not None and stop():
                break
        return final, trace, rounds

    @staticmethod
    def _transcript(header, rounds, tail):
        parts = [header]
        for i, rd in enumerate(rounds, 1):
            parts.append(f'[Round {i} — my tool calls]\n' + json.dumps({'tool_calls': rd['calls']}, ensure_ascii=False))
            shown = []
            for j, (call, res) in enumerate(zip(rd['calls'], rd['results']), 1):
                code = f" (exit {res['exit_code']})" if res.get('exit_code') is not None else ''
                shown.append(f"#{j} {call['name']} → {res['status'] or 'ok'}{code}\n{res['result']}")
            parts.append(f'[Round {i} — tool results]\n' + '\n\n'.join(shown))
        parts.append(tail)
        return '\n\n'.join(parts)

    # ---- an ordinary task turn ----------------------------------------------------------------------
    def _owner_says(self, R, task):
        if 'S->M' in R.cut:   # cut site S->M: the owner's words never reach the chat log memory reads
            return
        self.u.message_bus.log_chat('in', OWNER_CHAT, OWNER_CHAT, task['text'], drive_root=R.drive,
                                    task_id=task['id'], source='web')

    def _task(self, R, t):
        tid, repo = t['id'], t['repo']
        R.step(tid)
        task = {'id': tid, 'type': 'task', 'chat_id': OWNER_CHAT, 'text': t['request'], '_is_direct_chat': True}
        self._owner_says(R, task)
        before = self._trees(R)   # the delivered diff covers every checkout under ~/src (others only if edited)
        system = self._context(R, task, 'task', repo) + '\n\n' + self._tools_block('task')
        header = '[Message from my human]\n' + t['request']
        final, trace, rounds = self._loop(R, tid, system, header, lambda call: self._task_tool(R, repo, call))
        if 'A->M' not in R.cut:   # cut site A->M (1/3): my reply is not written to the chat log
            self.u.message_bus.log_chat('out', OWNER_CHAT, 0, final or '(no reply)', drive_root=R.drive, task_id=tid)
        ok, output, rule = self._check(R, repo)
        after = self._trees(R)
        diff = ''.join(_tree_diff(before.get(n, {}), after.get(n, {}), '' if n == repo else f'~/src/{n}/')
                       for n in sorted(set(before) | set(after), key=lambda n: n != repo))
        R.log['tasks'].append({'id': tid, 'phase': t['phase'], 'repo': repo, 'request': t['request'], 'final': final,
                               'rounds': len(rounds) + 1, 'calls': [(c['tool'], c['args'], c.get('status', ''),
                                                                     c.get('exit_code')) for c in trace['tool_calls']],
                               'check_runs': [c.get('exit_code') for c in trace['tool_calls']
                                              if c['tool'] == 'run_command' and c.get('exit_code') is not None],
                               'ci_pass': ok, 'ci_output': output, 'ci_rule': rule, 'diff': diff})
        return task, final, trace, len(rounds) + 1

    def _resolve(self, R, repo, raw):
        raw = str(raw or '.').strip()
        if raw.rstrip('/') in (f'{HOME}/src', '~/src'):
            return R.src.resolve()
        for prefix in (f'{HOME}/src/', '~/src/'):
            if raw.startswith(prefix):
                path = (R.src / raw[len(prefix):]).resolve()
                break
        else:
            if raw.startswith(('/', '~')):
                return None
            path = (R.src / repo / raw).resolve()
        return path if path == R.src.resolve() or R.src.resolve() in path.parents else None

    def _task_tool(self, R, repo, call):
        name, a = call['name'], call['arguments']
        err = lambda text: {'result': text, 'status': 'error', 'is_error': True, 'tool_result_code': 'TOOL_ARG_ERROR'}
        if str(a.get('root') or 'active_workspace') != 'active_workspace':
            return err(f"⚠️ TOOL_ARG_ERROR: root={a.get('root')!r} is not available in this run; use the active workspace.")
        if name in ('list_files', 'read_file', 'write_file'):
            path = self._resolve(R, repo, a.get('path', '.'))
            if path is None:
                return err(f"⚠️ TOOL_ARG_ERROR: path {a.get('path')!r} is outside the authorized roots (~/src).")
            shown = R.show(path, repo)
            where = shown if shown.startswith('~') else f'active_workspace:{shown}'
            if name == 'list_files':
                if not path.is_dir():
                    return err(f'⚠️ TOOL_ARG_ERROR: {shown} is not a directory.')
                entries = sorted(str(p.relative_to(path)) + ('/' if p.is_dir() else '') for p in path.rglob('*'))
                limit = int(a.get('max_entries') or 500)
                return {'result': f'{where} — {len(entries)} entries\n' + '\n'.join(entries[:limit]),
                        'status': 'ok'}
            if name == 'read_file':
                if not path.is_file():
                    return err(f'⚠️ TOOL_ARG_ERROR: {shown} does not exist.')
                lines = self._read(path).splitlines()
                start = max(1, int(a.get('start_line') or 1))
                count = int(a.get('max_lines') or 2000)
                chunk = lines[start - 1:start - 1 + count]
                return {'result': f'{where} lines {start}–{start + len(chunk) - 1} of {len(lines)}\n'
                                  + '\n'.join(chunk), 'status': 'ok'}
            content = a.get('content')
            if not isinstance(content, str):
                return err('⚠️ TOOL_ARG_ERROR: write_file needs `path` and string `content`.')
            old = self._read(path) if path.is_file() else None
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            note = f'\nDiff vs the previous version:\n{_diff(old, content, shown)}' if old is not None else ''
            return {'result': f'OK: {where} ({len(content)} chars written){note}', 'status': 'ok'}
        if name == 'run_command':
            cmd = a.get('cmd')
            words = cmd if isinstance(cmd, list) else str(cmd or '').split()
            line = ' '.join(str(w) for w in words)
            cwd = self._resolve(R, repo, a.get('cwd') or '.')
            target = cwd.relative_to(R.src).parts[0] if cwd is not None and cwd != R.src else repo
            if target not in R.item['repos']:
                return err(f"⚠️ TOOL_ARG_ERROR: cwd {a.get('cwd')!r} is not a repository under ~/src.")
            if not _is_make_check(line):
                text = (f'⚠️ SHELL_EXIT_ERROR: command exited with exit code 127 (cwd ~/src/{target}).\n\n'
                        f'sandbox: `{line}` is not available in this run; only the repository\'s `make check` target '
                        'executes here. Use read_file/list_files to read files.')
                return {'result': text, 'status': 'error', 'is_error': True, 'exit_code': 127,
                        'tool_result_code': 'SHELL_EXIT_ERROR'}
            ok, output, _rule = self._check(R, target)
            if ok:
                return {'result': f'exit code 0 (cwd ~/src/{target})\n$ make check\n{output}', 'status': 'ok',
                        'exit_code': 0, 'tool_result_code': 'OK'}
            return {'result': f'⚠️ SHELL_EXIT_ERROR: command exited with exit code 2 (cwd ~/src/{target}).\n\n'
                              f'$ make check\n{output}', 'status': 'error', 'is_error': True, 'exit_code': 2,
                    'tool_result_code': 'SHELL_EXIT_ERROR'}
        return err(f'⚠️ TOOL_ARG_ERROR: unknown tool {name!r} in this run.')

    # ---- the repository check (`make check`, simulated from declarative rules) ----------------------
    def _check(self, R, name):
        """`make check` of one repository: the declarative rules, fail-fast (first failing rule reported)."""
        repo = R.item['repos'][name]
        root = R.src / name
        current = {str(p.relative_to(root)): self._read(p) for p in root.rglob('*') if p.is_file()}
        header = f"{repo['checker']}: {len(repo['rules'])} rules"
        rule = first_failing_rule(repo['rules'], R.originals[name], current)
        if rule is not None:
            return (False, f"{header}\n{repo['checker']}: FAIL [{rule['id']}] {rule['msg']}\n"
                           'make: *** [Makefile:2: check] Error 1', rule['id'])
        return True, f"{header}\n{repo['checker']}: OK — all {len(repo['rules'])} rules passed", ''

    def _trees(self, R):
        """Every checkout under ~/src as {name: {relative path: text}}."""
        return {d.name: {str(p.relative_to(d)): self._read(p) for p in d.rglob('*') if p.is_file()}
                for d in sorted(R.src.iterdir()) if d.is_dir()}


    # ---- post-task stages (upstream, with the evidence-step and A->M cut sites) ------------------------
    def _evidence(self, R, task, final, trace):
        """The record, outcome and attribution cut sites: what the experience review receives."""
        calls = copy.deepcopy(trace['tool_calls'])
        notes = list(trace.get('reasoning_notes') or [])
        sealed = {'final_result_text': final, 'artifact_manifest': [],
                  'completion_observations': {'status': 'unavailable'}}
        if 'attribution' in R.cut:   # results arrive one task late, attached to the wrong task's calls
            own = [{k: c[k] for k in OUTCOME_KEYS if k in c} for c in calls]
            late = R.prev_outcomes or []
            R.prev_outcomes = own
            calls = [{**{k: v for k, v in c.items() if k not in OUTCOME_KEYS}, **(late[i] if i < len(late) else {})}
                     for i, c in enumerate(calls)]
        if 'outcome' in R.cut:       # no result or status of any call reaches the review
            calls = [{k: v for k, v in c.items() if k not in OUTCOME_KEYS} for c in calls]
        if 'record' in R.cut:        # the review sees results but not which actions produced them
            calls = [{'tool': '', 'args': {}, **{k: c[k] for k in OUTCOME_KEYS if k in c}} for c in calls]
            notes, sealed = [], None
        return {'tool_calls': calls, 'reasoning_notes': notes}, sealed

    def _post_task(self, R, task, final, trace, rounds):
        u = self.u
        R.step(f"{task['id']}:post")
        llm_client, pts = self.Backbone(), u.post_task_synthesis
        usage = {'rounds': rounds, 'cost': None}
        pts._run_memory_fallback_draft(R.env, task, llm_client, R.drive / 'logs', trace)
        pts._run_scratchpad_consolidation(R.env, R.memory, llm_client)
        review_trace, sealed = self._evidence(R, task, final, trace)
        writer = u.reflection.append_reflection_routed
        written = []
        if 'A->M' in R.cut:   # cut site A->M (2/3): the reflection writer keeps nothing in memory
            u.reflection.append_reflection_routed = lambda env, task_, entry: written.append(entry)
        try:
            entry = pts._run_reflection(R.env, llm_client, task, usage, review_trace, {}, sealed_final=sealed)
        finally:
            u.reflection.append_reflection_routed = writer
        if entry is not None and 'A->M' not in R.cut:   # cut site A->M (3/3): no memory actions applied
            pts._apply_reflection_memory_actions(R.env, entry)
        pts._update_improvement_backlog(R.env, entry)
        decision = u.post_task_evolution.maybe_promote(R.env, task, entry, llm_client)
        R.log['post'].append({'task': task['id'], 'reflection': (entry or {}).get('reflection'),
                              'memory_actions': (entry or {}).get('memory_actions'),
                              'backlog_candidates': (entry or {}).get('backlog_candidates'), 'promotion': decision})

    # ---- supervisor tick: apply the promotion, enqueue the evolution cycle ---------------------------
    def _tick(self, R):
        u = self.u
        R.step('tick')
        R.log['promotion_applied'] = bool(u.post_task_evolution.apply_pending_request(R.drive))
        if not R.log['promotion_applied']:
            return None
        captured, notices = {}, []
        q = u.sup_queue
        saved = q.enqueue_with_admission_receipt, q.send_with_budget

        def admit(task, prepare_admission=None, **kwargs):   # the queue admission is captured, not run
            if prepare_admission is None or prepare_admission(task):
                captured['task'] = task
            return {'id': task['id']}
        q.enqueue_with_admission_receipt = admit
        q.send_with_budget = lambda chat_id, text, **kwargs: notices.append(text)
        try:
            u.evolution_lifecycle.enqueue_evolution_task_if_needed()
        finally:
            q.enqueue_with_admission_receipt, q.send_with_budget = saved
        R.log['owner_notices'] = notices
        R.log['campaign'] = u.evolution_lifecycle._read_evolution_campaign()
        return captured.get('task')

    # ---- the evolution cycle ------------------------------------------------------------------------
    def _evolution(self, R, evo_task):
        R.step('evo')
        R.worktree = R.root / 'worktree'
        shutil.copytree(R.repo, R.worktree)
        R.attempts = []
        task = {**evo_task, 'id': str(evo_task.get('id') or 'evolution')}
        system = '\n\n'.join([self._context(R, task, 'evolution'), self._sandbox_note(R), self._tools_block('evolution')])
        header = '[Task]\n' + str(evo_task.get('text') or '')
        cap = self.u.review_cycles.review_max_cycles()
        stop = lambda: R.landed or bool(R.proposal and R.proposal.get('accepted')) or \
            (cap is not None and sum(a['paid'] for a in R.attempts) >= cap)
        final, trace, rounds = self._loop(R, 'evo', system, header, lambda call: self._evo_tool(R, task, call),
                                          forced_final=False, stop=stop)
        R.log['evolution'] = {'task_text': evo_task.get('text'), 'final': final, 'attempts': R.attempts,
                              'plan_reviews': R.plan_reviews,
                              'calls': [(c['tool'], {k: (v if len(str(v)) < 300 else str(v)[:300] + '…')
                                                     for k, v in c['args'].items()}, c.get('status', ''))
                                        for c in trace['tool_calls']]}

    def _sandbox_note(self, R):
        readme = self._read(R.repo / 'README.md')
        history = readme[readme.find('## Version History'):] if '## Version History' in readme else ''
        badge = next((line for line in readme.splitlines() if 'img.shields.io/badge/version-' in line), '')
        return ('## This run\'s system_repo\n\nThe sandbox working copy of my repository holds the files this cycle may '
                'change: prompts/SYSTEM.md (byte-identical to the base prompt at the top of this context, up to '
                '"## BIBLE.md"), VERSION (' + self._read(R.repo / 'VERSION').strip() + '), README.md and the other '
                'release carriers (docs/ARCHITECTURE.md, pyproject.toml, uv.lock, web/package.json, '
                'web/package-lock.json, web/modules/api_types.js, site/install/index.html, docs/install/index.html). '
                'BIBLE.md is protected. The reference books (docs/ARCHITECTURE.md and docs/DEVELOPMENT.md with their '
                'chapters under docs/architecture/ and docs/development/) and docs/CHECKLISTS.md are here to read. '
                'Code is not part of this sandbox: this run restricts self-modification to '
                'prompts and release metadata. When VERSION changes, the commit path syncs every carrier derived '
                'from it (release_sync); the README Version History row is mine to write.\n\n'
                f'README.md version badge line:\n{badge}\n\nREADME.md — current Version History section:\n\n{history}')

    def _evo_tool(self, R, task, call):
        name, a = call['name'], call['arguments']
        err = lambda text: {'result': text, 'status': 'error', 'is_error': True, 'tool_result_code': 'TOOL_ARG_ERROR'}
        if name == 'commit_reviewed':
            return self._commit_reviewed(R, task, a)
        if name == 'plan_task':
            return self._plan_task(R, task, a)
        if name == 'request_restart':
            text = ('Restart requested: the next task loads the committed tree.' if R.proposal else
                    'No reviewed commit in this cycle; nothing to restart into.')
            return {'result': text, 'status': 'ok'}
        if name in ('preflight_review', 'run_command', 'request_deep_self_review'):
            return err(f'⚠️ TOOL_UNAVAILABLE: {name} is not available in this sandbox run.')
        rel = str(a.get('path') or '').strip()
        for prefix in ('system_repo:', 'system_repo/', './', '/'):
            rel = rel[len(prefix):] if rel.startswith(prefix) else rel
        if not rel:
            return err('⚠️ TOOL_ARG_ERROR: `path` is required.')
        path = (R.worktree / rel).resolve()
        if R.worktree.resolve() not in path.parents:
            return err(f'⚠️ TOOL_ARG_ERROR: {rel} is outside system_repo.')
        if name == 'read_file':
            if not path.is_file():
                return err(f'⚠️ TOOL_ARG_ERROR: system_repo:{rel} is not in this sandbox.')
            lines = self._read(path).splitlines()
            start, count = max(1, int(a.get('start_line') or 1)), int(a.get('max_lines') or 2000)
            chunk = lines[start - 1:start - 1 + count]
            return {'result': f'system_repo:{rel} lines {start}–{start + len(chunk) - 1} of {len(lines)}\n'
                              + '\n'.join(chunk), 'status': 'ok'}
        if name in ('edit_text', 'write_file'):
            if rel in PROTECTED:
                return err(f'⚠️ PROTECTED_PATH: system_repo:{rel} is protected in advanced mode.')
            if rel not in EDITABLE:
                return err(f'⚠️ TOOL_ARG_ERROR: system_repo:{rel} is outside this sandbox, which restricts '
                           'self-modification to prompts and release metadata.')
            old = self._read(path)
            if name == 'write_file':
                if not isinstance(a.get('content'), str):
                    return err('⚠️ TOOL_ARG_ERROR: write_file needs string `content`.')
                new = a['content']
            else:
                old_str, new_str = a.get('old_str'), a.get('new_str')
                if not isinstance(old_str, str) or not isinstance(new_str, str) or not old_str:
                    return err('⚠️ TOOL_ARG_ERROR: edit_text needs `old_str` and `new_str`.')
                count = old.count(old_str)
                if count != 1:
                    return err(f'⚠️ TOOL_ARG_ERROR: old_str occurs {count} times in system_repo:{rel}; it must occur exactly once.')
                new = old.replace(old_str, new_str, 1)
            path.write_text(new, encoding='utf-8')
            return {'result': f'OK: system_repo:{rel} edited\n{_diff(old, new, rel)}', 'status': 'ok'}
        return err(f'⚠️ TOOL_ARG_ERROR: unknown tool {name!r} in this cycle.')

    def _plan_task(self, R, task, a):
        """plan_task as upstream runs it (tools/plan_review.py:341 _handle_plan_task, unchanged), on the cycle's
        sandbox; only the panel's fan-out is replaced (_plan_transport)."""
        ctx = self.u.ToolContext(repo_dir=R.worktree, drive_root=R.drive, task_id=task['id'],
                                 current_task_type='evolution')
        args = {k: v for k, v in a.items() if k in ('goal', 'plan', 'spec', 'review_disposition')}
        text = str(self.u.plan_review._handle_plan_task(ctx, **args) or '')
        R.plan_reviews.append({'args': args, 'result': text})
        failed = text.lstrip().startswith(('ERROR', '⚠️'))
        return {'result': text, 'status': 'error' if failed else 'ok', **({'is_error': True} if failed else {})}

    async def _plan_transport(self, ctx, slots, *, system_prompt='', user_content='', slot_messages=None, **kwargs):
        """Replaces tools/plan_review_runtime.py:379 run_plan_review_slots (the substrate fan-out of plan_task):
        each row gets upstream's plan-review messages (build_plan_review_messages) from the reviewer model role."""
        from ouroboros.tools.plan_packet import plan_user_stable_len
        from ouroboros.tools.review_synthesis import build_plan_review_messages
        base = build_plan_review_messages(system_prompt, user_content, plan_user_stable_len(user_content))
        wave = len(self.R.plan_reviews) + 1
        rows = []
        for slot in slots:
            sid = str(slot.slot_id)
            system, user = _split_messages((slot_messages or {}).get(sid) or base)
            try:
                text = self._model(system, user, f'plan:w{wave}:{sid}', role='reviewer')
                actor = {'slot_id': sid, 'model': slot.model, 'status': 'ok' if text.strip() else 'empty',
                         'raw_text': text, 'usage': {'resolved_model': MODEL_ID}}
            except Exception as exc:   # a failed row is a typed error row, as in the substrate
                actor = {'slot_id': sid, 'model': slot.model, 'status': 'error', 'error': f'Error: {exc}'}
            rows.append(self.u.plan_review_runtime._plan_row_from_actor(actor, slot))
        return rows

    def _touched(self, R):
        return sorted(rel for rel in EDITABLE if self._read(R.worktree / rel) != self._read(R.repo / rel))

    def _commit_reviewed(self, R, task, a):
        """The reviewed commit: release sync, upstream preflight, upstream packet + verdict, then landing."""
        u, rv = self.u, self.u.review_tool
        blocked = lambda text: {'result': text, 'status': 'error', 'is_error': True, 'tool_result_code': 'REVIEW_BLOCKED'}
        cap, paid = u.review_cycles.review_max_cycles(), sum(x['paid'] for x in R.attempts)
        if cap is not None and paid >= cap:
            return blocked(CYCLES_EXHAUSTED.format(root=task['id'], paid=paid, cap=cap))
        message = str(a.get('commit_message') or '').strip()
        goal, scope, rebuttal = str(a.get('goal') or ''), str(a.get('scope') or ''), str(a.get('review_rebuttal') or '')
        if not message:
            return blocked('⚠️ TOOL_ARG_ERROR: commit_message is required.')
        touched = self._touched(R)
        if not touched:
            return blocked('⚠️ NOTHING_TO_COMMIT: system_repo has no changes.')
        if 'VERSION' in touched:
            u.release_sync.sync_release_metadata(str(R.worktree))
            touched = self._touched(R)
        ctx = u.ToolContext(repo_dir=R.worktree, drive_root=R.drive, task_id=task['id'])
        # tools/review.py:1028-1035: per-attempt reset (history persists across attempts, as on the ctx).
        ctx._review_iteration_count = len(R.attempts) + 1
        ctx._review_history = R.review_history
        ctx._last_review_block_reason, ctx._last_triad_models, ctx._last_review_critical_findings = '', [], []
        ctx._last_triad_raw_results, ctx._triad_withheld_seat_records, ctx._review_degraded_reasons = [], [], []
        staged = '\n'.join(f"{'M' if (R.repo / p).exists() else 'A'}  {p}" for p in touched)
        attempt = {'n': len(R.attempts) + 1, 'message': message, 'goal': goal, 'touched': touched, 'paid': False,
                   'diff': ''.join(_diff(self._read(R.repo / p), self._read(R.worktree / p), p) for p in touched)}
        R.attempts.append(attempt)
        preflight = rv._preflight_check(message, staged, R.worktree)
        if preflight:
            attempt.update(verdict='preflight_blocked', text=preflight)
            out = rv._handle_review_block_or_warning(ctx, True, preflight, '')
            return blocked(out or preflight)
        prepared = self._triad_packet(R, ctx, touched, message, goal, scope, rebuttal)
        attempt['paid'] = True
        verdict = rv._dispatch_unified_review(ctx, message, prepared)
        attempt.update(critical=list(getattr(ctx, '_last_review_critical_findings', []) or []),
                       advisory=[w if isinstance(w, str) else json.dumps(w, ensure_ascii=False)
                                 for w in getattr(ctx, '_review_advisory', []) or []],
                       degraded=list(getattr(ctx, '_review_degraded_reasons', []) or []))
        if verdict is not None:
            attempt.update(verdict='blocked', text=verdict)
            return blocked(verdict)
        attempt.update(verdict='passed')
        R.proposal = {'accepted': True, 'diff': attempt['diff'], 'message': message}
        if 'revision' not in R.cut:   # cut site revision: the reviewed commit never reaches the runtime's tree
            for rel in touched:
                shutil.copy2(R.worktree / rel, R.repo / rel)
            R.landed = True
            backlog_id = str((R.log.get('campaign') or {}).get('post_task_backlog_id') or '')
            if backlog_id:
                u.improvement_backlog.close_backlog_items(R.drive, ids=[backlog_id])
        version = self._read(R.worktree / 'VERSION').strip()
        sha = hashlib.sha1(attempt['diff'].encode()).hexdigest()[:10]
        return {'result': f'✅ Committed after review: {sha} "{message.splitlines()[0]}" (v{version}). '
                          'Restart verification is the absorption boundary for this cycle.', 'status': 'ok'}

    def _triad_packet(self, R, ctx, touched, message, goal, scope, rebuttal):
        """tools/review.py:1066-1306 (_prepare_unified_review) without git: same sections, same templates."""
        u, rv, rh = self.u, self.u.review_tool, self.u.review_helpers
        checklist = rv._load_checklist_section()
        history = rv._build_review_history_section(ctx._review_history, open_obligations=[])
        row_plan = u.commit_triad_delivery()
        models = list(row_plan['models'])
        slots = [u.ReviewSlot(slot_id=row_plan['slot_ids'][i], model=models[i],
                              session_profile=row_plan['session_profiles'][i], use_local=row_plan['use_local'][i])
                 for i in range(len(models))]
        governance = rv._triad_governance_context(ctx, touched, checklist, models, slots)
        exclude, exclusion_note = rh.triad_pack_exclusions(R.worktree, touched,
                                                           prefix_texts=dict(governance.inline_whole_documents))
        files_section, omitted = rh.build_touched_file_pack(R.worktree, touched, exclude_paths=exclude)
        if omitted:
            files_section += f"\n\n⚠️ OMISSION NOTE: {len(omitted)} file(s) omitted from direct context: {', '.join(omitted)}"
        if exclusion_note:
            files_section += f'\n\n{exclusion_note}'
        diff_text = ''.join(f'diff --git a/{p} b/{p}\n' + _diff(self._read(R.repo / p), self._read(R.worktree / p), p)
                            for p in touched)
        tail = '\n\n'.join(part for part in (governance.selected_inline, governance.navigation) if part.strip())
        stable = rv._REVIEW_PROMPT_TEMPLATE_STABLE.format(
            preamble=rh.REVIEW_PREAMBLE, critical_calibration=rh.CRITICAL_FINDING_CALIBRATION,
            json_contract=u.REVIEW_JSON_ARRAY_CONTRACT, anti_pattern_lock_guard=rh.REPO_ANTI_PATTERN_LOCK_GUARD,
            checklist_section=checklist) + (f'\n{governance.stable_inline}\n' if governance.stable_inline.strip() else '')
        dynamic = (f'{tail}\n\n' if tail else '') + rv._REVIEW_PROMPT_TEMPLATE_DYNAMIC.format(
            goal_section=rh.build_goal_section(goal, scope, message, u.owner_words.owner_words_text(ctx)),
            scope_section=rh.build_scope_section(scope), current_files_section=files_section or '(no touched files could be read)',
            rebuttal_section=rh.build_rebuttal_section(rebuttal), review_history_section=history, diff_text=diff_text,
            changed_files='\n'.join(touched),
            task_evidence_section=u.review_evidence.commit_review_evidence_section({}, delivery='packet', compact=False))
        ctx._last_triad_models = models
        ctx._last_triad_governance_manifest = list(governance.manifest)
        return {'prompt': stable + '\n' + dynamic, 'stable_prefix_len': len(stable) + 1, 'models': models,
                'routes': row_plan['routes'], 'row_plan': row_plan, 'session_task': '', 'target_repo': str(R.worktree),
                'blocking_review': rh.review_enforcement_blocks(u.get_review_enforcement()), 'task_evidence': {},
                'governance_manifest': list(governance.manifest), 'governance_packet_slots': [s.slot_id for s in slots],
                'governance_retrieving_manifest': []}

    def _triad_transport(self, ctx, content='', prompt='', models=None, stable_prefix_len=0, row_plan=None, **kwargs):
        """Replaces tools/review_multi_model.py:129 _handle_multi_model_review (the substrate fan-out). Each
        packet row gets upstream's exact api messages (triad_api_messages) from the reviewer model role."""
        u = self.u
        messages, bible = u.review_multi_model.triad_api_messages(prompt, stable_prefix_len, content)
        system, user = _split_messages(messages)
        attempt = len(self.R.attempts)
        results = []
        for i, model in enumerate(models or []):
            slot = (row_plan or {}).get('slot_ids', [])[i] if i < len((row_plan or {}).get('slot_ids', [])) else f'row{i + 1}'
            try:
                text = self._model(system, user, f'review:a{attempt}:{slot}', role='reviewer')
                payload = {'choices': [{'message': {'content': text}}], 'usage': {}, 'slot_id': slot}
            except Exception as exc:   # a failed row is a typed error row, as in the substrate
                payload = {'error': f'Error: {exc}', 'usage': {}, 'slot_id': slot}
            results.append(u.review_response.parse_model_response(model, payload, None))
        return json.dumps({'model_count': len(models or []), 'constitutional_context': bool(bible), 'results': results},
                          ensure_ascii=False)

    # ---- result -------------------------------------------------------------------------------------
    @staticmethod
    def _read(path):
        try:
            return Path(path).read_text(encoding='utf-8')
        except (FileNotFoundError, IsADirectoryError):
            return None

    def _result(self, R):
        tasks = {t['id']: t for t in R.log['tasks']}
        tests = [tasks[t] for t in ('T1', 'T2') if t in tasks]
        learn = [tasks[t] for t in ('L1', 'L2') if t in tasks]

        def report(t):
            actions = '; '.join(f"{tool}({', '.join(f'{k}={json.dumps(v, ensure_ascii=False)[:80]}' for k, v in args.items() if k not in ('content',))})"
                                + (f' → {status}' if status else '') for tool, args, status, _code in t['calls']) or '(none)'
            diff = t['diff'] if len(t['diff']) < 3000 else t['diff'][:3000] + '\n… (diff truncated)'
            final = t['final'] if len(t['final']) < 2000 else t['final'][:2000] + ' … (truncated)'
            return (f"### {t['id']} in ~/src/{t['repo']}\nRequest: {t['request']}\nActions: {actions}\n"
                    f"Changes delivered (diff against the repository before the task):\n{diff or '(no changes)'}\n"
                    f"`make check` on the delivered state: {'PASS' if t['ci_pass'] else 'FAIL [' + t['ci_rule'] + ']'}\n"
                    f"Ouroboros's final message:\n{final or '(none)'}")
        evolution = R.log.get('evolution') or {}
        attempts = evolution.get('attempts') or []
        landed_diff = R.proposal['diff'] if R.landed and R.proposal else ''
        return {
            'output': '\n\n'.join(report(t) for t in tests),
            'learning': '\n\n'.join(report(t) for t in learn),
            'reflections': R.log['post'],
            'objective': (R.log.get('campaign') or {}).get('objective'),
            'evolution': evolution,
            'revision_landed': landed_diff,
            'proposal_reviewed': (R.proposal or {}).get('diff', ''),
            'owner_notices': R.log.get('owner_notices', []),
            'backbone_calls': [c['tag'] for c in R.calls],
            'metrics': {
                'test_ci_pass': sum(t['ci_pass'] for t in tests),
                'test_first_check_pass': sum(bool(t['check_runs']) and t['check_runs'][0] == 0 for t in tests),
                'test_failed_checks': sum(sum(1 for c in t['check_runs'] if c) for t in tests),
                'learn_ci_pass': sum(t['ci_pass'] for t in learn),
                'learn_failed_checks': sum(sum(1 for c in t['check_runs'] if c) for t in learn),
                'reflections': sum(1 for p in R.log['post'] if p['reflection']),
                'promoted': int(bool(R.log.get('promotion_applied'))),
                'plan_reviews': len((evolution.get('plan_reviews') or [])),
                'review_attempts': sum(a['paid'] for a in attempts),
                'review_passed': int(any(a.get('verdict') == 'passed' for a in attempts)),
                'revision_landed': int(R.landed),
                'backbone_calls': sum(c['role'] != 'reviewer' for c in R.calls),
                'reviewer_calls': sum(c['role'] == 'reviewer' for c in R.calls),
            },
        }
