"""HALO run-mode adapter for Egocentric Co-Pilot (YoungSeng/Egocentric-Co-Pilot at commit 4bdc1c4).

Two parts of the released code run per item.

1. The orchestrator, LLM-Orchestrated-Neuro-Symbolic-Execution/main.py. Its module code runs from the
   unchanged file with two top-level statements skipped: the call that loads the local Whisper, F5-TTS
   and Qwen models (main.py:214-215), whose clients are replaced here. The adapter then plays the glasses
   front end (On-Device-Perception-and-Interaction/MainActivity.kt) against the real websocket_handler
   (main.py:811): JPEG frames every imageAnalysis_interval ms at imageAnalysis_quality, and utterances as
   audio messages that process_audio (main.py:697) handles: ASR, intent routing (prompt_refine,
   llm_intent.LLMInferenceUnified.analyze_input), the branch actions, TTS reply. The front end applies
   the parameter messages the backend sends (MainActivity.kt:246-253).
2. The reasoning core's HCC, Egocentric-Reasoning-Core/Egolife/scripts/eval_guide.py, run through its own
   main() on the day's event history (captions file and SRT transcripts in the EgoLife layout it reads):
   query-aware hourly summaries of older events plus the 50 most recent events, then a multiple-choice
   answer.

Replacements: every model goes to the HALO backbone or is a scripted stand-in.
  - Qwen2-VL (main.inference_llm) and the Qwen intent LLM (LLMInferenceUnified.generate_response):
    backbone; images and frame lists become the scripted text of each frame.
  - Whisper (main.ASR_model): returns the scripted utterance carried in the audio message.
  - F5-TTS (main.process_tts): the reply text itself is "spoken" to the front end.
  - paraphrase-multilingual-MiniLM-L12-v2 (intent templates): all-MiniLM-L6-v2 on CPU.
  - The HCC script's Qwen2.5 LLM (AutoModelForCausalLM/AutoTokenizer in eval_guide): a tokenizer/model
    pair that sends each chat to the backbone.
  - Camera: scripted frames; the front end reads fine print only when imageAnalysis_quality >= 50
    (stand-in for JPEG quality 80 versus 25).

Cut sites (receiving end):
  S->M  main.py:337 CustomQueue.put (image_queue, filled at main.py:830) keeps only the newest frame,
        so the buffer retains no history (the latest frame, S->A, is still there);
        eval_guide.py:84 load_and_merge_all_data returns no events (nothing enters the event history).
  M->A  main.py:346 CustomQueue.get_all returns no frames to the memory branch (main.py:741);
        eval_guide.py:162 get_answer_from_llm receives no context items (summaries and recent events).
  A->S  the front end ignores the frame interval and quality message that send_text_parameters
        (main.py:675, sent at :752 and :761) delivers (MainActivity.kt:246-253).
Egocentric Co-Pilot does not revise its own mechanism, so no evidence step is cut.
"""
import ast, asyncio, base64, hashlib, io, json, os, re, shutil, sys, tempfile, threading, types, wave
from pathlib import Path

from halo.run.adapter import BaseAdapter

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core'                     # vendored upstream code, see core/SOURCE.md
ORCH = CORE / 'LLM-Orchestrated-Neuro-Symbolic-Execution'
HCC = CORE / 'Egocentric-Reasoning-Core' / 'Egolife' / 'scripts'
INTENT_MODEL = 'Qwen/Qwen2.5-0.5B-Instruct'   # main.py CONFIG["MODELS"]["INTENTION"] (replaced)
PARTICIPANT = 'A1_JAKE'                   # eval_guide.py default --participant_id
CAMERA_TICK_MS = 33                       # the camera delivers ~30 fps; MainActivity sends one frame per interval
FINE_PRINT_QUALITY = 50
IMAGE, AUDIO = (1).to_bytes(4, 'big'), (0).to_bytes(4, 'big')   # main.py identify_data_type headers


