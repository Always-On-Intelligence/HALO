"""HALO run-mode adapter for AiGet (Synteraction-Lab/AiGet at commit 92b17f8).

Each item is one moment seen through the glasses: five first-person frames written as text, a
location, and a timestamp. The adapter calls AiGet's own pipeline,
src/Module/LLM/LLMPipeline.get_llm_response, the way the timer path of src/Frontend.py calls it.
It then writes the shown suggestions to the suggestion history, as Frontend.process_response does,
and visits the same moment a second time.

Only the model clients are replaced: calls to Gemini, GPT, and Groq go to the HALO backbone.
AiGet's prompts, profile insertion, history retrieval and novelty filter (all-MiniLM-L6-v2), and
output processing all run from the upstream code. Temperature and token limits are not passed on,
because the CLI backends do not expose them.

Cut sites:
  M->S  the user profile is removed from the perception prompt (task_description/context_description)
  M->A  the user profile is removed from the generation prompt (task_description/knowledge_generation_filter)
  A->M  suggestions shown on the first visit are not written to the suggestion history
"""
import json, sys, types
from pathlib import Path
from collections import deque
from halo.run.adapter import BaseAdapter

CORE = Path(__file__).resolve().parent / 'core'   # vendored upstream code, see core/SOURCE.md
PLACEHOLDER = '[USER_PROFILE_PLACEHOLDER]'
# Frontend.__init__ default: knowledge_generation_model="gemini-pro-001", so generation takes the Gemini path.
GENERATION_MODEL = 'gemini-pro-001'
GEMINI_NOTES = "Above images are the user's 5 second-long fish-eye FPV frames with Gaze Circle/Dots in red. "


