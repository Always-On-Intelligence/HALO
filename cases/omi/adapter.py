"""HALO run-mode adapter for Omi (BasedHardware/omi, backend/ at commit 5a46ab0).

Configuration (case.yaml): wearable capture with an enrolled speech profile, a retained personal
backend, the agentic chat with its tools, and the built-in proactive-notification app (the
"mentor"); the rollout-gated desktop JIT features are off.

One item is two scripted days of one user. Each conversation is fed to the backend the way
the pendant's listen session feeds it, and each chat question the way the app's chat sends it:

  live segments  utils/app_integrations.trigger_realtime_integrations (per transcribed segment, as
                 routers/pusher.py:135 does): mentor buffer (utils/mentor_notifications.py), mentor
                 gate -> draft -> critic (utils/llm/proactive_notification.py), delivery, write-back.
  conversation   utils/conversations/process_conversation.process_conversation(trigger=CAPTURE_END):
  end            relevance rules, notes v2 (title, overview, tasks; utils/llm/conversation_processing.py),
                 persistence, vector metadata (utils/llm/chat.py), memory extraction
                 (utils/llm/memories.py -> working_observations.py), task write-back.
  chat question  the routers/chat.py send_message sequence (lines 446-600), reproduced in _chat():
                 store the human turn, read the cache-aligned history, run
                 utils/retrieval/graph.execute_chat_stream (the agentic tool loop of
                 utils/retrieval/agentic.py with the upstream tools), store the answer.

Replaced (see README and omi_harness/): every model client (utils/llm/clients.py) goes to the HALO
backbone; embeddings are all-MiniLM-L6-v2; Firestore, Pinecone, Typesense and Redis are in-memory
fakes behind the upstream database functions; FCM delivery is recorded; thread pools run inline;
speech is a scripted transcript whose speaker clusters carry the scripted result of the voice match.
Upstream telemetry, billing, rollout and shadow modules are inert stubs. The vendored modules see a
simulated clock and deterministic ids so that arms build identical prompts until a cut differs.

Cut sites (each blocks the channel where the receiver reads or the store is written; upstream
file:line of the call that the fake store or the adapter withholds):
  S->M  sensed evidence is not admitted to memory:
          processed conversation  utils/conversations/process_conversation.py:3157 (lifecycle write;
                                  omi_harness/fakes/utils/conversations/lifecycle.py)
          conversation vector     process_conversation.py:2365 -> database/vector_db.py:151 (Pinecone ns1)
          extracted memories      process_conversation.py:2053 (MemoryService.replace_conversation_memories)
          human chat turn         routers/chat.py:513 (chat_db.add_message, sender=human; adapter _chat)
  M->A  retained information does not reach Action (reads made while the mentor or the chat agent decides
        return nothing): user facts utils/app_integrations.py:785 -> utils/llms/memory.py:205
        (MemoryService.read); goals app_integrations.py:791 and utils/llm/chat.py:593; earlier mentor
        notifications app_integrations.py:802; past conversations app_integrations.py:851-864 (Pinecone ns1
        query database/vector_db.py:247, conversation store); chat history routers/chat.py:524-528
        (get_cache_aligned_messages); chat tools utils/retrieval/tools/memory_tools.py:269,443,
        conversation_tools.py:322,613,618, action_item_tools.py:270 (MemoryService, Typesense, Pinecone,
        task store)
  A->S  open tasks, the state of earlier actions, do not reach the extraction of a new transcript:
        database/vector_db.py:988 (find_similar_action_items, Pinecone ns4 query while Sensing), read by
        utils/conversations/notes_task_context.py:33 for the notes prompt at process_conversation.py:758
  M->S  the enrolled speech profile and the stored people are not applied to the incoming transcript:
        speaker labels as routers/listen/transcripts.py:1339-1350 assigns them (adapter _segments) and
        database/users.get_people_by_ids at process_conversation.py:3077 and utils/llm/memories.py:185
  A->M  action records are not written back: mentor notification utils/app_integrations.py:1187
        (database.chat.add_app_message); chat answer routers/chat.py:595 (chat_db.add_message, sender=ai;
        adapter _chat); extracted tasks process_conversation.py:2218 (create_action_items_batch) and
        database/vector_db.py:908 (Pinecone ns4); writes by chat tools action_item_tools.py:467
        (create_action_item) and preference_tools.py:148 (MemoryService.create_external_memory)
Omi does not revise its own mechanism in this configuration, so no evidence step is cut.
"""
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from halo.run.adapter import BaseAdapter

