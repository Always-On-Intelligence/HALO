"""HALO run-mode adapter for M3-Agent (ByteDance-Seed/M3-Agent at commit 0e3e419).

Configuration: the long-video QA setting, memory-7b-sft (memorization) plus control-32b-rl
(control) over an external multimodal memory graph.

Each item is one long video made of 30-second clips written as text, with questions about it.
Memorization runs the upstream m3_agent/memorization_memory_graphs.streaming_process_video. For
every clip, process_voices and process_faces load the clip's intermediate outputs (diarized speech
and face detections, the cache files the upstream code reads when they exist) and match each voice
and face against the voice and face nodes already in the VideoGraph. The memorization model then
writes episodic and semantic memories that refer to people by those node ids, and process_memories
inserts them into the graph, which is pickled. Control answers each question with the loop of
m3_agent/control.py (lines 162-207): the control model reasons, and control.consumer searches the
pickled graph with mmagent/retrieve.search until the model answers or the round limit (5) is
reached. control.eval_answer, the upstream GPT-4o verifier, scores every answer against the
reference answer.

Model clients replaced (everything else runs from core/):
  memory-7b-sft (Qwen2.5-Omni thinker, utils/chat_qwen.get_response) -> HALO backbone. The clip's
      video is its scripted text and each face crop is a text description of the face. The prompt
      asks for the key 'video_description' while the code reads 'video_descriptions' (the trained
      model emits the latter), so the adapter renames that key and adds an empty list for a missing
      key before the code parses the reply.
  control-32b-rl (vLLM, control.py:141,176-188) -> HALO backbone; the conversation is rendered as
      text with earlier turns marked.
  GPT-4o verifier (control.get_response, control.py:41) -> a second backbone role, tag 'gpt4o-verifier'.
  text-embedding-3-large (utils/chat_api.parallel_get_embedding, get_embedding_with_retry)
      -> all-MiniLM-L6-v2 on CPU.
  insightface (RetinaFace + ArcFace), the Gemini diarizer and the ERes2NetV2 speaker embedder are
      not run: their outputs are the scripted intermediate outputs, with the MiniLM embedding of a
      fixed face text and voice text per person. The face and voice matching thresholds in
      configs/memory_config.json (0.3 and 0.6, calibrated for ArcFace and ERes2NetV2) are set to
      0.95, because the same person's text scores 1.0 and different people in the inputs score at
      most 0.88.
  Video decoding (utils/video_processing.process_video_clip) returns the scripted clip: placeholder
      JPEG frames and face crops so the upstream image code runs, and the clip text for the model.
  Clips are listed in clip-id order (the stream order; upstream glob order depends on the filesystem).

Cut sites (upstream file:line):
  S->M  m3_agent/memorization_memory_graphs.py:66-67  process_memories(...) inserts nothing, so the
        clip's episodic and semantic memories never reach the graph.
  M->S  mmagent/face_processing.py:160 and mmagent/voice_processing.py:205 (VideoGraph.search_img_nodes
        and search_voice_nodes, mmagent/videograph.py:614-670): matching sees only the nodes created
        in the current clip, so faces and voices kept from earlier clips no longer identify the
        people in a new clip.
  M->A  m3_agent/control.py:117-131  search(...) returns no memories, so the control model receives
        'Searched knowledge: {}' after every search.
"""
import base64, importlib.util, io, json, os, re, shutil, sys, tempfile, types, uuid, warnings
from pathlib import Path
from halo.run.adapter import BaseAdapter
from halo.run.llm import LLM

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core'                       # vendored upstream code, see core/SOURCE.md
MATCH_THRESHOLD = 0.95                     # face and voice matching with MiniLM text embeddings (see docstring)
N_FRAMES = 5                               # placeholder frames per clip; face detections index into them
FORCED = '\n(The Action of this round must be [Answer]. If there is insufficient information, you can make reasonable guesses.)'


class _Inert:
    """Stands in for the perception models that are not run (their outputs are scripted)."""
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k): raise RuntimeError('replaced in HALO run mode: outputs are scripted')
    def load_state_dict(self, *a, **k): return None
    def to(self, *a, **k): return self
    def eval(self): return self
    def prepare(self, *a, **k): return None
    def get(self, *a, **k): raise RuntimeError('replaced in HALO run mode: face detections are scripted')


