"""HALO run-mode adapter for LightMem-Ego (zjunlp/LightMem-Ego at commit 3c023df).

LightMem-Ego is a glasses/phone memory service: a realtime frame and audio stream feeds a rolling
current memory (M_cur), short-term micro-events (M_st), and a consolidated long-term memory (M_lt,
EM2Mem), and the user asks questions that are answered from that memory with timestamped evidence.

Each input item is one scripted capture session (first-person frames written as text, and speech)
followed by two questions. The adapter drives the vendored backend (core/src/backend) in one process,
in the order the API and the worker processes run it:
  stream start (api_server._start_stream_session, upstream line 2909, not vendored) -> ingest_frame / ingest_audio_chunk
  (online_pipeline/realtime_ingest.py) -> rolling ASR task (online_streaming/stream_asr_processor.py,
  process_stream_asr_task) -> M_st refine (refine_mst_micro_events.refine_session) -> 30 s episodic
  consolidation (online_short_term/mst_to_episodic.build_episodic_from_mst) -> long-term append
  (online_memory_incremental/incremental_store.IncrementalMemoryAppender.append_ready_episodes, as
  online_memory_worker.py lines 419-433 calls it) -> questions (online_query/query_engine.query_session,
  as online_query_worker.py lines 529-551 calls it). Task files go to a per-run project root; nothing
  is shared between runs.

Replacements (only the model clients and media plumbing):
  - openai.OpenAI / AsyncOpenAI / AzureOpenAI are replaced by a client that sends the chat messages to
    the HALO backbone. This covers the M_st refiner, the episodic window builder, and em2mem's
    OpenAIModel (OpenIE, multiscale rewrite, event selector, answers). Attached images are replaced by
    the scripted text of the frame they show; em2mem's OpenAIModel.encode_image passes the frame file
    through instead of re-encoding it, so the stub can find that text.
  - Speech recognition: ffmpeg window assembly and the Xfyun/WhisperX call
    (online_streaming/stream_asr_processor.py:399 _build_audio_window_wav and :204
    _transcribe_audio_with_backend) return the scripted
    speech that falls in the window. Everything around them (window bookkeeping, partial transcript
    store, transcript backfill into M_cur and M_st) runs upstream.
  - Text embeddings (Qwen3-Embedding-4B) are all-MiniLM-L6-v2 on CPU, through the upstream
    Qwen3EmbeddingModel wrapper (EM2MEM_TEXT_EMBED_MODEL). Visual embeddings (VLM2Vec) are off, as in
    the Docker default (EM2MEM_VISUAL_BACKEND=mock).

Cut sites (receiving end; file:line in core/src/backend):
  S->M  online_short_term/mst_store.py:164 MSTStore.append_events and :206 backfill_transcript_segments
        admit nothing, so sensed frames and transcripts never enter M_st (and therefore M_lt).
        The rolling current window M_cur (current observation, the S->A path) still updates.
  M->A  retrieved memory is removed where the answer is built: online_query/query_engine.py:2783
        LoadedQueryEngine._generate_answer_from_evidence (only M_cur evidence and current frames
        stay), :3737 _build_short_term_llm_prompt (no M_st events), and
        online_query/coreference_resolver.py:46 CoreferenceResolver.resolve (no interaction-cache
        context is used to rewrite the question).
  A->M  online_query/interaction_cache.py:177 InteractionCache.update_from_query_result does not
        write the answered turn (question, answer, entities, time ranges, evidence ids) to the
        interaction cache that the next question's coreference resolver and retrieval boost read.
LightMem-Ego does not revise its own mechanism, so no evidence step is cut.
"""
import asyncio, base64, hashlib, io, json, os, re, shutil, sys, tempfile, threading, types, wave
from pathlib import Path
from types import SimpleNamespace

from halo.run.adapter import BaseAdapter

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core' / 'src' / 'backend'   # vendored upstream backend, see core/SOURCE.md

