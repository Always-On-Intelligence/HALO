"""HALO run-mode adapter for Vinci (OpenGVLab/vinci at commit a3b9dfa).

Configuration: the wearable, wake-word assistant served by vinci-inference, with periodic
timestamped activity memory and later history-aware answering; no chat-history backend
(Chat.use_chat_history stays False and the service never stores answers).

Each item is one egocentric stream: moments seen through the head-mounted camera, four frames each,
written as text, followed by questions the user asks after the wake word. The adapter calls the
service's own entry point, vinci-inference/app/models/internvl.chat, the way the backend does:
with silent=True at every moment (chat_unsafe_silent describes the user's action and the
(timestamp, description) pair is appended to the session history in history_cache), and with
silent=False for each question (chat_unsafe prepends the last ten history entries with
add_history and answers). The frame pre-processing (vl_open.dynamic_preprocess, build_transform),
the session clock, the history cache and all prompts run from the upstream code.

Replacements:
  Vinci-8B (InternVL chat model, vl_open.Chat: AutoModel.from_pretrained, model.chat) -> HALO
      backbone. Each 'FrameN: <image>' placeholder in the prompt is filled with the scripted text of
      that frame; the frames themselves are small placeholder images, so the pre-processing runs.
  The tokenizer (AutoTokenizer.from_pretrained) is not loaded; only the replaced model used it.
  IntervlChat is built on 'cpu' with stream=False (the module builds one per CUDA device, so none on
      this machine). Both branches of chat_unsafe build the same prompt (internvl.py:205-234); with
      stream=True the silent calls would also push their text into the shared TextIteratorStreamer,
      which the next streamed answer reads first.
  torch.Tensor.cuda is a no-op, because internvl.py:141 and :174 move pixel values to CUDA.
  The service clock (internvl.py:249-257 reads time.time()) follows the scripted moment times.
  The FastAPI layer (main.py, service/, util/) is not run; it only decodes frames and wraps replies.

Cut sites (upstream file:line):
  S->M  vinci-inference/app/models/internvl.py:146 (history.append in chat_unsafe_silent) and :279
        (history_cache.put): the silent description is returned but not added to the session history.
  M->A  vinci-inference/app/models/internvl.py:206  add_history(question, history, ...) receives an
        empty history, so the answer prompt carries no earlier descriptions.
"""
import contextlib, json, os, sys, tempfile, types, uuid
from pathlib import Path
from halo.run.adapter import BaseAdapter

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core'                         # vendored upstream code, see core/SOURCE.md
APP = CORE / 'vinci-inference' / 'app'
CLOCK_ORIGIN = 1_760_000_000                 # any epoch; only differences matter (internvl.get_timestamp)


@contextlib.contextmanager
def _replaced(cls, name, value):
    """Temporarily replace a class attribute (restores an inherited one by deleting the override)."""
    had, old = name in cls.__dict__, cls.__dict__.get(name)
    setattr(cls, name, value)
    try:
        yield
    finally:
        setattr(cls, name, old) if had else delattr(cls, name)


class _Tokenizer:
    """vl_open.Chat loads the Vinci-8B tokenizer; only the replaced model uses it."""


class _VinciModel:
    """Stands in for the Vinci-8B InternVL chat model returned by AutoModel.from_pretrained (vl_open.py:111)."""
    conv_template = types.SimpleNamespace(sep='<|im_end|>')

    def __init__(self, adapter):
        self.adapter = adapter

    def eval(self): return self
    def cuda(self, *a, **k): return self
    def state_dict(self): return {}

    def chat(self, tokenizer, pixel_values, question, generation_config, history=None, return_history=False,
             num_patches_list=None, **kwargs):
        reply = self.adapter._vlm(question, len(num_patches_list or []))
        if return_history:
            return reply, (history or []) + [(question, reply)]
        return reply


