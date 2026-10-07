"""HALO run-mode adapter for AssistantX (AssistantX-Agent/AssistantX at commit 35ab271).

AssistantX is an office robot: a mobile chassis with a QR-locked locker, driven over WeChat by a
loop of perception, planning, decision and reflection model calls (PPDR4X). The run executes the
upstream loop itself: core/OfficeAssistant/main.py runs unchanged as __main__ (runpy), with the
upstream prompt builders (core/OfficeAssistant/prompt_test.py), chat helpers (core/OfficeAssistant/chat.py)
and state module (core/common/global_var.py). Robot '大白1号' is used, the main.py:163 branch that has
the planning step. Each item is one WeChat instruction; the loop runs until the model chooses Stop,
or for at most MAX_STEPS iterations.

Replaced (stub modules installed in sys.modules before main.py runs):
  model client   OfficeAssistant.api.inference_chat (GPT-4o over HTTP) -> HALO backbone. The reflection
                 call (main.py:405-411) gets a fixed reply instead: reflect_flag is never True
                 (main.py:180, 417), so main.py only prints that reply.
  router         OfficeAssistant.prompt_assx.to_witch_robot (source not in the repository) -> always
                 '大白1号 <message>'.
  WeChat         common.wechat.WechatServer -> delivers scripted messages through main.onmessage and
                 hands the robot's messages and QR images to the simulated office.
  robot, locker  socket_server_dabai.send_dabai_command, handing.ocSelect / img_encode (module not in
                 the repository) -> simulated chassis and locker. ocSelect follows the commented-out
                 common/LockApi.py:64-85, with scans scripted instead of read from the door magnet.
  phone, files   common.andro_operation.Forward_file_on_Wechat (same success string as upstream).
  clock, sleep   main.py's datetime/time/threading globals -> scripted clock, no-op sleep, synchronous
                 thread (so the locker watcher starts deterministically).
People reply by fixed rules from inputs/office.json; no model plays them.

Cut sites (receiving end):
  M->S  main.py:190-192 passes priori_knowledge (the persistent relational graph, read at main.py:165 by
        prompt_test.py:385-388) to get_perception_prompt, inserted at prompt_test.py:414-416.
        Cut: the perception prompt gets an empty graph.
  M->A  main.py:222-225 and main.py:231-235 pass priori_knowledge to get_planning_prompt
        (prompt_test.py:463) and get_action_prompt (prompt_test.py:20-22). Cut: both get an empty graph.
  A->S  (1) the robot's own WeChat messages, written to the chat buffers as 'Assitant(yourself)' lines at
        main.py:277, 281, 285, 297, 301, 305, reach perception at main.py:190-192 (prompt_test.py:418-431),
        which must judge whether each person 'has done what you asked him to do' (prompt_test.py:435, 442).
        Cut: the perception prompt gets the buffers without those lines.
        (2) Send QR code hands (person, item) to ocSelect (main.py:316-321), which labels the locker
        door event with them (LockApi.py:83) in global_var.locker_info, read at main.py:191 and 235.
        Cut: the locker reports only that its door opened and closed.
Not cut: S->M and A->M. The only write to the graph (main.py:357-370, the Stop branch) is overwritten
by read_prior_knowledge() at main.py:165 on the next iteration; in between only the discarded
reflection prompt reads it. Chat and action histories are task buffers that main.py:377-397 clears,
which the survey configuration excludes from retention. No evidence-step cut: the reflection's
attribution judgment never leaves main.py (see above) and nothing revises the mechanism.
"""
import importlib, json, os, re, runpy, shutil, sys, tempfile, traceback, types
from datetime import datetime, timedelta
from pathlib import Path
from halo.run.adapter import BaseAdapter

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core'
MAIN = CORE / 'OfficeAssistant' / 'main.py'
MAX_STEPS = 5                     # loop iterations per item: 3 backbone calls each, plus one at Stop
ROBOT = '大白1号'                  # main.py:163
CHARGING = '充电桩'                # main.py:356, where Stop sends the robot
SELF = 'Assitant(yourself)'       # upstream spelling, main.py:277-305
ROOMS = {'Office Work': '48898365596@chatroom', 'Study Group': '50562147484@chatroom'}   # global_var.room_name
AUTO_REPLY = '机器人' + ROBOT + '为您服务~'   # main.py:53, sent back for every incoming message
REFLECTION_REPLY = ('### Completed contents ###\n(not requested)\n### Thought ###\n(not requested)\n'
                    '### Reflect ###\n(not requested)\n### Answer ###\nY')