# Deployment settings. Values follow deploy/.env.example (the Docker setup) and the worker launch
# scripts; the README explains each change.
ENV = {
    'OPENAI_API_KEY': 'halo-backbone',              # the OpenAI client is replaced; no request leaves the process
    'OPENAI_BASE_URL': 'http://backbone.invalid/v1',
    'EM2MEM_LLM_PROFILE': 'remote',
    'EM2MEM_PIPELINE_MODE': 'mst',
    'EM2MEM_MEMORY_MODEL': 'gpt-5.4',
    'EM2MEM_QUERY_RESPOND_MODEL': 'gpt-5.4',
    'EM2MEM_MST_REFINE_MODEL': 'gpt-5.4',
    'EM2MEM_MST_EPISODIC_MODEL': 'gpt-5.4',
    'EM2MEM_EVIDENCE_CAPTION_BACKEND': 'openai',
    'EM2MEM_STREAM_ASR_BACKEND': 'xfyun',
    'EM2MEM_AUDIO_ASR_BACKEND': 'xfyun',
    'EM2MEM_VISUAL_BACKEND': 'mock',
    'EM2MEM_AUTO_VISUAL_EMBEDDING': '0',            # no VLM2Vec model: visual retrieval stays off
    'EM2MEM_TEXT_EMBED_BACKEND': 'local',
    'EM2MEM_TEXT_EMBED_MODEL': 'sentence-transformers/all-MiniLM-L6-v2',
    'EM2MEM_TEXT_EMBED_DEVICE': 'cpu',
    'EM2MEM_ALLOW_HF_DOWNLOAD': '0',
    'EM2MEM_INCREMENTAL_HIPPORAG_REFRESH_SUBPROCESS': '0',   # run the cache refresh in this process
    'EM2MEM_MCUR_STALE_SECONDS': '1000000',         # the question follows the last frame; run time is not stream time
    'EM2MEM_SINGLE_ACTIVE_SESSION': '0',
    'EM2MEM_ANSWER_LANGUAGE': 'en',                 # scripted sessions are in English
    'EM2MEM_QUERY_WARMUP_ON_STREAM_START': '0',
    'TOKENIZERS_PARALLELISM': 'false',
}
SPEECH_LAG_S = 10.0     # the ASR worker transcribes a window once the frame event around it has closed
FRAME_SIZE = (320, 240)


def _jpeg(color, frame_index, scene_index):
    """A frame image: the scene's colour with a scene-specific shape, and the frame index coded in
    black and white blocks so every frame file is distinct. The image only drives the upstream
    OpenCV event detector; its content reaches the model as the scripted text."""
    from PIL import Image, ImageDraw
    img = Image.new('RGB', FRAME_SIZE, tuple(color))
    d = ImageDraw.Draw(img)
    w, h = FRAME_SIZE
    shade = tuple(max(0, c - 70) for c in color)
    x0 = 40 + (scene_index * 53) % 160
    d.rectangle([x0, 70, x0 + 110, 200], fill=shade)
    for bit in range(10):
        on = (frame_index >> bit) & 1
        d.rectangle([4 + bit * 12, 4, 13 + bit * 12, 13], fill=(255, 255, 255) if on else (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=90)
    return buf.getvalue()


def _wav(duration_ms, rate=8000):
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b'\x00\x00' * int(rate * duration_ms / 1000))
    return buf.getvalue()


SCENE_COLORS = [(196, 64, 52), (52, 120, 196), (60, 160, 80), (210, 170, 40), (140, 70, 170), (40, 170, 170)]