class _Tokenizer:
    """control.py loads the control model's tokenizer at import; the chat template is applied by the adapter."""
    def apply_chat_template(self, *a, **k): raise RuntimeError('replaced in HALO run mode')


class Adapter(BaseAdapter):
    channels = {
        'S->M': "each clip's episodic and semantic memories are inserted into the memory graph (memorization_memory_graphs.py:66-67)",
        'M->S': 'face and voice nodes kept from earlier clips identify the people in a new clip (face_processing.py:160, voice_processing.py:205)',
        'M->A': 'memories retrieved from the graph are returned to the control model (control.py:117-131)',
    }
    steps = {}   # M3-Agent does not revise its own mechanism, so no evidence step is cut

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        self.cut, self.tag = set(), ''
        self.verifier = LLM(llm.backend, llm.effort, llm.cache)          # second role: the GPT-4o answer verifier
        self.videos = {v['id']: v for v in json.loads((CASE / 'inputs' / 'videos.json').read_text())['videos']}
        # The upstream modules read configs/*.json relative to the working directory. The run directory
        # holds them unchanged, plus api_config.json filled with placeholders (the step the README asks
        # users to do): control.py builds an Azure client from it at import; it is never called.
        self.root = Path(tempfile.mkdtemp(prefix='halo-m3agent-'))
        (self.root / 'configs').mkdir()
        for f in ('processing_config.json', 'memory_config.json'):
            shutil.copy(CORE / 'configs' / f, self.root / 'configs' / f)
        placeholder = {'azure_endpoint': 'https://placeholder.invalid', 'api_version': '2024-08-01-preview', 'api_key': 'unused'}
        (self.root / 'configs' / 'api_config.json').write_text(json.dumps(
            {m: placeholder for m in ('gpt-4o-2024-11-20', 'gemini-1.5-pro-002', 'text-embedding-3-large')}))
        os.chdir(self.root)
        os.environ.setdefault('MPLBACKEND', 'Agg')
        warnings.filterwarnings('ignore', message='FigureCanvasAgg is non-interactive')
        warnings.filterwarnings('ignore', message="Couldn't find ffmpeg")
        from sentence_transformers import SentenceTransformer
        self.minilm = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', device='cpu')
        self._import_upstream()
        self._clip_text, self._image_text, self._emb = {}, {}, {}
        self._clip_start, self._reused, self._errors = 0, 0, []
        self._frames = [self._jpeg((128, 128, 128), (64, 48)) for _ in range(N_FRAMES)]

    # ---- upstream import with the model clients stubbed --------------------------------------
    def _import_upstream(self):
        def module(name, **attrs):
            m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m
        # Perception models and media libraries that only the replaced steps use.
        module('insightface'); module('insightface.app', FaceAnalysis=_Inert)
        module('speakerlab'); module('speakerlab.process'); module('speakerlab.process.processor', FBank=_Inert)
        module('speakerlab.utils'); module('speakerlab.utils.builder', dynamic_import=lambda path: _Inert)
        module('torchaudio'); module('hdbscan', HDBSCAN=_Inert); module('cv2')
        module('moviepy', VideoFileClip=_Inert, __all__=['VideoFileClip'])
        module('qwen_omni_utils', process_mm_info=_Inert())
        module('vllm', LLM=_Inert, SamplingParams=_Inert)
        sys.path.insert(0, str(CORE))
        import torch, transformers
        load, from_pretrained = torch.load, transformers.AutoTokenizer.__dict__['from_pretrained']
        torch.load = lambda *a, **k: {}                       # voice_processing.py:35 loads the ERes2NetV2 checkpoint at import
        transformers.AutoTokenizer.from_pretrained = staticmethod(lambda *a, **k: _Tokenizer())   # control.py:91
        try:
            import mmagent
            from mmagent import videograph, retrieve, memory_processing, memory_processing_qwen
            from mmagent.utils import chat_api
            self.mm = self._load('m3_memorization', CORE / 'm3_agent' / 'memorization_memory_graphs.py')
            self.control = self._load('m3_control', CORE / 'm3_agent' / 'control.py')
        finally:
            torch.load = load
            transformers.AutoTokenizer.from_pretrained = from_pretrained
        self.VideoGraph, self.translate = videograph.VideoGraph, retrieve.translate
        # model clients -> HALO backbone / MiniLM
        memory_processing_qwen.get_response = self._memorization_model
        for mod in (memory_processing_qwen, memory_processing, retrieve, chat_api):
            mod.parallel_get_embedding = self._embed_texts
        for mod in (retrieve, chat_api):
            mod.get_embedding_with_retry = lambda model, text, timeout=15: (self._embed([text])[0], 0)
        self.control.get_response = self._verifier_model
        # sensor input -> scripted clip; stream order
        self.mm.process_video_clip = self._read_clip
        self.mm.glob = types.SimpleNamespace(glob=lambda pattern: sorted(
            __import__('glob').glob(pattern), key=lambda p: int(Path(p).stem)))
        # cut sites
        self._process_memories = self.mm.process_memories
        self.mm.process_memories = self._memory_write                      # S->M
        self._search = self.control.search
        self.control.search = self._memory_read                            # M->A
        self._img, self._voice = self.VideoGraph.search_img_nodes, self.VideoGraph.search_voice_nodes
        adapter = self
        self.VideoGraph.search_img_nodes = lambda g, info: adapter._identify(adapter._img, g, info)       # M->S
        self.VideoGraph.search_voice_nodes = lambda g, info: adapter._identify(adapter._voice, g, info)   # M->S

    @staticmethod
    def _load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod; spec.loader.exec_module(mod)
        return mod

    # ---- cut sites ----------------------------------------------------------------------------
    def _memory_write(self, video_graph, memory_contents, clip_id, type='episodic'):
        if 'S->M' in self.cut:
            return None
        return self._process_memories(video_graph, memory_contents, clip_id, type=type)

    def _memory_read(self, video_graph, query, current_clips, *args, **kwargs):
        if 'M->A' in self.cut:
            return {}, current_clips, {}
        return self._search(video_graph, query, current_clips, *args, **kwargs)

    def _identify(self, search, video_graph, info):
        results = search(video_graph, info)
        if 'M->S' in self.cut:
            results = [(n, s) for n, s in results if n >= self._clip_start]
        elif results and results[0][0] < self._clip_start:
            self._reused += 1                  # a person kept from an earlier clip is recognised
        return results

    # ---- model clients ------------------------------------------------------------------------
    def _ask(self, llm, system, user, tag):
        """Upstream code catches some model errors (eval_answer returns False); record them so the run fails."""
        try:
            return llm(system, user, tag=tag)
        except Exception as e:
            self._errors.append(f'{tag}: {type(e).__name__}: {e}')
            raise

    def _embed(self, texts):
        missing = [t for t in texts if t not in self._emb]
        if missing:
            for t, e in zip(missing, self.minilm.encode(missing, normalize_embeddings=True)):
                self._emb[t] = [float(x) for x in e]
        return [self._emb[t] for t in texts]

    def _embed_texts(self, model, texts, timeout=15):
        return self._embed([t if isinstance(t, str) else json.dumps(t, ensure_ascii=False) for t in texts]), 0

    def _memorization_model(self, messages):
        """utils/chat_qwen.get_response: the Qwen2.5-Omni thinker fine-tuned as memory-7b-sft."""
        parts = []
        for message in messages:
            for c in message['content']:
                if c['type'] == 'text':
                    parts.append(c['text'])
                elif c['type'] == 'video':
                    parts.append('[Video clip, 30 seconds with audio]\n' + self._clip_text[c['video']])
                elif c['type'] == 'image':
                    parts.append('[Image] ' + self._image_text.get(c['image'].split('base64,', 1)[-1], 'unreadable image'))
        reply = self._ask(self.llm, '', '\n'.join(parts), tag=f'{self.tag}|memorization|{Path(self._clip_path).stem}')
        return self._sft_format(reply), 0

    @staticmethod
    def _sft_format(reply):
        m = re.search(r'\{.*\}', reply, re.S)
        try:
            data = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            return reply                       # the upstream parser handles (and retries) unparsable replies
        if 'video_descriptions' not in data:
            data['video_descriptions'] = data.pop('video_description', [])
        data.setdefault('high_level_conclusions', [])
        for k in ('video_descriptions', 'high_level_conclusions'):
            data[k] = [x if isinstance(x, str) else json.dumps(x, ensure_ascii=False) for x in (data[k] or [])]
        return json.dumps(data, ensure_ascii=False)

    def _control_model(self, conversations, tag):
        """Replaces tokenizer.apply_chat_template + vLLM generate (control.py:176-188) for control-32b-rl."""
        turns = conversations[1:]
        lines = []
        for i, t in enumerate(turns):
            last = i == len(turns) - 1
            lines.append(('[User turn]' if last else f'[Earlier {t["role"]} turn]') + '\n' + t['content'])
        return self._ask(self.llm, conversations[0]['content'], '\n\n'.join(lines), tag)

    def _verifier_model(self, messages, timeout=30):
        """control.get_response: GPT-4o judging an answer against the ground truth (control.eval_answer)."""
        system = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
        user = '\n'.join(c['text'] for m in messages if m['role'] == 'user' for c in m['content'] if c['type'] == 'text')
        return self._ask(self.verifier, system, user, f'gpt4o-verifier|{self.tag}|{self._qtag}'), 0

    # ---- scripted sensing -----------------------------------------------------------------------
    @staticmethod
    def _jpeg(color, size=(32, 32), fmt='JPEG'):
        from PIL import Image
        buf = io.BytesIO(); Image.new('RGB', size, color).save(buf, format=fmt)
        return base64.b64encode(buf.getvalue()).decode()

    def _read_clip(self, clip_path):
        """utils/video_processing.process_video_clip -> (video, frames, audio) for a scripted clip."""
        self._clip_path, self._clip_start = clip_path, self._graph.next_node_id
        return b'scripted-video', list(self._frames), b'scripted-audio'

    def _write_clips(self, video, run_dir):
        """Write each clip and its intermediate outputs (face detections, diarized speech) to disk."""
        clips, inter = run_dir / 'clips', run_dir / 'intermediate'
        clips.mkdir(); inter.mkdir()
        people = video['people']
        # one face-crop image per person (lossless, so every person's crop is distinct); the
        # memorization model is shown the person's face text in its place
        crops = {k: self._jpeg((40 + 13 * i, 200 - 11 * i, 90 + 7 * i), fmt='PNG') for i, k in enumerate(people)}
        for cid, clip in enumerate(video['clips']):
            path = clips / f'{cid}.mp4'
            path.write_text(clip['video'])
            self._clip_text[str(path)] = clip['video']
            faces = []
            for k, f in enumerate(clip['faces']):
                p, crop = people[f['person']], crops[f['person']]
                self._image_text[crop] = 'face crop: ' + p['face']
                emb = self._embed([p['face']])[0]
                for frame in f['frames']:
                    faces.append({'frame_id': frame, 'bounding_box': [16, 8, 40, 36], 'face_emb': emb, 'cluster_id': k,
                                  'extra_data': {'face_type': 'ortho', 'face_base64': crop,
                                                 'face_detection_score': '0.95', 'face_quality_score': '30.0'}})
            voices = []
            for s in clip['speech']:
                secs = lambda t: int(t.split(':')[0]) * 60 + int(t.split(':')[1])
                voices.append({'start_time': s['start'], 'end_time': s['end'], 'asr': s['text'],
                               'duration': secs(s['end']) - secs(s['start']), 'audio_segment': 'c2NyaXB0ZWQ=',
                               'embedding': self._embed([people[s['person']]['voice']])[0]})
            (inter / f'clip_{cid}_faces.json').write_text(json.dumps(faces))
            (inter / f'clip_{cid}_voices.json').write_text(json.dumps(voices))
        return {'clip_path': str(clips), 'mem_path': str(run_dir / 'memory.pkl'), 'intermediate_outputs': str(inter)}

    # ---- items ----------------------------------------------------------------------------------
    def items(self):
        out = []
        for v in self.videos.values():
            names = {k: p['name'] for k, p in v['people'].items()}
            lines = [f'Setting: {v["setting"]}', 'People: ' + '; '.join(f'{p["name"]} ({p["face"]})' for p in v['people'].values())]
            for cid, c in enumerate(v['clips']):
                speech = ' '.join(f'{names[s["person"]]}: "{s["text"]}"' for s in c['speech'])
                lines.append(f'Clip {cid} ({cid * 30}-{cid * 30 + 30} s): {c["video"]} Speech: {speech}')
            lines.append('Questions and reference answers:')
            lines += [f'Q{i + 1}: {q["question"]} Reference: {q["answer"]}' for i, q in enumerate(v['questions'])]
            out.append({'id': v['id'], 'judge_context': '\n'.join(lines)})
        return out

    def run(self, item, cut, sample):
        video = self.videos[item['id']]
        self.cut = set(cut)
        # The tag names the video, the sample and the stage, not the arm: arms whose prompts are
        # identical share the cached reply, so each comparison differs only where the cut changes a prompt.
        self.tag, self._errors = f'{video["id"]}|s{sample}', []
        run_dir = self.root / f'{video["id"]}-s{sample}-{uuid.uuid4().hex[:8]}'
        run_dir.mkdir()
        sample_paths = self._write_clips(video, run_dir)
        # memorization (memorization_memory_graphs.py:112-113)
        cfg = dict(json.loads((self.root / 'configs' / 'memory_config.json').read_text()),
                   img_matching_threshold=MATCH_THRESHOLD, audio_matching_threshold=MATCH_THRESHOLD)
        self._graph, self._reused = self.VideoGraph(**cfg), 0
        try:
            self.mm.streaming_process_video(self._graph, sample_paths)
        finally:
            import matplotlib.pyplot as plt
            plt.close('all')                   # memory_processing_qwen.py:80-100 draws the face crops in DETAIL logging
        graph = self._graph
        # control (control.py:162-207), one question at a time
        total_round = self.control.processing_config['total_round']
        answers, trajectories, correct, rounds, empty = [], [], [], [], 0
        for qi, qa in enumerate(video['questions']):
            self._qtag = f'q{qi}'
            data = {'id': f'{video["id"]}-q{qi}', 'mem_path': sample_paths['mem_path'],
                    'question': qa['question'], 'answer': qa['answer'],
                    'conversations': [{'role': 'system', 'content': self.control.system_prompt.format(question=qa['question'])},
                                      {'role': 'user', 'content': 'Searched knowledge: {}'}],
                    'finish': False, 'currenr_clips': []}
            used = 0
            for idx in range(total_round):
                if data['finish']:
                    break
                data['conversations'][-1]['content'] += self.control.instruction
                if idx == total_round - 1:
                    data['conversations'][-1]['content'] += FORCED
                reply = self._control_model(data['conversations'], tag=f'{self.tag}|control|q{qi}|round{idx}')
                data['conversations'].append({'role': 'assistant', 'content': reply})
                data = self.control.consumer(data)
                used += 1
                if not data['finish'] and '(The search result is empty.' in data['conversations'][-1]['content']:
                    empty += 1
            response = data.get('response')
            verdict = self.control.eval_answer(qa['question'], response, qa['answer']) if response else False
            answers.append(response.strip() if response else '(no answer)')
            correct.append(1.0 if verdict else 0.0); rounds.append(used)
            trajectories.append(data['conversations'])
        memories = {}
        for nid in graph.text_nodes:
            node = graph.nodes[nid]
            memories.setdefault(f'clip {node.metadata["timestamp"]}', []).extend(self.translate(graph, node.metadata['contents']))
        shutil.rmtree(run_dir, ignore_errors=True)
        if self._errors:
            raise RuntimeError('backbone call failed: ' + self._errors[0])
        return {
            'output': '\n\n'.join(f'Q{i + 1}: {q["question"]}\nA{i + 1}: {a}' for i, (q, a) in enumerate(zip(video['questions'], answers))),
            'answers': answers,
            'memories': memories,
            'trajectories': trajectories,
            'metrics': {
                'correct': round(sum(correct) / len(correct), 4),
                'control_rounds': round(sum(rounds) / len(rounds), 4),
                'empty_searches': empty,
                'text_memories': len(graph.text_nodes),
                'characters': len(getattr(graph, 'character_mappings', {}) or {}),
                'identities_reused': self._reused,
            },
        }