class Adapter(BaseAdapter):
    channels = {
        'S->M': 'frames retained in the orchestrator frame buffer (image_queue); caption and speech events admitted to the HCC event history',
        'M->A': 'retained frames delivered to the memory-query branch; HCC summaries and recent events delivered to the answer',
        'A->S': 'the interaction mode sets the glasses frame interval and JPEG quality (send_text_parameters)',
    }
    steps = {}   # no self-revision

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        self.cut, self.tag, self.stage = set(), '', ''
        self.frames_by_hash = {}
        self.calls = 0
        self.items_data = {s['id']: s for s in json.loads((Path(case_dir) / 'inputs' / 'sessions.json').read_text())['sessions']}
        self._install_stubs()
        sys.path.insert(0, str(ORCH))
        import llm_intent, api_providers
        self.llm_intent, self.api_providers = llm_intent, api_providers
        self._patch_intent_model()
        self.text_based_llm = llm_intent.LLMInferenceUnified(model_name=INTENT_MODEL)
        tree = ast.parse((ORCH / 'main.py').read_text())
        body = [n for n in tree.body if not _calls_load_local_models(n)]
        assert len(body) == len(tree.body) - 1, 'expected exactly one load_local_models() statement'
        self.main_code = compile(ast.Module(body=body, type_ignores=[]), str(ORCH / 'main.py'), 'exec')
        self._import_hcc()

    # ---- model clients -> HALO backbone --------------------------------------------------------
    def _ask(self, system, user):
        self.calls += 1
        return self.llm(system, user, tag=f'{self.tag}|{self.stage}')

    def _frame_text(self, url):
        try:
            raw = base64.b64decode(str(url).split(',', 1)[1])
            return self.frames_by_hash.get(hashlib.sha256(raw).hexdigest()) or 'not available'
        except Exception:
            return 'not available'

    def _vlm(self, messages, mode='image'):
        """main.inference_llm: Qwen2-VL chat with images or a frame list ('video')."""
        system, parts = [], []
        for m in messages:
            content = m['content']
            if m['role'] == 'system':
                system.append(content if isinstance(content, str) else json.dumps(content)); continue
            for p in ([{'type': 'text', 'text': content}] if isinstance(content, str) else content):
                if p.get('type') == 'image':
                    parts.append(f'[Image: {self._frame_text(p["image"])}]')
                elif p.get('type') == 'video':
                    frames = list(p.get('video') or [])
                    lines = [f'{i + 1}. {self._frame_text(f)}' for i, f in enumerate(frames)]
                    parts.append(f'[Video, {len(frames)} frames at {p.get("fps", 2.0)} fps]\n' + ('\n'.join(lines) or '(no frames)'))
                elif p.get('type') == 'text':
                    parts.append(p['text'])
        return self._ask('\n\n'.join(system), '\n\n'.join(parts)).strip()

    def _patch_intent_model(self):
        adapter, li = self, self.llm_intent

        class _Stub:
            @classmethod
            def from_pretrained(cls, *a, **k):
                return cls()

            def to(self, *a, **k):
                return self

        li.AutoTokenizer, li.AutoModelForCausalLM = _Stub, _Stub
        from sentence_transformers import SentenceTransformer
        li.SentenceTransformer = lambda name, *a, **k: SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', device='cpu')

        def generate_response(self, messages):
            system = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
            user = '\n'.join(m['content'] for m in messages if m['role'] != 'system')
            return adapter._ask(system, user).strip()

        li.LLMInferenceUnified.generate_response = generate_response

    def _install_stubs(self):
        # cached_path is only used to download TTS checkpoints, which this run does not load.
        mod = types.ModuleType('cached_path')
        mod.cached_path = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('no downloads in HALO runs'))
        sys.modules.setdefault('cached_path', mod)
        # api_providers.openai_API (used by main.py's piece-tracking branch) goes to the backbone.
        import openai
        adapter = self

        class _Completions:
            def create(self, **kw):
                system, parts = [], []
                for m in kw.get('messages') or []:
                    c = m.get('content')
                    if m.get('role') == 'system':
                        system.append(c if isinstance(c, str) else json.dumps(c)); continue
                    for p in ([{'type': 'text', 'text': c}] if isinstance(c, str) else c or []):
                        if p.get('type') == 'image_url':
                            parts.append(f'[Image: {adapter._frame_text(p["image_url"]["url"])}]')
                        else:
                            parts.append(str(p.get('text') or ''))
                text = adapter._ask('\n'.join(system), '\n'.join(parts))
                msg = types.SimpleNamespace(content=text, role='assistant')
                return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, index=0, finish_reason='stop')])

        class _OpenAI:
            def __init__(self, *a, **k):
                self.chat = types.SimpleNamespace(completions=_Completions())

        openai.OpenAI = _OpenAI

    def _import_hcc(self):
        adapter = self
        old = os.getcwd()
        os.chdir(tempfile.mkdtemp(prefix='ecp-hcc-import-'))   # config.py creates ./outputs on import
        try:
            sys.path.insert(0, str(HCC))
            import eval_guide
        finally:
            os.chdir(old)
        self.hcc = eval_guide

        class _Ids:
            def __init__(self, prompt):
                self.prompt, self.shape = prompt, (1, 0)

        class _Enc(dict):
            def __init__(self, prompt):
                super().__init__(input_ids=_Ids(prompt))

            @property
            def input_ids(self):
                return self['input_ids']

            def to(self, *a, **k):
                return self

        class _Gen:
            def __init__(self, text):
                self.text = text

            def __getitem__(self, key):
                return self

        class _Tok:
            @classmethod
            def from_pretrained(cls, *a, **k):
                return cls()

            def apply_chat_template(self, msgs, tokenize=False, add_generation_prompt=True):
                return json.dumps(msgs)

            def __call__(self, texts, return_tensors=None):
                return _Enc(texts[0])

            def batch_decode(self, gen, skip_special_tokens=True):
                return [gen.text]

        class _Model:
            device = 'cpu'

            @classmethod
            def from_pretrained(cls, *a, **k):
                return cls()

            def generate(self, input_ids=None, **kw):
                msgs = json.loads(input_ids.prompt)
                system = '\n'.join(m['content'] for m in msgs if m['role'] == 'system')
                user = '\n'.join(m['content'] for m in msgs if m['role'] != 'system')
                return _Gen(adapter._ask(system, user))

        eval_guide.AutoTokenizer, eval_guide.AutoModelForCausalLM = _Tok, _Model
        orig_load, orig_answer = eval_guide.load_and_merge_all_data, eval_guide.get_answer_from_llm

        def load(captions_filepath, asr_base_path, target_participant):
            events = orig_load(captions_filepath, asr_base_path, target_participant)
            return [] if 'S->M' in adapter.cut else events      # cut S->M: nothing enters the event history

        def answer(model, tokenizer, question_data, context_items, method='direct'):
            adapter.stage = 'hcc-answer'
            if 'M->A' in adapter.cut:
                context_items = []                               # cut M->A: no history reaches the answer
            return orig_answer(model, tokenizer, question_data, context_items, method)

        eval_guide.load_and_merge_all_data, eval_guide.get_answer_from_llm = load, answer

    # ---- the orchestrator ---------------------------------------------------------------------
    def _load_main(self, root):
        """Run main.py's module code (minus the local model loading) in a fresh namespace."""
        ns = {'__name__': 'egocentric_copilot_main', '__file__': str(root / 'main.py'), '__builtins__': __builtins__}
        exec(self.main_code, ns)
        adapter, li = self, self.llm_intent
        ns['LLMInferenceUnified'] = li.LLMInferenceUnified        # main's try-import stops at chess_engine (no YOLO)
        ns['openai_API'], ns['siliconflow_API'] = self.api_providers.openai_API, self.api_providers.siliconflow_API
        ns['text_based_llm'] = self.text_based_llm                # what load_local_models() would set
        ns['INTENT_EMBEDDINGS'] = self.text_based_llm.INTENT_EMBEDDINGS   # what main's __main__ block sets
        ns['my_Chinese_Chessboard'] = None
        ns['inference_llm'] = self._vlm

        class _ASR:   # Whisper: the scripted utterance travels in the audio payload
            def transcribe(self, filepath, language='en'):
                with wave.open(filepath, 'rb') as w:
                    raw = w.readframes(w.getnframes())
                return {'text': raw.rstrip(b'\x00').decode('utf-8')}

        ns['ASR_model'] = _ASR()

        def process_tts(output_text):   # F5-TTS: the front end receives the reply text
            path = os.path.join(ns['OUTPUT_DIR'], f'tts_{len(os.listdir(ns["OUTPUT_DIR"]))}.txt')
            Path(path).write_text(output_text, encoding='utf-8')
            return path

        ns['process_tts'] = process_tts
        q = ns['image_queue']
        orig_put, orig_get_all = q.put, q.get_all

        def put(item):
            if 'S->M' in adapter.cut:
                q.queue.clear()          # cut S->M: the buffer keeps the current frame only
            orig_put(item)

        def get_all(timestamp_tracking=None):
            if 'M->A' in adapter.cut:
                return []                # cut M->A: the memory branch receives no retained frames
            return orig_get_all(timestamp_tracking)

        q.put, q.get_all = put, get_all
        return ns

    async def _session(self, ns, sess, log):
        adapter = self
        front = {'interval': 200, 'quality': 25}   # MainActivity.kt:98-99 defaults

        class Socket:
            def __init__(self):
                self.inbox = asyncio.Queue()

            def __aiter__(self):
                return self

            async def __anext__(self):
                msg = await self.inbox.get()
                if msg is None:
                    raise StopAsyncIteration
                return msg

            async def send(self, msg):
                if isinstance(msg, str):
                    params = json.loads(msg)
                    log.append({'t': round(clock / 1000, 2), 'event': 'parameters', 'params': params,
                                'applied': 'A->S' not in adapter.cut})
                    if 'A->S' not in adapter.cut:     # MainActivity.kt:250-252
                        front['interval'] = params['imageAnalysis_interval']
                        front['quality'] = params['imageAnalysis_quality']
                else:
                    log.append({'t': round(clock / 1000, 2), 'event': 'reply', 'text': msg.decode('utf-8')})

        sock = Socket()
        handler = asyncio.create_task(ns['websocket_handler'](sock, '/'))
        utterances = sorted(sess['utterances'], key=lambda u: u['t'])
        end_ms = int(sess['duration_s'] * 1000)
        clock, last_frame, frame_index, ui = 0, -10 ** 9, 0, 0
        while clock <= end_ms:
            if clock - last_frame > front['interval']:          # MainActivity.kt:379-386 shouldSendFrame
                text = _view(sess['segments'], clock / 1000, front['quality'])
                jpg = _jpeg(text, frame_index, front['quality'])
                self.frames_by_hash[hashlib.sha256(jpg).hexdigest()] = text
                await sock.inbox.put(IMAGE + jpg)
                last_frame, frame_index = clock, frame_index + 1
                await asyncio.sleep(0)
            while ui < len(utterances) and utterances[ui]['t'] * 1000 <= clock:
                u = utterances[ui]
                self.stage = f'turn{ui + 1}'
                log.append({'t': u['t'], 'event': 'user', 'text': u['text'], 'turn': ui + 1})
                payload = u['text'].encode('utf-8')
                payload += b'\x00' * (len(payload) % 2)
                await sock.inbox.put(AUDIO + payload)
                while not sock.inbox.empty():   # the handler has taken the message and started process_audio
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0.05)
                while any(t.get_coro().__name__ == 'process_audio' and not t.done() for t in asyncio.all_tasks()):
                    await asyncio.sleep(0.05)   # the wearer waits for the reply before going on
                ui += 1
            clock += CAMERA_TICK_MS
        await sock.inbox.put(None)
        await handler
        log.append({'event': 'frames_sent', 'count': frame_index, 'buffer_frames': len(ns['image_queue'].queue),
                    'final_interval': front['interval'], 'final_quality': front['quality']})

    # ---- HCC on the day's event history ---------------------------------------------------------
    def _run_hcc(self, root, sess):
        day = sess['history']
        data, asr = root / 'hcc', root / 'hcc' / 'asr' / PARTICIPANT / 'DAY1'
        asr.mkdir(parents=True)
        captions = {}
        for block in day['blocks']:
            h0, m0 = map(int, block['from'].split(':')); h1, m1 = map(int, block['to'].split(':'))
            t, k = h0 * 3600 + m0 * 60, 0
            while t < h1 * 3600 + m1 * 60:
                hh, mm, ss = t // 3600, t % 3600 // 60, t % 60
                captions[f'DAY1_{PARTICIPANT}_{hh:02d}{mm:02d}{ss:02d}00.mp4'] = block['captions'][k % len(block['captions'])]
                t, k = t + 30, k + 1
        for key, text in day.get('key_captions', {}).items():
            captions[f'DAY1_{PARTICIPANT}_{key.replace(":", "")}00.mp4'] = text
        (data / 'captions.json').write_text(json.dumps(captions, ensure_ascii=False, indent=1))
        by_hour = {}
        for sp in day.get('speech', []):
            hh, mm, ss = map(int, sp['time'].split(':'))
            by_hour.setdefault(hh, []).append((mm, ss, sp['text']))
        for hh, lines in by_hour.items():   # one SRT per hour, times relative to the hour (generate_asr.py layout)
            srt = [f'{i + 1}\n00:{mm:02d}:{ss:02d},000 --> 00:{mm:02d}:{min(ss + 5, 59):02d},000\n{text}\n'
                   for i, (mm, ss, text) in enumerate(sorted(lines))]
            (asr / f'DAY1_{PARTICIPANT}_{hh:02d}000000.srt').write_text('\n'.join(srt))
        q = day['question']
        (data / 'questions.json').write_text(json.dumps({'results': [{'metadata': {
            'question': q['question'], 'choice_a': q['choices'][0], 'choice_b': q['choices'][1],
            'choice_c': q['choices'][2], 'choice_d': q['choices'][3], 'answer': q['answer'],
            'query_time': {'date': 'DAY1', 'time': q['time'].replace(':', '') + '00'}}}]}))
        argv = sys.argv
        sys.argv = ['eval_guide.py', '--results_file', str(data / 'questions.json'), '--captions_file', str(data / 'captions.json'),
                    '--asr_base_path', str(data / 'asr'), '--llm_path', 'Qwen/Qwen2.5-7B-Instruct',
                    '--output_dir', str(data / 'out'), '--participant_id', PARTICIPANT]
        self.stage = 'hcc-summary'
        try:
            self.hcc.main()
        finally:
            sys.argv = argv
        outs = sorted((data / 'out').glob('eval_guide_*.json')) if (data / 'out').exists() else []
        if not outs:
            return None, {'events': 0}
        details = json.loads(outs[-1].read_text())['results'][0]['new_llm_answer_details']
        letter = details['choice']
        text = q['choices']['ABCD'.index(letter)] if letter in 'ABCD' else 'no option'
        return f'{letter}. {text}', {'events': len(captions) + sum(len(v) for v in by_hour.values()),
                                     'method': details['method'], 'correct': int(bool(details['correct']))}

    # ---- one item -------------------------------------------------------------------------------
    def items(self):
        return [{'id': s['id'], 'judge_context': _situation(s)} for s in self.items_data.values()]

    def run(self, item, cut, sample):
        sess = self.items_data[item['id']]
        self.cut = set(cut)
        # The tag names the item and the sample, not the arm, so arms with identical prompts share replies.
        self.tag = f'{sess["id"]}|s{sample}'
        self.calls = 0
        root = Path(tempfile.mkdtemp(prefix=f'ecp-{sess["id"]}-'))
        old_cwd = os.getcwd()
        os.chdir(root)
        try:
            ns = self._load_main(root)
            log = []
            asyncio.run(self._session(ns, sess, log))
            replies = {}
            turn = 0
            for e in log:
                if e['event'] == 'user':
                    turn = e['turn']
                elif e['event'] == 'reply':
                    replies.setdefault(turn, []).append(e['text'])
            label_turn, memory_turn = sess['label_turn'], sess['memory_turn']
            hcc_answer, hcc_info = self._run_hcc(root, sess)
            q = sess['history']['question']
            out = {
                'output': ' / '.join(replies.get(label_turn, [])) or '(no reply)',
                'output_memory': ' / '.join(replies.get(memory_turn, [])) or '(no reply)',
                'output_hcc': hcc_answer or '(no answer: the event history is empty)',
                'context_memory': _situation(sess, turn=memory_turn),
                'context_hcc': _hcc_situation(sess),
                'log': log,
                'hcc': hcc_info,
                'metrics': {
                    'replies': sum(len(v) for v in replies.values()),
                    'final_quality': next(e['final_quality'] for e in log if e['event'] == 'frames_sent'),
                    'buffer_frames': next(e['buffer_frames'] for e in log if e['event'] == 'frames_sent'),
                    'label_fact_recall': _recall(' '.join(replies.get(label_turn, [])), sess.get('label_expect', [])),
                    'memory_fact_recall': _recall(' '.join(replies.get(memory_turn, [])), sess.get('memory_expect', [])),
                    'hcc_correct': hcc_info.get('correct', 0),
                    'model_calls': self.calls,
                },
            }
            return out
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(root, ignore_errors=True)


