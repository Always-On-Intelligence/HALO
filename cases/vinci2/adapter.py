"""HALO run-mode adapter for Vinci2 / EgoMemo (SitongGong/EgoMemo at commit 0029a33).

Configuration: EgoMemo's streaming proactive service (egomemo_demo), with GPT-5-mini as the
reasoning model, as launched by egomemo/run.py (v2 reasoning, fast memory read, trimmed entity
prompt), with the three-level memory switched on and no user questions.

Each item is one egocentric session: 30-second windows of six frames sampled every 5 seconds,
written as text. The adapter runs the upstream CLI entry point, egomemo/run.main, with these
arguments (the rest are run.py's defaults):
    --video_path <placeholder> --working_dir <run dir> --multi_level_caption --caption_window_minutes 1
so caption_model=qwen_vllm, reasoning_model_path=gpt-5-mini, datasets_type=egolife,
step_interval=5, caption_window=30, caption_window_hours=1, proactive_cooldown=5,
pipeline_mode=async, questions=[]. For every window the memory side (MemoryBridge.build_step) writes
the clip caption to the text-chunk store, extracts entities and relations into the knowledge
graph, stores a visual embedding, and every minute summarises the clip captions into an activity
caption (sessions summaries need an hour and are only flushed when the stream ends). The
reasoning side (StreamingPipeline._reason_and_route -> pipeline_v2_patch._reason_proactive_v2)
decides [silent], [search] <query> or [respond] <reminder> (the decision d_t and response r_t);
a search reads memory (memory_bridge_fast._fast_read) and a second pass decides again.

Replacements (everything else runs from core/):
  caption model, Qwen3-VL-8B served by vLLM (videorag/llm/qwen3vl_vllm.mllm_response) -> HALO
      backbone; each frame is given as its scripted text. Also writes the activity and session captions.
  reasoning model, GPT-5-mini (StreamingPipeline._call_api_reasoning) -> HALO backbone.
  gpt-4o-mini (videorag/_llm.gpt_4o_mini_complete: entity extraction, retrieval-query rewriting)
      -> HALO backbone.
  text-embedding-3-small (videorag/_llm.openai_embedding) -> all-MiniLM-L6-v2, zero-padded to the
      1536 dimensions the stores are built with (cosine similarity is unchanged).
  ImageBind (vdb_nanovectordb: _get_embedder, the video pre-processing that needs pytorchvideo,
      encode_string_query) -> all-MiniLM-L6-v2 on the frames' scripted text and on the query,
      zero-padded to 1024 dimensions.
  tiktoken's o200k_base data is downloaded on first use, which is not possible offline; a local
      word-and-punctuation tokenizer stands in. Token counts only gate truncation limits that
      these short sessions never reach.
  Video decoding (streaming_pipeline.sample_frames_by_interval) returns placeholder images for the
      scripted frames. Libraries used only by replaced or unused paths are stubbed (ollama, neo4j,
      hnswlib, xxhash, faster_whisper, qwen_vl_utils, moviepy, decord, cv2).
  pipeline_mode=async runs memory construction in a background thread that may run ahead of
      reasoning (streaming_pipeline.py:563-671). The adapter runs the same two loop bodies in
      lockstep (memory for window i, then reasoning for window i), so later windows never leak
      into earlier decisions and runs are reproducible.

Cut sites (upstream file:line):
  S->M  egomemo/memory_bridge.py:227-346 (MemoryBridge.build_step): the clip caption is generated
        and still reaches the reasoner as the current observation, but no store admits it:
        :262 _store_frames (video segments), :313 ainsert_streaming_caption (text chunks and the
        knowledge graph, videorag/egograph_retrieval_optimize_.py:2994), :326 _insert_visual_embedding,
        :337 self._captions.append, :344 _accumulate_multi_level (activity and session captions).
  M->A  egomemo/pipeline_v2_patch.py:680-685, 688-697 and 778 (in _reason_proactive_v2): the reasoner
        reads an empty memory: no caption time ranges, no recent activity caption, and memory.read
        returns the store's empty-result message.
  A->M  egomemo/pipeline_v2_patch.py:771-775 and 850-856: the reasoner's own reminders, search
        requests and their times (_proactive_history, _last_proactive_search,
        _last_proactive_time_by_kind) are not kept for later windows.
"""
import base64, io, json, os, re, sys, tempfile, time, types, uuid
from pathlib import Path
import numpy as np
from halo.run.adapter import BaseAdapter

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core'                         # vendored upstream code, see core/SOURCE.md
TEXT_DIM, VISUAL_DIM = 1536, 1024            # text-embedding-3-small and ImageBind sizes of the stores
WINDOW = 30                                  # run.py --caption_window default
CLI_ARGS = ['--multi_level_caption', '--caption_window_minutes', '1']