ASK_RE = r"Ask\s*\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)"   # main.py:288


class EpisodeEnd(Exception):
    pass


class Book(dict):
    """Chat buffers: a missing contact starts empty (the upstream dicts raise KeyError). Prints as a dict."""
    def __missing__(self, key):
        return ''


class Contacts(dict):
    """WeChat contact book (global_var.chat_name/room_name). Unknown keys resolve case-insensitively and
    without quotes; a name that matches nobody gives None (the upstream dict raises KeyError)."""
    def __missing__(self, key):
        k = str(key).strip(' "\'').lower()
        for name, wxid in self.items():
            if name.lower() == k:
                return wxid
        return None


def _mentions(text, aliases):
    t = (text or '').lower()
    return any(re.search(r'(?<![a-z])' + re.escape(a.lower()) + r'(?:s|es)?(?![a-z])', t) for a in aliases)


def _strip_self(book):
    return Book({k: ''.join(l for l in v.splitlines(keepends=True) if SELF not in l) for k, v in book.items()})


class Office:
    """The simulated office: robot chassis, locker, WeChat contacts and people answering by rules."""

    def __init__(self, spec, task, adapter):
        self.spec, self.task, self.adapter = spec, task, adapter
        self.people = json.loads(json.dumps(spec['people']))
        for name, extra in (task.get('knows') or {}).items():
            self.people[name]['knows'] = extra + self.people[name]['knows']
        self.items = {k: dict(v, signed_by=None) for k, v in json.loads(json.dumps(spec['items'])).items()}
        self.wx = {p['wxid']: n for n, p in self.people.items()}
        self.clock = datetime.strptime(task['time'], '%Y-%m-%d %H:%M')
        self.at, self.target, self.status = 'Charging station', None, 'Idle at the charging station.'
        self.locker, self.qr, self.watch, self.files, self.sent_file = [], {}, None, {}, None
        self.told = {n: [] for n in self.people}           # what the robot said to each person
        self.inbox, self.complained, self.qr_complained, self.away_told, self.confirmed = [], set(), set(), set(), set()
        self.steps, self.n_perception, self._perc_at_monitor = 0, 0, 0
        self.stopped, self.stop_action, self.graph_update = False, None, None
        self.log, self.trace, self.step_rec = [], [], None
        self.counts = {'messages': 0, 'qr': 0, 'moves': 0, 'auto_replies': 0, 'undelivered': 0}
        self.qr_used, self.qr_sent, self.scanned = set(), [], {}     # scanned: person -> what they did at the locker
        self.g = None                                         # main.py's module globals

    # ---- helpers ------------------------------------------------------------------------------
    def hm(self):
        return self.clock.strftime('%H:%M')

    def person(self, name):
        k = str(name or '').strip(' "\'').lower()
        for n, p in self.people.items():
            if k == n.lower() or any(k == a.lower() for a in p['aliases']):
                return n
        return None

    def resolve_marker(self, target):
        t = str(target).strip(' "\'').lower()
        best = None
        for m, aliases in self.spec['markers'].items():
            for a in [m] + aliases:
                if a.lower() in t and (best is None or len(a) > best[1]):
                    best = (m, len(a))
        for n, p in self.people.items():
            for a in p['aliases']:
                if _mentions(t, [a]) and (best is None or len(a) > best[1]):
                    best = (p['marker'], len(a))
        return best[0] if best else None

    def item_mentioned(self, text):
        return [k for k, it in self.items.items() if _mentions(text, it['aliases'])]

    def goal(self, item):
        return next((g for g in self.task['goal'] if g['item'] == item), None)

    def ready_for(self, item, person):
        g = self.goal(item)
        return bool(g and g['to'] == person and (not g.get('signed_by') or self.items[item]['signed_by'] == g['signed_by']))

    def note(self, text):
        self.log.append(f'{self.hm()} {text}')

    # ---- WeChat (stubbed WechatServer) ------------------------------------------------------------
    def attach(self, server):
        g = server.func_on_msgs.__globals__        # main.py's namespace; onmessage is defined there
        self.g, self.server = g, server
        office = self
        g['datetime'] = type('SimDatetime', (), {'now': staticmethod(lambda: office.clock)})
        g['time'] = types.SimpleNamespace(sleep=lambda s: None)
        g['threading'] = types.SimpleNamespace(Thread=_SyncThread)
        t = self.task
        self.incoming(t['from'], t['instruction'])
        self.note(f'{t["from"]} to robot: {t["instruction"]}')
        if t.get('file'):
            self.sent_file = (t['from'], t['file'])
            self.incoming(t['from'], t['file'], file=True)
            self.note(f'{t["from"]} sent the robot a file: {t["file"]}')

    def incoming(self, name, text, file=False, group=None):
        p = self.people[name]
        msg = _WechatMessage(FromUserName=ROOMS[group] if group else p['wxid'], ToUserName='robot', MsgType=1,
                             Content=text, ActionNickName=name,
                             PushContent=f'{name}: ' + ('[文件]' if file else text))
        self.g['onmessage'](self.server, msg)

    def say(self, to, text):
        if text == AUTO_REPLY:
            self.counts['auto_replies'] += 1
            return
        action = (self.g or {}).get('action', '')
        m = re.search(ASK_RE, action or '')
        is_ask = bool(m and m.group(2).strip(' "\'') == text)
        group = next((r for r, rid in ROOMS.items() if rid == to), None)
        name = self.wx.get(to)
        if group:
            self.counts['messages'] += 1
            self._effect(f'message to the {group} group: "{text}"')
            self.inbox.append((None, group, text, is_ask))
        elif name:
            self.counts['messages'] += 1
            self.told[name].append(text)
            self._effect(f'message to {name}: "{text}"')
            self.inbox.append((name, None, text, is_ask))
        else:
            self.counts['undelivered'] += 1
            self._effect(f'message not delivered (no such contact): "{text}"')

    def say_image(self, to, img):
        desc = img[len('[QR code: '):-1] if isinstance(img, str) and img.startswith('[QR code: ') else str(img)
        name = self.wx.get(to)
        if name:
            self.counts['qr'] += 1
            self.qr[name] = desc
            self.qr_sent.append(name)
            self._effect(f'QR code to {name} for "{desc}"')
        else:
            self._effect(f'QR code not delivered (no such contact) for "{desc}"')

    def forward(self, src, dst):
        s, d = self.person(src), self.person(dst)
        ok = bool(self.sent_file and s == self.sent_file[0] and d)
        self._effect(f'forwarded {"the file " + repr(self.sent_file[1]) if ok else "a file it does not have"} '
                     f'from {src} to {dst}')
        if ok:
            self.files.setdefault(d, []).append(self.sent_file[1])
            if self.people[d].get('prints') and 'printout' not in self.items:
                self.items['printout'] = {'name': f'printout of {self.sent_file[1]}', 'signed_by': None,
                                          'aliases': ['printout', 'printed', 'print', 'slides', 'copies'], 'holder': d,
                                          'made_for_robot': True}
        return f"Successful forwarding of electronic files from {src} to {dst}"   # common/andro_operation.py:105-108

    # ---- robot and locker (stubbed sockets and 'handing') ----------------------------------------------
    def send_dabai_command(self, cmd, arg=None):
        if cmd == 'monitor_move_status':
            if self.n_perception == self._perc_at_monitor:
                self._step_start()          # main.py:175, top of an iteration
            else:
                self._post_action()         # main.py:402, after the action was executed
            self._perc_at_monitor = self.n_perception
            return self.status
        if cmd == 'move_marker':
            if arg == CHARGING:             # main.py:356, the Stop branch
                self.stopped = True
                self.stop_action = self.g.get('action')
                self._effect('Stop: the robot returns to the charging station')
                self.target = 'Charging station'
                return 'ok'
            self.counts['moves'] += 1
            m = self.resolve_marker(arg)
            self.target = m or ('?' + str(arg))
            self._effect(f'robot drives to {m}' if m else f'robot cannot drive to "{arg}" (no such marker)')
        return 'ok'

    def ocSelect(self, person_name, item=''):
        self.watch = (person_name, item)    # the latest QR code's watcher replaces the previous one (main.py:318-320)

    def img_encode(self, path='encrypted_qrcode.png', itme_name=''):
        return f'[QR code: {itme_name}]'

    # ---- one loop iteration --------------------------------------------------------------------------
    def _effect(self, text):
        if self.step_rec is not None:
            self.step_rec['effects'].append(text)

    def on_reply(self, stage, reply):
        if self.step_rec is not None:
            self.step_rec[stage + '_reply'] = reply

    def _post_action(self):
        rec = self.step_rec
        rec['action'] = self.stop_action if self.stopped else self.g.get('action')
        if self.stopped:
            self.graph_update = self.g.get('item_pos')
        if self.target and self.target != self.at:
            self.status = f'Moving to {self.target.lstrip("?")}.'

    def _step_start(self):
        if self.steps:
            end = ('stopped' if self.stopped else
                   'stalled: count was reset to 0 without Stop (main.py:349)' if (self.g.get('count') or 0) < 1 else
                   'step limit' if self.steps >= MAX_STEPS else None)
            self.clock += timedelta(minutes=2)
            self._arrive()
            if end:                       # the cap stops the robot's decisions, not the office: the last
                self._scans(final=True)   # instructions still play out (arrival and scans, no new replies)
                raise EpisodeEnd(end)
            self._replies()
            self._scans()
        self.steps += 1
        self.step_rec = {'step': self.steps, 'time': self.hm(), 'status': self.status, 'effects': []}
        self.trace.append(self.step_rec)
        self.log.append(f'Step {self.steps} ({self.hm()})')

    def _arrive(self):
        if self.target is None:
            self.status = f'Idle at {self.at}.'
            return
        if self.target.startswith('?'):
            self.status = f'Failed to move to {self.target[1:]}: no such marker. Idle at {self.at}.'
        else:
            self.at = self.target
            self.status = f'Moved to {self.at} successfully.'
            self.note(f'robot arrived at {self.at}')
        self.target = None

    def _reply(self, name, text, group=None):
        self.note(f'{name} to robot{" in the " + group + " group" if group else ""}: {text}')
        self.incoming(name, text, group=group)

    def _knowledge(self, name, text):
        """Every fact the person has that the message asks about (up to three), as one reply."""
        found = list(dict.fromkeys(ans for keys, ans in self.people[name]['knows'] if _mentions(text, keys)))
        return ' '.join(found[:3]) or None

    def _replies(self):
        inbox, self.inbox = self.inbox, []
        for name, group, text, is_ask in inbox:
            if group:
                answered = 0
                for n in self.spec['group_order']:
                    p = self.people[n]
                    ans = None if p.get('away') else self._knowledge(n, text)
                    if ans and answered < 2 and (is_ask or '?' in text):
                        self._reply(n, ans, group=group)
                        answered += 1
                continue
            p = self.people[name]
            done = [i for i in self.items if self.goal(i) and self.goal(i)['to'] == name and self.items[i]['holder'] == name
                    and self.ready_for(i, name)]
            if done and name not in self.confirmed:      # the requester has what they asked for
                self.confirmed.add(name)
                self._reply(name, f"Got the {self.items[done[0]]['name']}, thanks! Everything is fine, nothing else needed.")
                continue
            if p.get('away'):
                if name not in self.away_told:
                    self.away_told.add(name)
                    self._reply(name, p['away'])
                continue
            if (is_ask or '?' in text) and name in self.scanned and _mentions(text, ['locker', 'scan', 'scanned', 'put', 'placed']):
                self._reply(name, f'Yes, I {self.scanned[name]}.')
                continue
            if is_ask or '?' in text:
                ans = self._knowledge(name, text)
                if not ans:
                    held = [self.items[i]['name'] for i in self.item_mentioned(text) if self.items[i]['holder'] == name]
                    ans = f'I have the {held[0]} here.' if held else "Sorry, I don't know."
                self._reply(name, ans)
                continue
            missing = [i for i in self.item_mentioned(text) if self.goal(i) and self.items[i]['holder'] != name
                       and name not in (self.goal(i)['to'], self.goal(i).get('signed_by'))]
            if p.get('prints') and _mentions(text, ['print', 'printout', 'slides']) and not self.files.get(name):
                self._reply(name, "I haven't received any file to print yet. Please forward it to me on WeChat.")
            elif missing and name not in self.complained:
                self.complained.add(name)
                hint = self._knowledge(name, self.items[missing[0]]['aliases'][0]) or ''
                self._reply(name, f"I don't have the {self.items[missing[0]]['name']}. {hint}".strip())

    def _scans(self, final=False):
        here = [n for n, p in self.people.items() if p['marker'] == self.at and not p.get('away') and n in self.qr]
        for n in here:
            desc = self.qr[n]
            said = ' '.join([desc] + self.told[n])
            puts = [i for i, it in self.items.items() if it['holder'] == n and
                    (it.get('made_for_robot') or i in self.item_mentioned(said))]
            signs = [i for i in self.locker if i in self.people[n].get('signs', []) and not self.items[i]['signed_by']]
            takes = [i for i in self.locker if self.ready_for(i, n)]
            if not (puts or signs or takes):
                if n not in self.qr_complained and not final:
                    self.qr_complained.add(n)
                    self._reply(n, f'I got your QR code for "{desc}", but there is nothing for me to put in or take out.')
                continue
            del self.qr[n]
            self.qr_used.add(n)
            done = []
            for i in puts:
                self.items[i]['holder'] = 'locker'; self.locker.append(i)
                done.append(f'put the {self.items[i]["name"]} into the locker')
            for i in signs:
                self.items[i]['signed_by'] = n
                done.append(f'took out the {self.items[i]["name"]}, signed it and put it back')
            for i in [i for i in self.locker if self.ready_for(i, n)]:
                self.items[i]['holder'] = n; self.locker.remove(i)
                done.append(f'took the {self.items[i]["name"]} out of the locker')
            self.note(f'{n} scanned the QR code at the robot and ' + ', then '.join(done) + '.')
            self.scanned[n] = ', then '.join(done)
            self._door_event()

    def _door_event(self):
        """LockApi.py:64-85 (commented out upstream): when the door closes, the watcher started by the
        last Send QR code writes who did what, using the arguments of that action."""
        gv = self.g['global_var']
        if self.watch is None:
            return
        person_name, item = self.watch
        if 'A->S' in self.adapter.cut:
            gv.locker_info += f'At {self.hm()}, the locker door was opened and closed.\n'
        else:
            gv.locker_info += str(f"At {self.hm()}, {person_name} have scanned the QR code and complete the operation of "
                                  f"{item}; {person_name} has done what you asked {person_name} to do in {person_name}'s location.\n")
        gv.locker_flag = False
        self.watch = None

    # ---- result ------------------------------------------------------------------------------------
    def result(self, end):
        outcome = []
        ok = True
        for g in self.task['goal']:
            it = self.items.get(g['item'])
            where = 'does not exist (never printed)' if it is None else (
                'is still in the locker' if it['holder'] == 'locker' else f'is with {it["holder"]}')
            met = bool(it and it['holder'] == g['to'] and (not g.get('signed_by') or it['signed_by'] == g['signed_by']))
            ok &= met
            extra = '' if not g.get('signed_by') or it is None else (
                f', signed by {it["signed_by"]}' if it['signed_by'] else ', not signed')
            outcome.append(f'the {(it or {}).get("name", g["item"])} {where}{extra} (requested for {g["to"]})')
        unused = len([n for n in self.qr_sent if n not in self.qr_used])
        end_text = {'stopped': f'The robot chose Stop after {self.steps} steps.',
                    'step limit': f'The robot had not stopped after {self.steps} steps (limit).'}.get(end, f'The run ended: {end}.')
        output = '\n'.join(self._transcript() + ['', 'Outcome: ' + end_text + ' ' + '; '.join(outcome) + '.'])
        return {
            'output': output,
            'end': end,
            'trace': self.trace,
            'graph_update_discarded': self.graph_update,
            'metrics': {
                'task_success': int(ok),
                'stopped': int(end == 'stopped'),
                'steps': self.steps,
                'messages_sent': self.counts['messages'],
                'qr_codes_sent': self.counts['qr'],
                'qr_codes_unused': unused,
                'moves': self.counts['moves'],
                'undelivered': self.counts['undelivered'],
            },
        }

    def _transcript(self):
        lines, by_step = [], {r['step']: r for r in self.trace}
        for line in self.log:
            if line.startswith('Step '):
                k = int(line.split()[1])
                r = by_step.get(k, {})
                act = re.sub(r'Successful forwarding of electronic files from .*$', '', r.get('action') or '').strip()   # main.py:257
                lines.append(f'{line}: ' + (act if act else '(no action parsed)'))
                lines += [f'  - {e}' for e in r.get('effects', [])]
            else:
                lines.append(line)
        return lines