class Adapter(BaseAdapter):
    channels = {
        'S->M': 'silent timestamped activity descriptions are appended to the session history (internvl.py:146, 279)',
        'M->A': 'the last ten history entries are prepended to the question by add_history (internvl.py:206)',
    }
    steps = {}   # Vinci does not revise its own mechanism, so no evidence step is cut

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        self.cut, self.tag, self.stage, self._now, self._frame_texts, self._errors = set(), '', '', CLOCK_ORIGIN, [], []
        self.streams = {s['id']: s for s in json.loads((CASE / 'inputs' / 'streams.json').read_text())['streams']}
        os.chdir(tempfile.mkdtemp(prefix='halo-vinci-'))     # internvl.py:91 saves ./lastim.jpg
        import numpy as np, torch, transformers
        from PIL import Image
        self.np, self.Image = np, Image
        torch.Tensor.cuda = lambda t, *a, **k: t          # CPU only: internvl.py:141,174 call .cuda()
        sys.path[:0] = [str(APP), str(CORE)]
        from models import internvl                        # vinci-inference/app/models (imports vl_open from CORE)
        self.vi = internvl
        with _replaced(transformers.AutoModel, 'from_pretrained', staticmethod(lambda *a, **k: _VinciModel(self))), \
                _replaced(transformers.AutoTokenizer, 'from_pretrained', staticmethod(lambda *a, **k: _Tokenizer())):
            chat = internvl.IntervlChat(sep_chat=internvl.sep_chat, stream=False, device='cpu',
                                        language=internvl.running_language, version=internvl.version or 'v1')
        internvl.chats.append(chat)                        # model_index 0
        internvl.time = types.SimpleNamespace(time=lambda: self._now)   # service clock follows the stream
        # cut sites
        self._silent = chat.chat_unsafe_silent
        chat.chat_unsafe_silent = self._silent_write       # S->M
        self._add_history = internvl.add_history
        internvl.add_history = self._history_read          # M->A
        self.chat = chat

    # ---- cut sites ----------------------------------------------------------------------------
    def _silent_write(self, question, frames, history=[], timestamp=0):
        if 'S->M' in self.cut:
            response, _ = self._silent(question, frames, list(history), timestamp=timestamp)
            return response, history                       # the description is not admitted to the history
        return self._silent(question, frames, history, timestamp=timestamp)

    def _history_read(self, question, history, sep_chat=False, language='chn'):
        if 'M->A' in self.cut:
            history = []
        self.last_history = list(history or [])            # what reaches the answer prompt
        return self._add_history(question, history, sep_chat, language)

    # ---- model client ---------------------------------------------------------------------------
    def _vlm(self, question, n_frames):
        """model.chat of Vinci-8B: each <image> placeholder is filled with the frame's scripted text."""
        parts = question.split('<image>')
        text = parts[0]
        for i, rest in enumerate(parts[1:]):
            frame = self._frame_texts[i] if i < len(self._frame_texts) else 'unreadable frame'
            text += f'[image: {frame}]' + rest
        try:
            return self.llm('', text, tag=f'{self.tag}|{self.stage}')
        except Exception as e:                             # recorded so a swallowed failure still fails the run
            self._errors.append(f'{self.stage}: {type(e).__name__}: {e}')
            raise

    # ---- scripted sensing -----------------------------------------------------------------------
    def _frames(self, texts):
        """Frames as the service receives them (service/internvl.py decodes them to arrays)."""
        self._frame_texts = list(texts)
        return [self.np.array(self.Image.new('RGB', (64, 48), (90 + 20 * i, 110, 130))) for i in range(len(texts))]

    def _call(self, question, frames, silent, at, session):
        self._now = CLOCK_ORIGIN + at
        return self.vi.chat(question, self._frames(frames), [], session_id=session, silent=silent, model_index=0)

    # ---- items ----------------------------------------------------------------------------------
    def items(self):
        out = []
        for s in self.streams.values():
            lines = [f'Setting: {s["setting"]}', 'What the head-mounted camera saw:']
            lines += [f'At {m["time"]} s: ' + ' '.join(m['frames']) for m in s['moments']]
            lines.append('Questions the user asked after the wake word, with reference answers:')
            for i, q in enumerate(s['questions']):
                lines.append(f'Q{i + 1} (at {q["time"]} s, looking at: {" ".join(q["frames"])}): {q["question"]} Reference: {q["answer"]}')
            out.append({'id': s['id'], 'judge_context': '\n'.join(lines)})
        return out

    def run(self, item, cut, sample):
        stream = self.streams[item['id']]
        self.cut = set(cut)
        # The tag names the stream, the sample and the stage, not the arm: arms whose prompts are
        # identical share the cached reply, so each comparison differs only where the cut changes a prompt.
        self.tag, self._errors = f'{stream["id"]}|s{sample}', []
        session = f'{stream["id"]}-s{sample}-{uuid.uuid4().hex[:8]}'
        descriptions = []
        for m in stream['moments']:                        # the backend's periodic silent requests
            self.stage = f'silent|t{m["time"]}'
            response, _ = self._call('', m['frames'], True, m['time'], session)
            descriptions.append({'time': m['time'], 'description': response})
        answers, history_sizes = [], []
        for i, q in enumerate(stream['questions']):        # wake word, then the user's question
            self.stage, self.last_history = f'answer|q{i}', []
            answer, _ = self._call(q['question'], q['frames'], False, q['time'], session)
            answers.append(answer.strip() or '(no answer)')
            history_sizes.append(len(self.last_history))
        stored = self.vi.get_history(session)
        if self._errors:
            raise RuntimeError('backbone call failed: ' + self._errors[0])
        return {
            'output': '\n\n'.join(f'Q{i + 1}: {q["question"]}\nA{i + 1}: {a}' for i, (q, a) in enumerate(zip(stream['questions'], answers))),
            'answers': answers,
            'descriptions': descriptions,
            'history': [[t, d] for t, d in stored],
            'metrics': {
                'history_entries': len(stored),
                'history_entries_at_question': round(sum(history_sizes) / len(history_sizes), 4),
                'answer_chars': round(sum(len(a) for a in answers) / len(answers), 1),
            },
        }