class _Encoding:
    """Stands in for tiktoken's o200k_base (its data file is downloaded on first use)."""
    _ids, _pieces = {}, []

    def encode(self, text, **kwargs):
        out = []
        for piece in re.findall(r'\s*\w+|\s*[^\w\s]|\s+$', text):
            if piece not in self._ids:
                self._ids[piece] = len(self._pieces); self._pieces.append(piece)
            out.append(self._ids[piece])
        return out

    def encode_batch(self, texts, num_threads=8, **kwargs):
        return [self.encode(t) for t in texts]

    def decode(self, tokens, **kwargs):
        return ''.join(self._pieces[t] for t in tokens)


class _Inert:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): raise RuntimeError('replaced in HALO run mode')


class _VisualEncoder:
    """Stands in for ImageBind (imagebind_huge): MiniLM on the frames' scripted text."""
    def __init__(self, adapter):
        import torch
        self.adapter, self._param = adapter, torch.zeros(1)

    def parameters(self): return iter([self._param])
    def eval(self): return self

    def __call__(self, inputs):
        import torch
        (modality, texts), = inputs.items()
        vec = self.adapter._pad(self.adapter._embed([' '.join(texts)])[0], VISUAL_DIM)
        return {modality: torch.tensor(np.array([vec], dtype=np.float32))}


class _Withheld:
    """The memory the reasoner reads under the M->A cut: empty."""
    def __init__(self, real, empty_result, log):
        self._real, self._empty, self._log = real, empty_result, log
        self._captions, self._min_captions, self._hour_captions = [], [], []

    def read(self, query, current_time_span, *a, **k):
        self._log(query)
        return self._empty
    def format_recent_history(self, n=3): return '(no prior observations)'
    def format_recent_history_before(self, current_time_span, n=3): return '(no prior observations)'
    def get_recent_captions(self, n=3): return []
    def get_all_captions(self): return []
    def __getattr__(self, name): return getattr(self._real, name)