CASE = Path(__file__).resolve().parent

# Deployment flags that define the configuration. Everything else keeps the upstream default.
ENV = {
    # notes v2 is production-on since 2026-09-01 (utils/llm/conversation_processing.py:1525)
    'CONVERSATION_NOTES_V2_ENABLED': 'true',
    # the mentor runs its legacy gate/draft/critic pipeline by default (utils/app_integrations.py:1160)
    'MENTOR_PIPELINE': 'legacy',
    'OMI_SHAPED_AGENT_MODE': 'off',
    'PINECONE_API_KEY': '',
    'TOKENIZERS_PARALLELISM': 'false',
}
GAP_TO_PROCESS = 120   # seconds of silence before a pendant conversation is closed and processed
PROCESS_ATTEMPTS = 3
WORDS_PER_SECOND = 2.6


class Adapter(BaseAdapter):
    channels = {
        'S->M': 'transcripts become stored conversations, vectors and extracted memories; chat turns become chat history',
        'M->A': 'stored facts, conversations, tasks, notifications and chat history read by the mentor and the chat agent',
        'A->S': 'open tasks supplied to the extraction of a new transcript (dedup and completion)',
        'M->S': 'enrolled speech profile and stored people label who is speaking in the incoming transcript',
        'A->M': 'delivered mentor notifications, chat answers and created tasks written back to the user store',
    }
    steps = {}

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        for k, v in ENV.items():
            os.environ[k] = v
        if str(CASE) not in sys.path:
            sys.path.insert(0, str(CASE))
        from omi_harness import loader, netguard
        netguard.install()
        loader.install()
        from omi_harness.pinecone_fake import INDEX, install_pinecone_module
        from omi_harness.typesense_fake import install_typesense_module
        install_pinecone_module()
        install_typesense_module()
        import database.vector_db as vector_db
        vector_db.index = INDEX            # the Pinecone handle (database/vector_db.py:131)
        import database.chat as chat_db
        from models.chat import Message
        from models.conversation import CreateConversation
        from models.transcript_segment import TranscriptSegment, transcript_segment_for_client
        from utils import app_integrations, mentor_notifications
        from utils.conversations import process_conversation as pc
        from utils.conversations.processing_trigger import ProcessingTrigger
        from utils.llm.goals import extract_and_update_goal_progress
        from utils.llms import memory as llms_memory
        from utils.retrieval import graph
        from omi_harness.llm_bridge import BRIDGE, EMBEDDINGS
        from omi_harness.store import STORE
        self.loader, self.STORE, self.BRIDGE, self.EMB = loader, STORE, BRIDGE, EMBEDDINGS
        self.chat_db, self.Message, self.CreateConversation = chat_db, Message, CreateConversation
        self.TranscriptSegment, self.for_client = TranscriptSegment, transcript_segment_for_client
        self.app_integrations, self.mentor_notifications, self.pc = app_integrations, mentor_notifications, pc
        self.ProcessingTrigger, self.goal_progress = ProcessingTrigger, extract_and_update_goal_progress
        self.llms_memory, self.graph = llms_memory, graph
        BRIDGE.llm = llm
        data = json.loads((CASE / 'inputs' / 'days.json').read_text())
        self.user, self.scenarios = data['user'], {s['id']: s for s in data['items']}

    # ---- items ------------------------------------------------------------------------------
    def items(self):
        return [{'id': s['id'], 'judge_context': s['judge_context']} for s in self.scenarios.values()]

    # ---- one run ----------------------------------------------------------------------------
    def _reset(self, scen, cut, sample):
        S = self.STORE
        S.reset()
        S.cut = set(cut)
        self.loader.SIM_UUID.reset(f'{scen["id"]}|s{sample}')
        self.loader.STUB_CALLS.clear()
        self.BRIDGE.base, self.BRIDGE.stage, self.BRIDGE.calls = f'{scen["id"]}|s{sample}', '', []
        # upstream module state that would otherwise leak between runs in this worker
        self.llms_memory.clear_prompt_data_cache()
        buf = self.mentor_notifications.message_buffer
        buf.buffers.clear()
        u = self.user
        uid = u['uid']
        S.users[uid] = {'name': u['name'], 'language': u.get('language', 'en'), 'time_zone': u['time_zone'],
                        'mentor_frequency': u.get('mentor_frequency', 3)}
        S.people[uid] = {p['id']: {'id': p['id'], 'name': p['name'], 'created_at': None, 'updated_at': None,
                                   'deleted': False} for p in u.get('people', [])}
        S.goals[uid] = [dict(g) for g in u.get('goals', [])]
        self.tz = ZoneInfo(u['time_zone'])
        self.loader.CLOCK.set(datetime.fromisoformat(scen['days'][0]['date'] + 'T07:00').replace(tzinfo=self.tz))
        buf.last_cleanup = self.loader.CLOCK.time()
        return uid

    def run(self, item, cut, sample):
        scen = self.scenarios[item['id']]
        uid = self._reset(scen, cut, sample)
        record = {'conversations': [], 'notifications': [], 'chats': []}
        for day in scen['days']:
            for ev in day['events']:
                if ev['type'] == 'conversation':
                    self._conversation(uid, day['date'], ev, record)
                elif ev['type'] == 'chat':
                    self._chat(uid, day['date'], ev, record)
        return self._result(scen, record)

    # ---- a pendant conversation -------------------------------------------------------------
    def _segments(self, ev):
        """Scripted speech. `voice` is the result of matching the cluster's audio against the enrolled
        speech profile ('user') or a stored person's samples (a person id); routers/listen/transcripts.py
        applies that match to the segment at lines 1339-1350. M->S withholds it."""
        segs, t = [], 0.0
        withhold = 'M->S' in self.STORE.cut
        for i, s in enumerate(ev['segments']):
            start = float(s.get('t', t))
            end = start + max(1.5, len(s['text'].split()) / WORDS_PER_SECOND)
            t = end + 1.0
            voice = s.get('voice')
            if voice and withhold:
                self.STORE.cut_active('M->S', 'speech-profile labels (routers/listen/transcripts.py:1339)')
                voice = None
            segs.append(self.TranscriptSegment(
                id=f'{ev["id"]}-{i:02d}', text=s['text'], speaker=f'SPEAKER_{s["spk"]:02d}', speaker_id=s['spk'],
                speaker_id_scope=f'session:{ev["id"]}', is_user=voice == 'user',
                person_id=voice if voice and voice != 'user' else None, start=start, end=end, stt_provider='scripted'))
        return segs

    def _conversation(self, uid, date, ev, record):
        S, clock = self.STORE, self.loader.CLOCK
        start = datetime.fromisoformat(f'{date}T{ev["start"]}').replace(tzinfo=self.tz)
        segs = self._segments(ev)
        delivered_before = len(S.delivered)
        # live: one pusher batch per transcribed segment (routers/pusher.py:135)
        self.BRIDGE.stage = f'{ev["id"]}/live'
        for seg in segs:
            clock.set(start + timedelta(seconds=seg.end))
            S.phase = 'action'
            asyncio.run(self.app_integrations.trigger_realtime_integrations(
                uid, [self.for_client(seg.model_dump())], ev['id'], source='omi'))
        # end of capture: the conversation is closed after the silence gap and processed
        clock.set(start + timedelta(seconds=segs[-1].end + GAP_TO_PROCESS))
        S.phase = 'sensing'
        before_tasks = dict(S.action_items.get(uid, {}))
        conversation, error = None, None
        for attempt in range(PROCESS_ATTEMPTS):
            # A failed finalization is retried by the durable job (utils/conversations/finalizer.py);
            # each retry is a fresh model sample, so the attempt number is part of the cache tag.
            self.BRIDGE.stage = f'{ev["id"]}/process' + (f'/retry{attempt}' if attempt else '')
            try:
                conversation = self.pc.process_conversation(
                    uid, 'en',
                    self.CreateConversation(started_at=start, finished_at=start + timedelta(seconds=segs[-1].end),
                                            transcript_segments=segs, source='omi', language='en'),
                    trigger=self.ProcessingTrigger.CAPTURE_END)
                break
            except Exception as e:      # upstream raises HTTPException(500) when the notes reply cannot be parsed
                error = f'{type(e).__name__}: {e}'
        S.phase = None
        if conversation is None:
            record['conversations'].append({'id': ev['id'], 'date': date, 'start': ev['start'], 'title': '',
                                            'overview': f'(processing failed after {PROCESS_ATTEMPTS} attempts: {error})',
                                            'tasks': [], 'open_tasks_before': [], 'memories': [],
                                            'notifications': [d['body'] for d in S.delivered[delivered_before:]],
                                            'discarded': False, 'failed': True})
            for d in S.delivered[delivered_before:]:
                record['notifications'].append({'day': date, 'during': ev['id'], 'text': d['body']})
            return
        st = conversation.structured
        record['conversations'].append({
            'id': ev['id'], 'date': date, 'start': ev['start'],
            'title': st.title, 'overview': st.overview,
            'tasks': [_task(a, self.tz) for a in st.action_items],
            'open_tasks_before': [_task_row(t, self.tz) for t in before_tasks.values() if not t.get('completed')],
            'memories': [e['content'] for e in S.log
                         if e['event'] == 'memory.extracted' and e.get('conversation_id') == conversation.id],
            'notifications': [d['body'] for d in S.delivered[delivered_before:]],
            'discarded': bool(conversation.discarded),
        })
        for d in S.delivered[delivered_before:]:
            record['notifications'].append({'day': date, 'during': ev['id'], 'text': d['body']})

    # ---- a chat question (routers/chat.py send_message, lines 446-600) ----------------------
    def _chat(self, uid, date, ev, record):
        S, clock, M = self.STORE, self.loader.CLOCK, self.Message
        clock.set(datetime.fromisoformat(f'{date}T{ev["at"]}').replace(tzinfo=self.tz))
        self.BRIDGE.stage = f'{ev["id"]}'
        message = M(id=str(self.loader.SIM_UUID.uuid4()), text=ev['text'], created_at=clock.now(), sender='human',
                    type='text', app_id=None)
        self.chat_db.add_message(uid, message.model_dump())                       # routers/chat.py:513
        self.goal_progress(uid, ev['text'])          # routers/chat.py:516-517 (a goal update, not an Action read)
        S.phase = 'action'
        messages = list(reversed(M.deserialize_many_safe(
            self.chat_db.get_cache_aligned_messages(uid, app_id=None, chat_session_id=None))))   # :521-531
        if not messages or messages[-1].id != message.id:
            messages.append(message)    # the turn just sent is always the last message the agent sees
        callback_data = {}

        async def _drain():
            async for _ in self.graph.execute_chat_stream(uid, messages, None, cited=True, callback_data=callback_data,
                                                          chat_session=None, context=None, platform='ios',
                                                          client_tz=self.user['time_zone']):
                pass
        asyncio.run(_drain())
        response = callback_data.get('answer') or ''
        # process_message (routers/chat.py:539-597): strip citations, store the answer
        cited = {int(i) for i in re.findall(r'\[(\d+)\]', response)}
        if cited:
            response = re.sub(r'\[\d+\]', '', response)
        ai = M(id=str(self.loader.SIM_UUID.uuid4()), text=response, created_at=clock.now(), sender='ai', app_id=None,
               type='text')
        self.chat_db.add_message(uid, ai.model_dump())                            # routers/chat.py:595
        S.phase = None
        record['chats'].append({'day': date, 'at': ev['at'], 'id': ev['id'], 'question': ev['text'], 'answer': response,
                                'expect': ev.get('expect', []),
                                'tools': [c for c in self.BRIDGE.calls if c['stage'] == ev['id']]})

    # ---- outputs ----------------------------------------------------------------------------
    def _result(self, scen, record):
        S = self.STORE
        from omi_harness.store import cosine
        last_day = scen['days'][-1]['date']
        acted, captured = [], []
        starts = {c['id']: c['start'] for c in record['conversations']}
        for n in record['notifications']:
            acted.append((n['day'], starts.get(n['during'], ''), f'[{n["day"]} {starts.get(n["during"], "")}, during the '
                          f'conversation {n["during"]}] Omi pushed a notification: {n["text"]}'))
        for q in record['chats']:
            acted.append((q['day'], q['at'], f'[{q["day"]} {q["at"]}] Alex asked in chat: {q["question"]}\n'
                          f'Omi answered: {q["answer"] or "(no answer)"}'))
        acted = [text for _, _, text in sorted(acted, key=lambda x: (x[0], x[1]))]
        for c in record['conversations']:
            captured.append(f'Conversation {c["id"]} ({c["date"]} {c["start"]}): {c["title"]}\n{c["overview"]}\n'
                            f'Tasks created: {json.dumps(c["tasks"], ensure_ascii=False)}\n'
                            f'Facts remembered: {json.dumps(c["memories"], ensure_ascii=False)}')
        last = [c for c in record['conversations'] if c['date'] == last_day]
        open_before = sorted({t for c in last for t in c['open_tasks_before']})
        tasks_last = [t for c in last for t in c['tasks']]
        # metrics
        hits = total = 0
        for q in record['chats']:
            for kw in q['expect']:
                total += 1
                hits += any(alt.lower() in (q['answer'] or '').lower() for alt in kw.split('|'))
        notes = [n['text'] for n in record['notifications']]
        repeats = 0
        if len(notes) > 1:
            vecs = self.EMB.embed_documents(notes)
            repeats = sum(any(cosine(vecs[i], vecs[j]) >= 0.75 for j in range(i)) for i in range(1, len(vecs)))
        dup = 0
        if tasks_last and open_before:
            a, b = self.EMB.embed_documents(tasks_last), self.EMB.embed_documents(open_before)
            dup = sum(any(cosine(x, y) >= 0.7 for y in b) for x in a)
        speakers = ('Speakers: in every conversation Alex is the account owner (his enrolled voice); Maya, Sam, Jordan '
                    'and Priya are people Alex has saved in Omi; anyone else is not known to Omi.')
        return {
            'output': '\n\n'.join(acted) if acted else '(Omi sent no notification and answered nothing)',
            'output_capture': '\n\n'.join(captured),
            'context_capture': scen['judge_context'] + '\n' + speakers,
            'output_tasks': json.dumps(tasks_last, ensure_ascii=False) if tasks_last else '(no task created)',
            'context_tasks': (scen['judge_context'] + '\nOpen tasks Alex already had before the last day\'s '
                              f'conversation: {json.dumps(open_before, ensure_ascii=False)}\nThe output lists the '
                              'tasks Omi created from that conversation.'),
            'record': record,
            'withheld': dict(S.withheld),
            'calls_by_feature': _count(c['feature'] for c in self.BRIDGE.calls),
            'stub_calls': dict(self.loader.STUB_CALLS),
            'metrics': {
                'notifications': len(notes),
                'repeated_notifications': repeats,
                'chat_expected_hits': round(hits / total, 4) if total else None,
                'memories_written': sum(1 for e in S.log if e['event'] == 'memory.write'),
                'tasks_last_day': len(tasks_last),
                'duplicate_tasks_last_day': dup,
                'backbone_calls': len(self.BRIDGE.calls),
                'failed_conversations': sum(1 for c in record['conversations'] if c.get('failed')),
            },
        }


def _task(item, tz) -> str:
    due = f' (due {item.due_at.astimezone(tz).strftime("%a %b %d %H:%M")})' if item.due_at else ''
    return item.description + due


def _task_row(row, tz) -> str:
    due = row.get('due_at')
    return row['description'] + (f' (due {due.astimezone(tz).strftime("%a %b %d %H:%M")})' if due else '')


def _count(it):
    out = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out