class Adapter(BaseAdapter):
    channels = {
        'M->S': 'user profile inserted into the perception prompt (context_description)',
        'M->A': 'user profile inserted into the generation prompt (knowledge_generation_filter)',
        'A->M': 'shown suggestions written to the suggestion history that later generation calls read',
    }
    steps = {}   # AiGet does not revise its own mechanism, so no evidence step is cut

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        self.cut, self.tag = set(), ''
        self._install_stubs()
        sys.path.insert(0, str(CORE))
        from src.Module.LLM import LLMPipeline
        from src.Utilities.process_json import detect_json
        from src.Utilities.sentence_similarity import model as minilm
        from sentence_transformers import util
        self.pipeline, self.detect_json, self.minilm, self.st_util = LLMPipeline, detect_json, minilm, util
        self._load = LLMPipeline.load_task_description
        LLMPipeline.load_task_description = self._load_task_description
        self.profile = self._load('user_profile')
        self.scenes = json.loads((Path(case_dir) / 'inputs' / 'scenes.json').read_text())['scenes']

    # ---- cut sites -------------------------------------------------------------------------
    def _load_task_description(self, task_type):
        text = self._load(task_type)
        if (task_type == 'context_description' and 'M->S' in self.cut) or \
           (task_type == 'knowledge_generation_filter' and 'M->A' in self.cut):
            text = text.replace(PLACEHOLDER, '')   # the pipeline's own .replace() then has nothing to fill
        return text

    def _record(self, history, response):
        """Frontend.process_response (src/Frontend.py, lines 476-492): shown suggestions extend the history."""
        if response.get('Suggestion Type') == 'None':
            return history
        if response.get('Suggestion Type') in ('Danmaku', 'Live Comments'):
            shown = list(response.get('English AI Suggestion') or [])
        else:
            v = (response.get('AI Suggestion') or {}).get('v')
            shown = [v] if isinstance(v, str) else list(v or [])
        if 'A->M' in self.cut:
            return history
        return history + shown

    # ---- model clients -> HALO backbone ------------------------------------------------------
    def _install_stubs(self):
        adapter = self

        def get_gemini_response(system_instruction=None, image_frame=None, image_path=None, image_queue=None,
                                text=None, max_tokens=8192, temperature=0.0, history=None,
                                model='gemini-2.0-flash-exp', image_size=512, image_process_notes=GEMINI_NOTES):
            # Mirrors src/Module/LLM/Gemini.py: frames first, then the notes and the text, and the
            # history as an earlier model turn.
            parts = []
            if image_queue is not None:
                parts += [str(f) for f in list(image_queue)]
            elif image_frame is not None or image_path is not None:
                parts.append(str(image_frame if image_frame is not None else image_path))
            if text is not None:
                if parts:
                    text = image_process_notes + text
                parts.append(text)
            user = '\n'.join(parts)
            if history:
                user = ('[Earlier model turn]\nSuggestion History (*avoid similar content in the following list*): '
                        + str(history) + '\n\n[User turn]\n' + user)
            return adapter.llm(system_instruction or '', user, tag=adapter.tag)

        def _messages(conversation_history, text):
            system = '\n\n'.join(m['content'] if isinstance(m['content'], str) else json.dumps(m['content'])
                                 for m in conversation_history or [] if m['role'] == 'system')
            user = '\n\n'.join(m['content'] if isinstance(m['content'], str) else json.dumps(m['content'])
                               for m in conversation_history or [] if m['role'] != 'system')
            return system, (user + ('\n\n' + text if text else '')).strip()

        def get_gpt_response(image_frame=None, text=None, conversation_history=None, max_tokens=4096, image_path=None,
                             image_queue=None, model='gpt-4o', temperature=0.0):
            system, user = _messages(conversation_history, text)
            return adapter.llm(system, user, tag=adapter.tag)

        def get_groq_response(text=None, conversation_history=None, max_tokens=4096, model='llama-3.1-70b-versatile',
                              temperature=0.0):
            system, user = _messages(conversation_history, text)
            return adapter.llm(system, user, tag=adapter.tag)

        for name, fn in (('Gemini', get_gemini_response), ('GPTVision', get_gpt_response), ('Groq', get_groq_response)):
            mod = types.ModuleType(f'src.Module.LLM.{name}')
            setattr(mod, fn.__name__, fn)
            sys.modules[mod.__name__] = mod
        sys.modules.setdefault('cv2', types.ModuleType('cv2'))   # imported by LLMPipeline, used only in its __main__

    # ---- one moment, visited twice ------------------------------------------------------------
    def items(self):
        return [{'id': s['id'], 'judge_context': json.dumps({'user profile': self.profile, 'location': s['location']},
                                                            ensure_ascii=False)} for s in self.scenes]

    def _visit(self, scene, history):
        """Frontend.send_data_thread with initiation='timer', no user comment, simulated location."""
        send_message = {'Request Mode': 'timer', 'user comments': '', 'location': scene['location'],
                        'timestamp': scene['timestamp'], 'Response Style': 'Live Comments'}
        response, location = self.pipeline.get_llm_response(
            image_queue=deque(scene['frames']), text=send_message, user_profile=None, history=history,
            user_comment='', language='en', last_response=None, knowledge_generation_model=GENERATION_MODEL)
        if location is None:   # everything was filtered as repeated: nothing is shown or recorded
            return None, []
        data = self.detect_json(response)
        return data, data.get('English AI Suggestion') or []

    def run(self, item, cut, sample):
        scene = next(s for s in self.scenes if s['id'] == item['id'])
        self.cut = set(cut)
        # The tag names the moment and the sample, not the arm: arms whose prompts are identical
        # share the cached reply, so each comparison differs only where the cut changes a prompt.
        self.tag = f'{scene["id"]}|s{sample}'
        history = []
        first, shown1 = self._visit(scene, None)          # first visit: no AI response yet, history is None
        if first is not None:
            history = self._record(history, first)
            second, shown2 = self._visit(scene, history)  # revisit reads the history (Frontend line 410)
        else:
            second, shown2 = self._visit(scene, None)     # nothing shown, so last_ai_response is still None
        sims = []
        if shown1 and shown2:
            e1, e2 = self.minilm.encode(shown1, convert_to_tensor=True), self.minilm.encode(shown2, convert_to_tensor=True)
            sims = self.st_util.cos_sim(e2, e1).max(dim=1).values.tolist()
        earlier = json.dumps(shown1, ensure_ascii=False)
        return {
            'output': json.dumps(shown1, ensure_ascii=False) if shown1 else '(nothing shown)',
            'output_revisit': json.dumps(shown2, ensure_ascii=False) if shown2 else '(nothing shown)',
            'context_revisit': item['judge_context'] + '\nShown to the user at this place earlier: ' + earlier,
            'history_at_revisit': history,
            'perception': (first or {}).get('Context Description'),
            'metrics': {
                'shown': len(shown1),
                'shown_revisit': len(shown2),
                # AiGet's own novelty threshold (filter_new_items, threshold=0.75)
                'revisit_repeats': sum(s >= 0.75 for s in sims),
                'revisit_mean_max_similarity': round(sum(sims) / len(sims), 4) if sims else None,
            },
        }