class _SyncThread:
    """threading.Thread for main.py: runs the target when started, so the locker watcher is set
    before the next iteration."""
    def __init__(self, target=None, args=(), kwargs=None, **_):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)

    def join(self, timeout=None):
        pass


class _WechatMessage:   # common/wechat.py:21-48
    def __init__(self, FromUserName=None, ToUserName=None, MsgType=None, Content=None, ActionUserName=None,
                 PushContent=None, ActionNickName=None):
        self.FromUserName, self.ToUserName, self.MsgType, self.Content = FromUserName, ToUserName, MsgType, Content
        self.ActionUserName, self.PushContent, self.ActionNickName = ActionUserName, PushContent, ActionNickName


class Adapter(BaseAdapter):
    channels = {
        'M->S': 'persistent relational graph (priori_knowledge) in the perception prompt',
        'M->A': 'persistent relational graph (priori_knowledge) in the planning and action prompts',
        'A->S': "robot's own messages in the perception prompt; Send QR code arguments labelling the locker event",
    }
    steps = {}   # no mechanism revision; reflection's judgment is discarded by main.py (reflect_flag)

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        if getattr(llm, 'cache', None) is not None and not Path(llm.cache).is_absolute():
            llm.cache = Path(llm.cache).resolve()            # run() changes the working directory
        self.spec = json.loads((CASE / 'inputs' / 'office.json').read_text())
        self.cut, self.tag, self.world = set(), '', None
        sys.path.insert(0, str(CORE))
        self._install_stubs()
        pt = importlib.import_module('OfficeAssistant.prompt_test')
        self._orig = {n: getattr(pt, n) for n in ('get_perception_prompt', 'get_planning_prompt', 'get_action_prompt')}
        pt.get_perception_prompt = self._perception_prompt   # main.py imports these at lines 21 and 164
        pt.get_planning_prompt = self._planning_prompt
        pt.get_action_prompt = self._action_prompt

    # ---- cut sites ---------------------------------------------------------------------------------
    def _perception_prompt(self, instruction='', flag=False, robot_status='', time_str='', locker_infomation='',
                           user_chat_history='', group_chat_history='', priori_knowledge=''):
        self.world.n_perception += 1
        if 'M->S' in self.cut:
            priori_knowledge = ''
        if 'A->S' in self.cut:
            user_chat_history, group_chat_history = _strip_self(user_chat_history), _strip_self(group_chat_history)
        return self._orig['get_perception_prompt'](instruction, flag, robot_status, time_str, locker_infomation,
                                                   user_chat_history, group_chat_history, priori_knowledge)

    def _planning_prompt(self, instruction='', thought_history=[], action_history=[], last_summary='', last_action='',
                         error_flag=None, priori_knowledge='', user_chat_history='', time_str='', group_chat_history='',
                         reflect_history='', perception=''):
        if 'M->A' in self.cut:
            priori_knowledge = ''
        return self._orig['get_planning_prompt'](instruction, thought_history, action_history, last_summary, last_action,
                                                 error_flag, priori_knowledge, user_chat_history, time_str,
                                                 group_chat_history, reflect_history, perception)

    def _action_prompt(self, instruction='', summary_history=[], action_history=[], last_summary='', last_action='',
                       error_flag=None, priori_knowledge='', user_chat_history='', time_str='', group_chat_history='',
                       reflect_history='', perception='', refined_instruction='', active='', locker='', robot='',
                       output_planning=''):
        if 'M->A' in self.cut:
            priori_knowledge = ''
        return self._orig['get_action_prompt'](instruction, summary_history, action_history, last_summary, last_action,
                                               error_flag, priori_knowledge, user_chat_history, time_str,
                                               group_chat_history, reflect_history, perception, refined_instruction,
                                               active, locker, robot, output_planning)

    # ---- model client -> HALO backbone ----------------------------------------------------------------
    def _inference_chat(self, chat, model=None, api_url=None, token=None):
        """OfficeAssistant/api.py:10-41 posts the chat to GPT-4o; here it goes to the backbone."""
        system = '\n\n'.join(str(c) for r, c in chat if r == 'system')
        user = '\n\n'.join(str(c) for r, c in chat if r != 'system')
        if system.startswith('You are a helpful AI assistant. You are proficient at Fetch-and-Deliver'):
            stage = 'action'
        elif system.startswith('You are a helpful AI assistant. Your role is to synthesize'):
            stage = 'stop_planning' if self.world.stopped else 'planning'
        elif user.startswith('### Robot basic information'):
            return REFLECTION_REPLY          # main.py:405-416: printed only, never parsed
        else:
            stage = 'perception'
        reply = self.llm(system, user, tag=f'{self.tag}|step{self.world.steps}|{stage}')
        self.world.on_reply(stage, reply)
        return reply

    def _install_stubs(self):
        ad = self

        def mod(name, **attrs):
            m = types.ModuleType(name)
            m.__dict__.update(attrs)
            sys.modules[name] = m
            return m

        class WechatServer:   # common/wechat.py:87
            def __init__(self, wx_id, func_on_msgs, func_on_event, url=None):
                self.current_wx_id, self.func_on_msgs, self.func_on_event, self.wx_name = wx_id, func_on_msgs, func_on_event, 'AssistantX'
                ad.world.attach(self)

            def Say(self, to, text):
                ad.world.say(to, text)

            def SayImage(self, to, img):
                ad.world.say_image(to, img)

        importlib.import_module('common')            # namespace package core/common (global_var.py)
        mod('common.wechat', WechatServer=WechatServer, WechatMessage=_WechatMessage, onevent=lambda s, e: None)
        mod('common.andro_operation', Forward_file_on_Wechat=lambda a, b: ad.world.forward(a, b),
            juge_open_wechat=lambda contact: None)
        mod('common.robot_api')
        mod('common.LockApi')
        mod('handing', ocSelect=lambda person_name, item='': ad.world.ocSelect(person_name, item),
            img_encode=lambda path='encrypted_qrcode.png', itme_name='': ad.world.img_encode(path, itme_name))
        mod('socket_server_dabai', send_dabai_command=lambda cmd, arg=None: ad.world.send_dabai_command(cmd, arg))
        for name in ('socket_server_armcar', 'handle_dabai', 'handle_armcar'):
            mod(name)
        mod('MobileAgent', __path__=[])
        mod('MobileAgent.api', encode_image=lambda path: '')
        importlib.import_module('OfficeAssistant')   # namespace package core/OfficeAssistant
        mod('OfficeAssistant.api', inference_chat=self._inference_chat)
        mod('OfficeAssistant.prompt_assx', to_witch_robot=lambda text: f'{ROBOT} {text}')
        noop = lambda *a, **k: None
        mod('OfficeAssistant.controller', **{n: noop for n in (
            'get_screenshot', 'tap', 'slide', 'type', 'back', 'home', 'tap_hold', 'talk_to_fitbot1', 'talk_to_someone',
            'search_food', 'open_meituan', 'find_specific_food', 'open_xiecheng', 'open_didi', 'skipp_wechat_interface')})

    def _fresh_state(self):
        """A new common.global_var per run, with the simulated office's contacts."""
        sys.modules.pop('common.global_var', None)
        gv = importlib.import_module('common.global_var')
        contacts = Contacts()
        for n, p in self.spec['people'].items():
            for a in p['aliases']:
                contacts[a] = p['wxid']
        gv.chat_name = contacts
        gv.room_name = Contacts(ROOMS)
        gv.user_history = Book({n: '' for n in contacts})       # global_var.py:36-38
        gv.group_history = Book({g: '' for g in ROOMS})
        sys.modules['handing'].global_var = gv                 # main.py uses global_var.locker_info / locker_flag
        return gv

    # ---- items and runs ------------------------------------------------------------------------------
    def items(self):
        out = []
        for t in self.spec['tasks']:
            ctx = (f'An office assistant robot (a mobile base with a QR-locked locker that people open with a QR code '
                   f'it sends them on WeChat; it can message people, ask the "Office Work" group, forward files and '
                   f'drive to people or rooms). At {t["time"][-5:]} {t["from"]} sends it this request: "{t["instruction"]}"'
                   + (f' together with the file {t["file"]}.' if t.get('file') else '')
                   + '\nWhat is true in the office:\n' + self.spec['graph'])
            out.append({'id': t['id'], 'judge_context': ctx})
        return out

    def run(self, item, cut, sample):
        task = next(t for t in self.spec['tasks'] if t['id'] == item['id'])
        self.cut = set(cut)
        self.tag = f'{task["id"]}|s{sample}'      # names item, sample and (in _inference_chat) step and stage, not the arm
        self.world = Office(self.spec, task, self)
        self._fresh_state()
        tmp = Path(tempfile.mkdtemp(prefix='halo-assistantx-'))
        (tmp / 'prompt_txt').mkdir()
        (tmp / 'prompt_txt' / 'priori_knowledge.txt').write_text(self.spec['graph'], encoding='utf-8')
        (tmp / 'Result' / 'gpt4o').mkdir(parents=True)        # main.py:372 writes the run record here
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            runpy.run_path(str(MAIN), run_name='__main__')
            end = 'main.py returned'
        except EpisodeEnd as e:
            end = str(e)
        except Exception as e:
            tb = traceback.extract_tb(e.__traceback__)
            if not tb or not tb[-1].filename.startswith(str(CORE)):
                raise                                          # an adapter error, not an upstream crash
            traceback.print_exc()
            end = f'upstream crash at {Path(tb[-1].filename).name}:{tb[-1].lineno}: {type(e).__name__}: {e}'
        finally:
            os.chdir(cwd)
            shutil.rmtree(tmp, ignore_errors=True)
        return self.world.result(end)