class Adapter(BaseAdapter):
    channels = {
        'S->M': 'clip captions, entities and relations, visual embeddings and activity captions are written to memory (memory_bridge.py:262-344)',
        'M->A': 'memory reaches the proactive reasoner: retrieval, the recent activity caption and the caption time ranges (pipeline_v2_patch.py:680-697, 778)',
        'A->M': "the reasoner's own reminders and search requests are kept and shown to it in later windows (pipeline_v2_patch.py:771-775, 850-856)",
    }
    steps = {}   # EgoMemo does not revise its own mechanism, so no evidence step is cut

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        self.cut, self.tag, self._window, self._frames_now, self.pipeline, self._errors = set(), '', 0, [], None, []
        self.sessions = {s['id']: s for s in json.loads((CASE / 'inputs' / 'sessions.json').read_text())['sessions']}
        self.root = Path(tempfile.mkdtemp(prefix='halo-egomemo-'))
        os.chdir(self.root)
        from sentence_transformers import SentenceTransformer
        self.minilm, self._vectors, self._frame_text = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', device='cpu'), {}, {}
        self._install_stubs()
        sys.path.insert(0, str(CORE))
        import egomemo.run as cli                          # applies run.py's three patches (v2, fast read, trimmed prompt)
        from egomemo import streaming_pipeline as sp, memory_bridge as mb
        from videorag import egograph_retrieval_optimize_ as eg
        from videorag._storage import vdb_nanovectordb as vdb
        from videorag.ego_prompt_ import PROMPTS
        self.cli, self.sp, self.mb = cli, sp, mb
        adapter = self
        # model clients -> HALO backbone / MiniLM. Plain functions, as upstream: the LLM config is
        # deep-copied by dataclasses.asdict, which copies a bound method's instance but not a function.
        async def gpt_4o_mini_complete(model_name, prompt, system_prompt=None, history_messages=[], **kwargs):
            return adapter._gpt_4o_mini(prompt, system_prompt, history_messages)

        async def openai_embedding(model_name, texts):
            return np.array([adapter._pad(v, TEXT_DIM) for v in adapter._embed(list(texts))])
        sp.gpt_4o_mini_complete = gpt_4o_mini_complete     # read by create_default_llm_config at call time
        sp.openai_embedding = openai_embedding
        sp.StreamingPipeline._call_api_reasoning = lambda p, prompt, history_messages=None: adapter._reasoner(prompt, history_messages)
        vdb.NanoVectorDBVideoSegmentStorage._get_embedder = lambda store: adapter._visual
        vdb.NanoVectorDBVideoSegmentStorage._load_and_transform_base64_images_as_video = \
            lambda store, frames, device: [adapter._frame_text.get(f, '') for f in frames]
        vdb.encode_string_query = lambda query, embedder: np.array([self._pad(self._embed([query])[0], VISUAL_DIM)], dtype=np.float32)
        self._visual = _VisualEncoder(self)
        # sensor input -> scripted frames; async loops -> lockstep
        sp.sample_frames_by_interval = self._sample_frames
        sp.StreamingPipeline._run_async_mode = lambda p, batches: adapter._lockstep(p, batches)
        # cut sites
        self._cut_memory_writes(mb, eg)                                       # S->M
        rr = sp.StreamingPipeline._reason_and_route
        empty = PROMPTS['fail_response']

        def reason_and_route(p, *a, **k):                                     # M->A
            if 'M->A' not in adapter.cut:
                return rr(p, *a, **k)
            real, p.memory = p.memory, _Withheld(p.memory, empty, lambda q: adapter._searches.append({'window': adapter._window, 'query': q}))
            try:
                return rr(p, *a, **k)
            finally:
                p.memory = real
        sp.StreamingPipeline._reason_and_route = reason_and_route
        rp = sp.StreamingPipeline._reason_proactive                          # pipeline_v2_patch._reason_proactive_v2

        def reason_proactive(p, *a, **k):                                     # A->M
            if 'A->M' not in adapter.cut:
                return rp(p, *a, **k)
            kept = (list(p._proactive_history), p.__dict__.get('_last_proactive_search'),
                    dict(p._last_proactive_time_by_kind), p._last_proactive_time)
            try:
                return rp(p, *a, **k)
            finally:
                p._proactive_history[:] = kept[0]
                p.__dict__['_last_proactive_search'] = kept[1]
                p._last_proactive_time_by_kind.clear(); p._last_proactive_time_by_kind.update(kept[2])
                p._last_proactive_time = kept[3]
        sp.StreamingPipeline._reason_proactive = reason_proactive
        read = mb.MemoryBridge.read                                           # memory_bridge_fast._fast_read

        def logged_read(bridge, query, current_time_span, *a, **k):          # observation only
            adapter._searches.append({'window': adapter._window, 'query': query})
            return read(bridge, query, current_time_span, *a, **k)
        mb.MemoryBridge.read = logged_read

    def _install_stubs(self):
        def module(name, **attrs):
            m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m
        module('tiktoken', encoding_for_model=lambda name: _Encoding(), get_encoding=lambda name: _Encoding(), Encoding=_Encoding)
        module('ollama', AsyncClient=_Inert); module('neo4j', AsyncGraphDatabase=_Inert)
        module('hnswlib', Index=_Inert); module('xxhash', xxh32_intdigest=_Inert())
        module('faster_whisper', WhisperModel=_Inert); module('qwen_vl_utils', process_vision_info=_Inert())
        module('moviepy'); module('moviepy.editor', VideoFileClip=_Inert); module('moviepy.video')
        module('moviepy.video.io'); module('moviepy.video.io.VideoFileClip', VideoFileClip=_Inert); module('moviepy.video.fx')
        module('decord', VideoReader=_Inert, cpu=_Inert()); module('cv2')
        adapter = self

        def mllm_response(*args, **kwargs):
            return adapter._caption_model(*args, **kwargs)
        module('videorag.llm.qwen3vl_vllm', mllm_response=mllm_response)        # the vLLM caption client

    def _cut_memory_writes(self, mb, eg):
        """S->M: the receiving stores of MemoryBridge.build_step admit nothing."""
        adapter = self

        def gate(fn):
            def wrapped(bridge, *a, **k):
                return None if 'S->M' in adapter.cut else fn(bridge, *a, **k)
            return wrapped
        for name in ('_store_frames', '_insert_visual_embedding', '_accumulate_multi_level'):
            setattr(mb.MemoryBridge, name, gate(getattr(mb.MemoryBridge, name)))
        insert = eg.VideoGraphSeparated.ainsert_streaming_caption

        async def ainsert(vg, *a, **k):
            return None if 'S->M' in adapter.cut else await insert(vg, *a, **k)
        eg.VideoGraphSeparated.ainsert_streaming_caption = ainsert

        class Admitted(list):
            def append(self, item):
                if 'S->M' not in adapter.cut:
                    super().append(item)
        init = mb.MemoryBridge.__init__

        def bridge_init(bridge, *a, **k):
            init(bridge, *a, **k)
            bridge._captions = Admitted()
        mb.MemoryBridge.__init__ = bridge_init

    # ---- model clients ------------------------------------------------------------------------
    def _embed(self, texts):
        missing = [t for t in dict.fromkeys(texts) if t not in self._vectors]
        if missing:
            for t, v in zip(missing, self.minilm.encode(missing, normalize_embeddings=True)):
                self._vectors[t] = np.asarray(v, dtype=np.float32)
        return [self._vectors[t] for t in texts]

    @staticmethod
    def _pad(vec, dim):
        return np.concatenate([vec, np.zeros(dim - len(vec), dtype=np.float32)])

    def _ask(self, system, user, tag):
        """Upstream code catches model errors (empty caption, silent decision); record them so the run fails."""
        try:
            return self.llm(system or '', user, tag=tag)
        except Exception as e:
            self._errors.append(f'{tag}: {type(e).__name__}: {e}')
            raise

    def _chat(self, system, history, prompt, tag):
        lines = [f'[Earlier {m["role"]} turn]\n{m["content"]}' for m in history or []]
        lines.append(('[User turn]\n' if history else '') + prompt)
        return self._ask(system, '\n\n'.join(lines), tag)

    def _gpt_4o_mini(self, prompt, system_prompt=None, history_messages=()):
        """videorag/_llm.gpt_4o_mini_complete: entity extraction and retrieval-query rewriting."""
        return self._chat(system_prompt, history_messages, prompt, tag=f'{self.tag}|gpt-4o-mini|w{self._window}')

    def _reasoner(self, prompt, history_messages=None):
        """StreamingPipeline._call_api_reasoning (GPT-5-mini): same messages, earlier turns rendered as text."""
        history = [{'role': m['role'], 'content': '\n'.join(c['text'] for c in m['content'] if c.get('type') == 'text')
                    if isinstance(m['content'], list) else str(m['content'])} for m in history_messages or []]
        stage = 'pass2' if history else 'pass1'
        return self._chat('', history, prompt, tag=f'{self.tag}|gpt-5-mini|w{self._window}|{stage}').strip()

    def _caption_model(self, video_llm, processor, user_prompt, system_prompt=None, base64_frames=None,
                       max_new_tokens=2048, has_image=True, temperature=None, top_p=None, **kwargs):
        """videorag/llm/qwen3vl_vllm.mllm_response: the prompt, then the frames (here their scripted text)."""
        parts = [user_prompt] if user_prompt else []
        if has_image and base64_frames:
            parts += [f'[Image {i}] ' + (self._frames_now[i] if i < len(self._frames_now) else 'unreadable frame')
                      for i in range(len(base64_frames))]
        stage = 'caption' if has_image else 'summary'
        return self._ask(system_prompt, '\n'.join(parts), f'{self.tag}|{stage}|w{self._window}')

    # ---- scripted sensing and the stream loop ------------------------------------------------
    def _sample_frames(self, video_path, interval_seconds=5.0, output_format='base64', **kwargs):
        """videorag/video_processing.sample_frames_by_interval -> (frames, timestamps, time ranges)."""
        n = len(self._frames)
        return list(self._frames), None, [{'start': i * interval_seconds, 'end': (i + 1) * interval_seconds} for i in range(n)]

    def _lockstep(self, p, step_batches):
        """The two loops of StreamingPipeline._run_async_mode (streaming_pipeline.py:563-671), in lockstep."""
        p._total_steps = len(step_batches)              # pipeline_v2_patch wraps the mode to set this
        p._wall_memory_start = p._wall_reasoning_start = time.time()
        for i, batch in enumerate(step_batches):
            time_span = self.mb._make_time_span(1, batch['start_time'], batch['end_time'])
            self._window, self._frames_now = i + 1, [self._frame_text[f] for f in batch['frames']]
            t0 = time.time()
            entry = p.memory.build_step(batch['frames'], time_span, batch['start_time'], batch.get('frame_times'))
            t1 = time.time()
            p._timing_per_chunk_memory_wall.append(t1 - t0)
            caption_text = self.sp._extract_caption_text(entry.get('caption', ''))
            p._current_video_time = batch['end_time']
            p._step_count += 1
            p._reason_and_route(i, batch['end_time'], time_span, caption_text, batch['frames'])
            p._timing_per_chunk_reason_wall.append(time.time() - t1)
            if i == 0:
                p._wall_chunk0_mem_done, p._wall_chunk0_reason_done = t1, time.time()
        p._wall_memory_end = p._wall_reasoning_end = time.time()
        self.pipeline = p

    def _frame_images(self, session):
        """One distinct placeholder image per frame; the frame's text stands in for its pixels."""
        from PIL import Image
        frames = []
        for w, window in enumerate(session['windows']):
            for k, text in enumerate(window):
                buf = io.BytesIO()
                Image.new('RGB', (64, 48), (20 + 9 * w, 30 + 35 * k, 120)).save(buf, format='PNG')
                b64 = base64.b64encode(buf.getvalue()).decode()
                self._frame_text[b64] = text
                frames.append(b64)
        return frames

    # ---- items ----------------------------------------------------------------------------------
    @staticmethod
    def _clock(seconds):
        return f'{int(seconds) // 3600:02d}:{int(seconds) % 3600 // 60:02d}:{int(seconds) % 60:02d}'

    def items(self):
        out = []
        for s in self.sessions.values():
            lines = [f'Setting: {s["setting"]}', f'What the smart glasses saw, in {WINDOW}-second windows:']
            lines += [f'Window {w + 1} ({self._clock(WINDOW * w)}-{self._clock(WINDOW * (w + 1))}): ' + ' '.join(frames)
                      for w, frames in enumerate(s['windows'])]
            lines.append('What would help the user: ' + s['ideal'])
            out.append({'id': s['id'], 'judge_context': '\n'.join(lines)})
        return out

    def run(self, item, cut, sample):
        session = self.sessions[item['id']]
        self.cut = set(cut)
        # The tag names the session, the sample and the stage, not the arm: arms whose prompts are
        # identical share the cached reply, so each comparison differs only where the cut changes a prompt.
        self.tag, self._errors = f'{session["id"]}|s{sample}', []
        run_dir = self.root / f'{session["id"]}-s{sample}-{uuid.uuid4().hex[:8]}'
        run_dir.mkdir()
        video = run_dir / f'{session["id"]}.mp4'
        video.write_text('scripted session')            # run.py checks that the file exists
        self._frames, self.pipeline, self._searches = self._frame_images(session), None, []
        argv = sys.argv
        sys.argv = ['run.py', '--video_path', str(video), '--working_dir', str(run_dir / 'cache')] + CLI_ARGS
        try:
            self.cli.main()
        finally:
            sys.argv = argv
        p = self.pipeline
        if self._errors:
            raise RuntimeError('backbone call failed: ' + self._errors[0])
        if p is None:
            raise RuntimeError('the pipeline stopped before the stream loop; see worker.stderr.log')
        reminders, decisions = [], []
        for step in p.recorder.trajectory:
            w = step['step'] + 1
            span = f'{self._clock(WINDOW * (w - 1))}-{self._clock(WINDOW * w)}'
            for o in step['outputs']:
                if o.get('type') == 'proactive':
                    reminders.append(f'Window {w} ({span}): {o["content"]}')
            decisions.append({'window': w, 'actions': step['actions_taken'],
                              'search': [q['query'] for q in self._searches if q['window'] == w]})
        graph = p._videorag.chunk_entity_relation_graph._graph
        memory = p.memory
        return {
            'output': '\n'.join(reminders) if reminders else '(no reminder)',
            'reminders': reminders,
            'decisions': decisions,
            'captions': [c['caption'] for c in memory._captions],
            'activity_captions': [c['caption'] for c in memory._min_captions],
            'metrics': {
                'reminders': len(reminders),
                'searches': sum('PROACTIVE_SEARCH' in d['actions'] for d in decisions),
                'stored_captions': len(memory._captions),
                'activity_captions': len(memory._min_captions),
                'kg_nodes': graph.number_of_nodes(),
            },
        }