class Adapter(BaseAdapter):
    channels = {
        'S->M': 'frames and ASR transcripts admitted into the short-term micro-event store (M_st), the source of M_lt',
        'M->A': 'retrieved M_st/M_lt/interaction-cache evidence delivered to the answer prompt',
        'A->M': 'answered turns written to the interaction cache that resolves and boosts the next question',
    }
    steps = {}   # no self-revision of prompts, rules, or code

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        self.cut, self.tag, self.stage = set(), '', ''
        self.frames_by_hash, self.speech = {}, []
        self.calls = 0
        self._lock = threading.Lock()
        os.environ.update(ENV)
        data = json.loads((Path(case_dir) / 'inputs' / 'sessions.json').read_text())
        self.sessions = {s['id']: s for s in data['sessions']}
        self._install_stubs()
        for p in (CORE, CORE / 'src', CORE / 'src' / 'HippoRAG' / 'src'):
            sys.path.insert(0, str(p))
        self._import_upstream()
        self._install_cuts()

    # ---- model clients -> HALO backbone --------------------------------------------------------
    def _messages_to_text(self, messages):
        system, turns = [], []
        for m in messages or []:
            content = m.get('content')
            parts = []
            if isinstance(content, str):
                parts.append(content)
            else:
                for p in content or []:
                    if not isinstance(p, dict):
                        parts.append(str(p)); continue
                    if p.get('type') in ('text', 'input_text'):
                        parts.append(str(p.get('text') or ''))
                    elif p.get('type') in ('image_url', 'input_image', 'image'):
                        url = p.get('image_url')
                        url = url.get('url') if isinstance(url, dict) else url
                        parts.append(self._image_text(str(url or '')))
            text = '\n'.join(x for x in parts if x)
            if m.get('role') == 'system':
                system.append(text)
            else:
                turns.append((m.get('role') or 'user', text))
        if len(turns) == 1:
            user = turns[0][1]
        else:
            user = '\n\n'.join(f'[{r}]\n{t}' for r, t in turns)
        return '\n\n'.join(system), user

    def _image_text(self, url):
        try:
            raw = base64.b64decode(url.split(',', 1)[1])
            desc = self.frames_by_hash.get(hashlib.sha256(raw).hexdigest())
        except Exception:
            desc = None
        return f'[Attached image: {desc}]' if desc else '[Attached image: not available]'

    def _complete(self, kwargs):
        system, user = self._messages_to_text(kwargs.get('messages'))
        with self._lock:
            self.calls += 1
        text = self.llm(system, user, tag=f'{self.tag}|{self.stage}')
        fmt = kwargs.get('response_format') or {}
        if isinstance(fmt, dict) and fmt.get('type') in ('json_object', 'json_schema'):
            text = _json_only(text)   # JSON mode: the API returns a bare JSON object
        return text

    def _install_stubs(self):
        adapter = self

        def response(text, model):
            msg = SimpleNamespace(role='assistant', content=text, refusal=None, tool_calls=None)
            return SimpleNamespace(id='halo', model=model, object='chat.completion',
                                   choices=[SimpleNamespace(index=0, message=msg, finish_reason='stop', text=None)],
                                   usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0))

        def stream(text, model):
            yield SimpleNamespace(id='halo', model=model, choices=[SimpleNamespace(index=0, delta=SimpleNamespace(content=text, text=None), finish_reason=None, text=None)])
            yield SimpleNamespace(id='halo', model=model, choices=[SimpleNamespace(index=0, delta=SimpleNamespace(content=None, text=None), finish_reason='stop', text=None)])

        class Completions:
            def create(self, **kw):
                text = adapter._complete(kw)
                return stream(text, kw.get('model')) if kw.get('stream') else response(text, kw.get('model'))

        class AsyncCompletions:
            async def create(self, **kw):
                text = await asyncio.to_thread(adapter._complete, kw)
                if kw.get('stream'):
                    async def agen():
                        for chunk in stream(text, kw.get('model')):
                            yield chunk
                    return agen()
                return response(text, kw.get('model'))

        class Responses:
            def create(self, **kw):
                raise RuntimeError('responses API is not used (EM2MEM_OPENAI_FORCE_CHAT_COMPLETIONS=1)')

        class FakeOpenAI:
            def __init__(self, *a, **k):
                self.chat = SimpleNamespace(completions=Completions())
                self.responses = Responses()

        class FakeAsyncOpenAI:
            def __init__(self, *a, **k):
                self.chat = SimpleNamespace(completions=AsyncCompletions())
                self.responses = Responses()

        import openai
        openai.OpenAI, openai.AsyncOpenAI, openai.AzureOpenAI = FakeOpenAI, FakeAsyncOpenAI, FakeOpenAI
        # decord (video decoding) is imported by em2mem/llm/openai_gpt.py but only used for video prompts,
        # which this run never sends; it has no macOS arm64 wheel.
        if 'decord' not in sys.modules:
            decord = types.ModuleType('decord')
            decord.VideoReader = type('VideoReader', (), {})
            decord.cpu = lambda *a, **k: None
            sys.modules['decord'] = decord

    def _import_upstream(self):
        import torch  # noqa: F401  (load torch's OpenMP before faiss's, or encoding segfaults on macOS)
        from em2mem.llm import openai_gpt
        # em2mem's client re-encodes images before upload; pass the frame file through instead so the
        # backbone stub can replace it with the frame's scripted text.
        openai_gpt.OpenAIModel.encode_image = lambda self, image: base64.b64encode(Path(image).read_bytes()).decode()
        from online_short_term.stream_chunk_manager import StreamChunkManager
        from online_pipeline.frame_stream import FrameStreamStore
        from online_pipeline.audio_stream import AudioStreamStore
        from online_pipeline import realtime_ingest
        from online_preprocess.io_utils import write_json_atomic, write_status
        from online_preprocess import task_queue
        from online_streaming import stream_asr_processor
        import refine_mst_micro_events
        from online_short_term.mst_to_episodic import build_episodic_from_mst
        from online_memory_incremental import IncrementalMemoryAppender
        from online_query import query_engine
        from online_short_term.mst_store import MSTStore
        from online_query.coreference_resolver import CoreferenceResolver
        from online_query.interaction_cache import InteractionCache
        from online_query.cache_schema import CacheContext
        self.u = SimpleNamespace(
            StreamChunkManager=StreamChunkManager, FrameStreamStore=FrameStreamStore, AudioStreamStore=AudioStreamStore,
            ingest=realtime_ingest, write_json_atomic=write_json_atomic, write_status=write_status,
            task_queue=task_queue, asr=stream_asr_processor, refine=refine_mst_micro_events,
            build_episodic_from_mst=build_episodic_from_mst, Appender=IncrementalMemoryAppender,
            qe=query_engine, MSTStore=MSTStore, Resolver=CoreferenceResolver, Cache=InteractionCache,
            CacheContext=CacheContext)
        adapter = self

        def build_window(session_dir, task, *, force=False):
            # ffmpeg concatenation of the window's audio chunks; the stub ASR below reads the script.
            out = Path(session_dir) / str(task.get('output_audio_path') or f"stream/audio/asr_windows/{task.get('window_id')}.wav")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(_wav(int(task.get('duration_ms') or 0) or 1000))
            return out

        def transcribe(*, backend, audio_path, **kw):
            m = re.search(r'_(\d{9})_(\d{9})\.wav$', str(audio_path))
            start, end = int(m.group(1)) / 1000.0, int(m.group(2)) / 1000.0
            local = [{'start': round(s['start'] - start, 3), 'end': round(min(s['end'], end) - start, 3),
                      'text': s['text'], 'confidence': 0.95}
                     for s in adapter.speech if start <= s['start'] < end]
            return local, not local, backend, None

        stream_asr_processor._build_audio_window_wav = build_window
        stream_asr_processor._transcribe_audio_with_backend = transcribe

    # ---- cut sites ------------------------------------------------------------------------------
    def _install_cuts(self):
        adapter, u = self, self.u
        orig_append, orig_backfill = u.MSTStore.append_events, u.MSTStore.backfill_transcript_segments

        def append_events(store, events):
            if 'S->M' in adapter.cut:
                return []
            return orig_append(store, events)

        def backfill(store, segments, reason='stream_asr'):
            if 'S->M' in adapter.cut:
                return {'backfilled_event_count': 0, 'updated_event_ids': [], 'needs_refine_event_ids': [],
                        'needs_reconsolidation_windows': [], 'updated_events': []}
            return orig_backfill(store, segments, reason=reason)

        u.MSTStore.append_events, u.MSTStore.backfill_transcript_segments = append_events, backfill

        Engine = u.qe.LoadedQueryEngine
        orig_generate = Engine._generate_answer_from_evidence

        def generate(engine, **kw):
            if 'M->A' in adapter.cut:
                kw['selected_evidence'] = [e for e in (kw.get('selected_evidence') or []) if e.get('source_memory') == 'M_cur']
                kw['text_results'], kw['visual_results'], kw['fused_results'], kw['short_term_results'] = [], [], [], []
                if kw.get('selected_image_paths') is not None:
                    kw['selected_image_paths'] = [p for p in kw['selected_image_paths'] if str(p).startswith('current/')]
            return orig_generate(engine, **kw)

        Engine._generate_answer_from_evidence = generate
        orig_st_prompt = u.qe._build_short_term_llm_prompt
        u.qe._build_short_term_llm_prompt = lambda q, results, summary: orig_st_prompt(
            q, [] if 'M->A' in adapter.cut else results, {} if 'M->A' in adapter.cut else summary)
        orig_resolve = u.Resolver.resolve

        def resolve(resolver, question, cache):
            if 'M->A' in adapter.cut:
                return u.CacheContext(reason='interaction cache withheld (HALO cut M->A)').to_dict()
            return orig_resolve(resolver, question, cache)

        u.Resolver.resolve = resolve
        orig_update = u.Cache.update_from_query_result

        def update(cache, question, resolved_question, result):
            if 'A->M' in adapter.cut:
                return {'updated': False, 'reason': 'HALO cut A->M'}
            return orig_update(cache, question, resolved_question, result)

        u.Cache.update_from_query_result = update

    # ---- one capture session, then questions ---------------------------------------------------
    def items(self):
        return [{'id': s['id'], 'judge_context': _situation(s)} for s in self.sessions.values()]

    def _start_stream(self, root, session_id):
        """The calls api_server._start_stream_session (upstream line 2909) makes for input_mode=frame_audio_stream."""
        u = self.u
        session_dir = root / 'online_sessions' / session_id
        session_dir.mkdir(parents=True)
        metadata = {'input_mode': 'frame_audio_stream', 'api_namespace': 'stream', 'device_type': 'phone'}
        u.write_json_atomic(session_dir / 'metadata.json', {
            'session_id': session_id, 'source': 'stream', 'original_filename': None,
            'saved_video_path': str(session_dir / 'input.mp4'), 'size_bytes': 0, 'metadata': metadata})
        u.write_status(session_dir=session_dir, session_id=session_id, status='created', stage='stream_created', progress=0, error=None)
        manager = u.StreamChunkManager(session_dir)
        state = manager.init_stream(chunk_duration=float(os.getenv('EM2MEM_STREAM_PROCESSING_CHUNK_SECONDS') or 5.0), metadata=metadata)
        manager.update_stream_state_locked(lambda s: (s.__setitem__('input_mode', 'frame_audio_stream'), s.setdefault('metadata', {}).update(metadata)))
        frames, audio = u.FrameStreamStore(session_dir), u.AudioStreamStore(session_dir)
        frames.initialize(stream_id=str(state.get('stream_id') or ''), input_mode='frame_audio_stream')
        audio.initialize(stream_id=str(state.get('stream_id') or ''), input_mode='frame_audio_stream')
        fr, ar = frames.public_status(input_mode='frame_audio_stream'), audio.public_status(input_mode='frame_audio_stream')
        manager.update_stream_state_locked(lambda s: s.update({'input_mode': 'frame_audio_stream', 'frame_stream': fr, 'audio_stream': ar}))
        u.write_status(session_dir=session_dir, session_id=session_id, status='streaming', stage='stream_started', progress=0, error=None)
        return session_dir

    def _run_asr(self, root, until_ms):
        """online_asr_worker.run_worker: claim queued rolling-ASR tasks and process them."""
        u = self.u
        for path in u.task_queue.list_queued_stream_asr_tasks(root):
            if int(json.loads(path.read_text()).get('window_end_ms') or 0) > until_ms:
                continue   # the worker has not reached this window yet
            claimed = u.task_queue.claim_stream_asr_task(root, path)
            if claimed is None:
                continue
            claimed_path, task = claimed
            result = u.asr.process_stream_asr_task(
                project_root=root, sessions_root=root / 'online_sessions', task=task, asr_runtime=None,
                whisperx_model='medium', device='cpu', compute_type='int8', language=None, model_dir=None,
                align_model_dir=None, force=False)
            u.task_queue.finish_stream_asr_task(root, claimed_path, task, status='done', result=result)

    def _capture(self, root, session_id, sess):
        u = self.u
        timeline = []
        dt = float(sess.get('frame_interval_s', 2.0))
        frame_index = 0
        for si, scene in enumerate(sess['scenes']):
            color = SCENE_COLORS[si % len(SCENE_COLORS)]
            for k, text in enumerate(scene['frames']):
                t = float(scene['start']) + k * dt
                jpg = _jpeg(color, frame_index, si)
                self.frames_by_hash[hashlib.sha256(jpg).hexdigest()] = text
                timeline.append((t, 0, 'frame', frame_index, jpg))
                frame_index += 1
        duration = float(sess['duration_s'])
        for i in range(int(duration)):
            timeline.append((float(i), 1, 'audio', i, _wav(1000)))
        timeline.sort(key=lambda x: (x[0], x[1]))
        for t, _, kind, idx, payload in timeline:
            rel = int(round(t * 1000))
            if kind == 'frame':
                r = u.ingest.ingest_frame(root, session_id, payload, frame_index=idx, relative_ts_ms=rel,
                                          client_ts_ms=1790000000000 + rel, format='jpg', width=FRAME_SIZE[0],
                                          height=FRAME_SIZE[1], source='http_frame_upload')
            else:
                r = u.ingest.ingest_audio_chunk(root, session_id, payload, audio_index=idx, relative_ts_ms=rel,
                                                client_ts_ms=1790000000000 + rel, duration_ms=1000, sample_rate=8000,
                                                channels=1, format='wav', content_type='audio/wav', source='http_audio_upload')
            if r.get('status') not in ('frame_received', 'audio_chunk_received'):
                raise RuntimeError(f'{kind} {idx} not accepted: {r}')
            self._run_asr(root, int((t - SPEECH_LAG_S) * 1000))
        self._run_asr(root, int(duration * 1000))

    def run(self, item, cut, sample):
        sess = self.sessions[item['id']]
        self.cut = set(cut)
        # The tag names the item and the sample, not the arm, so arms with identical prompts share replies.
        self.tag = f'{sess["id"]}|s{sample}'
        self.speech = sess.get('speech', [])
        self.calls = 0
        root = Path(tempfile.mkdtemp(prefix=f'lmego-{sess["id"]}-'))
        old_cwd = os.getcwd()
        os.chdir(root)                     # em2mem keeps its caches under ./.cache
        (root / '.cache').mkdir()
        session_id = f'halo_{sess["id"]}'.replace('-', '_')
        u = self.u
        try:
            session_dir = self._start_stream(root, session_id)
            self.stage = 'ingest'
            self._capture(root, session_id, sess)
            self.stage = 'refine'
            refine = u.refine.refine_session(session_id=session_id, sessions_root=root / 'online_sessions',
                                             backend='openai', limit_events=1000)
            self.stage = 'episodic'
            episodic = u.build_episodic_from_mst(session_id=session_id, sessions_root=root / 'online_sessions', backend='openai')
            self.stage = 'longterm'
            appended = u.Appender(session_id=session_id, sessions_root=root / 'online_sessions',
                                  project_root=root).append_ready_episodes(
                episode_ids=episodic.get('generated_episode_ids') or None)
            answers = []
            for qi, q in enumerate(sess['questions']):
                self.stage = f'q{qi + 1}'
                res = u.qe.query_session(session_id=session_id, question=q['q'], sessions_root=root / 'online_sessions',
                                         no_cache=True)
                answers.append(res)
            config = json.loads((session_dir / 'em2mem' / 'memory_config.json').read_text()) \
                if (session_dir / 'em2mem' / 'memory_config.json').exists() else {}
            mst = u.MSTStore(session_dir)
            n_events = len(mst.load_archive_events())
            n_refined = sum(1 for e in mst.load_archive_events() if e.get('status') in ('refined', 'final'))
            out = {'questions': [q['q'] for q in sess['questions']]}
            for i, (q, res) in enumerate(zip(sess['questions'], answers)):
                key = 'output' if i == 0 else f'output_q{i + 1}'
                out[key] = (str(res.get('answer') or '').strip() or f'(no answer; status {res.get("status")})')
            out['context_q2'] = item['judge_context'] + f'\n\nEarlier in this conversation the wearer asked: "{sess["questions"][0]["q"]}" and was told: "{out["output"]}"'
            out['trace'] = [{
                'question': q['q'], 'status': res.get('status'), 'resolved_question': res.get('resolved_question'),
                'route': (res.get('route_decision') or {}).get('memory_route'), 'query_type': res.get('query_type'),
                'used_sources': res.get('used_memory_sources'),
                'selected_evidence': [{k: e.get(k) for k in ('source_memory', 'start_time', 'end_time', 'caption')}
                                      for e in (res.get('selected_evidence') or [])][:8],
                'cache_followup': bool((res.get('cache_context') or {}).get('is_followup')),
                'warnings': (res.get('warnings') or [])[:5],
                'fallback_reason': res.get('fallback_reason'),
                'long_term_load_error': (res.get('raw') or {}).get('long_term_load_error'),
            } for q, res in zip(sess['questions'], answers)]
            out['memory'] = {'long_term_status': config.get('status'),
                             'hipporag_cache_ready': config.get('hipporag_cache_ready'),
                             'hipporag_cache_error': config.get('hipporag_cache_error'),
                             'refine': {k: refine.get(k) for k in ('selected_event_count', 'refined_event_count')},
                             'episodes': episodic.get('generated_episode_ids')}
            out['metrics'] = {
                'mst_events': n_events,
                'mst_refined': n_refined,
                'mlt_episodes': len(appended.appended_episode_ids or []),
                'q1_fact_recall': _recall(out['output'], sess['questions'][0].get('expect', [])),
                'q2_fact_recall': _recall(out.get('output_q2', ''), sess['questions'][1].get('expect', [])) if len(sess['questions']) > 1 else None,
                'q2_followup_resolved': int(bool((answers[1].get('cache_context') or {}).get('is_followup'))) if len(answers) > 1 else None,
                'model_calls': self.calls,   # calls the system made to the model (cached replies included)
            }
            return out
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(root, ignore_errors=True)


def _json_only(text):
    t = text.strip()
    t = re.sub(r'^```(?:json)?\s*', '', t)
    t = re.sub(r'\s*```$', '', t)
    if not t.startswith('{'):
        m = re.search(r'\{.*\}', t, flags=re.DOTALL)
        if m:
            t = m.group(0)
    return t


def _recall(answer, expect):
    if not expect:
        return None
    a = (answer or '').lower()
    return round(sum(1 for e in expect if str(e).lower() in a) / len(expect), 3)


def _situation(s):
    lines = [s.get('situation', ''), '', 'What the wearer saw and heard (ground truth, not shown to the assistant):']
    for sc in s['scenes']:
        lines.append(f'- {sc["start"]:.0f}-{sc["end"]:.0f} s: {sc["summary"]}')
    for sp in s.get('speech', []):
        lines.append(f'- speech at {sp["start"]:.0f} s: "{sp["text"]}"')
    lines.append('')
    lines.append(f'The question was asked at {s["duration_s"]:.0f} s, while the capture was still running: "{s["questions"][0]["q"]}"')
    return '\n'.join(lines)