def _calls_load_local_models(node):
    """main.py:214-215 `if not Using_remote_server: load_local_models()`."""
    return isinstance(node, ast.If) and any(
        isinstance(n, ast.Call) and getattr(n.func, 'id', None) == 'load_local_models' for n in ast.walk(node))


def _view(segments, t, quality):
    for seg in segments:
        if seg['start'] <= t < seg['end']:
            text = seg['view']
            if seg.get('fine'):
                text += ' ' + (seg['fine'] if quality >= FINE_PRINT_QUALITY else seg.get('fine_blurred', 'Small print is visible but too blurry to read.'))
            return text
    return segments[-1]['view']


def _jpeg(text, index, quality):
    """A distinct JPEG per frame at the front end's quality; its content reaches the model as text."""
    from PIL import Image, ImageDraw
    h = int(hashlib.sha256(text.encode()).hexdigest()[:6], 16)
    img = Image.new('RGB', (320, 240), ((h >> 16) & 255, (h >> 8) & 255, h & 255))
    d = ImageDraw.Draw(img)
    for bit in range(12):
        d.rectangle([4 + bit * 12, 4, 13 + bit * 12, 13], fill=(255, 255, 255) if (index >> bit) & 1 else (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=int(quality))
    return buf.getvalue()


def _recall(answer, expect):
    if not expect:
        return None
    a = (answer or '').lower()
    return round(sum(1 for e in expect if str(e).lower() in a) / len(expect), 3)


def _situation(s, turn=None):
    lines = [s['situation'], '', 'What happened in the live session (ground truth, not shown to the assistant):']
    for seg in s['segments']:
        lines.append(f'- {seg["start"]:.0f}-{seg["end"]:.0f} s: {seg["summary"]}')
    lines.append('')
    lines.append('What the wearer said:')
    for i, u in enumerate(sorted(s['utterances'], key=lambda u: u['t'])):
        lines.append(f'- turn {i + 1} at {u["t"]:.0f} s: "{u["text"]}"')
    turn = turn or s['label_turn']
    lines.append('')
    lines.append(f'The output to compare is the assistant\'s reply to turn {turn}.')
    return '\n'.join(lines)


def _hcc_situation(s):
    h = s['history']
    q = h['question']
    return '\n'.join([s['situation'], '', 'Key events of the day so far (ground truth):'] + [f'- {x}' for x in h['summary']] + [
        '', f'At {q["time"]} the wearer asks: "{q["question"]}"',
        'Options: ' + '; '.join(f'{"ABCD"[i]}. {c}' for i, c in enumerate(q['choices'])),
        f'Correct option: {q["answer"]}. The output is the option the assistant chose.'])
