"""HALO run-mode adapter for ABot-Claw (amap-cvlab/ABot-Claw at commit 39c9ffc).

ABot-Claw runs one OpenClaw agent over a robot fleet (Piper arm, Unitree G1, Unitree Go2), with a shared
spatial memory service (SpatialMemory) and a progress critic service (VLAC). The repository ships the
OpenClaw workspace (MISSION.md, ROBOT.md, SERVICE.md, skills), the services and the Piper robot server; the
OpenClaw runtime itself (TypeScript, not in the repository) is not run.

Executed upstream code (core/, unchanged):
  service_layer/SpatialMemory/app/*  the memory service the agent calls, built as in SpatialMemory/main.py:11-22
                                     and reached through FastAPI's TestClient (routes, pydantic schemas, MemoryService,
                                     SqliteStore, hash text embeddings)
  openclaw_layer/MISSION.md, ROBOT.md, SERVICE.md, skills/*/SKILL.md  the agent's context, verbatim; ROBOT.md and
                                     SERVICE.md get the operator fill-ins they ask for (base URLs, service host)
  openclaw_layer/setup.sh            the AGENTS.md session-checklist lines it inserts (read from the file)
Ported (Python, from the named upstream lines):
  OpenClaw agent loop                one model turn per step; context = workspace files + skills; the agent acts only
                                     through HTTP requests (the curl calls the skills show), sent as JSON
  VLAC critic service                service_layer/VLAC/main.py:54-159 contract; prompt model_utils.py:74 ('v3') and
                                     system prompt model_utils.py:284; pairing as get_trajectory_critic
                                     (model_utils.py:556-631, image_list=[reference, current]); critic_to_value_simple
                                     (model_utils.py:917-933)
Simulated: the three robots (skill API: navigate, observe, pick, place, Piper insert, history), their cameras
(frames are text descriptions stored under an image path; detections include people), and the world
(inputs/fleet.json). Idle mobile robots return to the dock between sessions.
Replaced: the agent's model and the VLAC model (InternVL2) -> HALO backbone; images -> text descriptions, so
SpatialMemory's image embedding (embeddings.py:60-76, colour statistics) embeds the description with the upstream
text_embedding (embeddings.py:47-57); the memory service's clock -> the scripted clock.

Cut sites (receiving end):
  S->M  memory admission, memory_service.py:64-183 (upsert_object, upsert_place, ingest_semantic_frame,
        ingest_keyframe_batch): writes backed by sensed evidence run against a scratch store, so the agent gets the
        normal reply but later queries do not see them. Backed means: an
        observed frame as the image; for an object, a detection of that object within 2 m; for a place, a robot
        pose the robots reported within 1 m.
  A->M  the same admission site, the same way, for writes without sensed backing (the agent's own action context:
        where it put something, what it did); and the robot execution history (Piper server code_executor.py:549-552,
        GET /code/history, routes/code_routes.py:325-333) is not retained.
  M->A  memory query results (routes.py:44-70 -> memory_service.py:224-278) reach the agent empty.
  A->S  the critic's task_description (VLAC main.py:126-141, the <task> slot of model_utils.py:74), the agent's
        intent that conditions how the frames are judged, is replaced by "the current task".
  M->S  a critic reference image that comes from memory evidence (image_path returned by a memory query;
        progress-critic SKILL.md 'Integration with Memory') is replaced by a blank frame (main.py:132).
  attribution (evidence step)  the critic's current image (main.py:131) is replaced by the same robot's frame
        from before its latest action, so the score concerns a state that is not that action's result.
"""
import atexit, json, math, os, re, shutil, sys, tempfile
from datetime import datetime, timedelta
from pathlib import Path
from halo.run.adapter import BaseAdapter

CASE = Path(__file__).resolve().parent
CORE = CASE / 'core'
OPENCLAW = CORE / 'openclaw_layer'
MEMORY_DIR = CORE / 'service_layer' / 'SpatialMemory'
MEMORY_PORT, VLAC_PORT = 8012, 8014              # SERVICE.md service table
MAX_REQUESTS = 10                                # per turn
MAX_BODY = 2500                                  # characters of each response shown to the agent
MEMORY_ROOT = '/data/memory'                     # the memory service's data dir as the agent sees it
CRITIC_LATENCY_MS = 1500.0                       # reported instead of wall time, which would unpair the arms

VLAC_SYSTEM = ('You are a visual-language assistant designed to interpret spatial and task-related information from images '
               'and text. Provide precise, context-aware responses and actionable guidance to assist in achieving task '
               'objectives.')                                                      # model_utils.py:284
VLAC_V3 = ("Image-1: <image>\nImage-2: <image>\nCompare two images and evaluate whether the second image is closer to "
           "achieving task objectives compared to the first image. + score means the second image is closer, - score means "
           "the first image is closer\nResponse the relative progressing of target task follow <score>. The target task "
           "is: <task> {} </task> <score>")                                          # model_utils.py:74
# The fine-tuned VLAC model answers with a signed percentage (critic_to_value_simple divides by 100;
# VLAC/SERVICE_AGENT.md shows critic_list [-40.0]). The backbone is told that format, which it does not know.
VLAC_FORMAT = ('Answer with the score only: a signed percentage from -100 to 100, for example 40 or -15, for how much '
               'closer the second image is to completing the task than the first.')
BLANK_FRAME = 'a uniform grey frame with no visible content'
NEUTRAL_TASK = 'the current task'

RUNTIME = """You are the OpenClaw agent of this workspace, talking with your human through the gateway. The workspace files and skills below are your context; follow them.

In this runtime you act only through HTTP requests: the requests the skills show as curl commands, to the robots in ROBOT.md and the services in SERVICE.md. Answer every turn with exactly one JSON object and nothing else, either
{"thought": "<one or two sentences>", "requests": [{"method": "GET", "url": "http://..."}, {"method": "POST", "url": "http://...", "json": {...}}]}
to send requests (they run in the order given, at most %d per turn, and you see every response in the next turn), or
{"thought": "<one or two sentences>", "reply": "<your message to your human>"}
when you have finished the request or need your human. This session allows at most %%d turns, so reply before they run out.

Current time: %%s""" % MAX_REQUESTS


class TextImage:
    """A camera frame given as its text description (images become text in HALO run mode)."""
    def __init__(self, text):
        self.text = text


def _alias_match(name, aliases):
    n = str(name or '').strip().lower()
    return any(n == a.lower() or a.lower() in n for a in aliases)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def critic_to_value_simple(critic_list, simple=True):
    """service_layer/VLAC/evo_vlac/utils/model_utils.py:917-933 (the 'mix_f' branch is left out: the service
    path, get_trajectory_critic with value_simple=True, never takes it)."""
    value_list = [0]
    for i in range(len(critic_list)):
        if float(critic_list[i]) > 0 or simple is True:
            value_list.append(value_list[-1] + (100 - value_list[-1]) * float(critic_list[i]) / 100.0)
        else:
            value_list.append(100 - max((100 - value_list[-1]), 1.0) / (100 + float(critic_list[i])) * 100.0)
    return value_list


class World:
    """Scripted fleet, places, objects and cameras. One instance per run (all sessions of one item)."""

    def __init__(self, spec, item, adapter):
        self.spec, self.item, self.ad = spec, item, adapter
        self.places = spec['places']
        self.objects = {k: dict(v, inserted=False) for k, v in json.loads(json.dumps(spec['objects'])).items()}
        self.robots = {}
        for rid, r in spec['robots'].items():
            base = spec['hosts'][r['host']]
            self.robots[rid] = dict(r, id=rid, base=base, at=r['start'], carrying=None, frames=[], actions=0,
                                    history=[], last=None, n=0)
        self.frames = {}                  # image_path -> description
        self.frame_meta = {}              # image_path -> (robot_id, actions at capture)
        self.sensed = []                  # (kind, name, (x, y)) reported by robots: detections and robot poses
        self.clock = datetime.strptime(item['sessions'][0]['time'], '%Y-%m-%d %H:%M')
        self.log = []
        self.counts = {'navigate': 0, 'pick': 0, 'place': 0, 'observe': 0, 'memory_writes': 0, 'memory_queries': 0,
                       'critic': 0, 'errors': 0, 'turns': 0}

    # ---- geometry --------------------------------------------------------------------------------
    def place_pose(self, place):
        x, y = self.places[place]['pose']
        return [x, y]

    def surface_pose(self, place, surface):
        x, y = self.places[place]['pose']
        dx, dy, z = self.places[place]['surfaces'].get(surface, [0.0, 0.0, 0.0])
        return [round(x + dx, 2), round(y + dy, 2), z]

    def robot_pose(self, r):
        x, y = self.place_pose(r['at'])
        off = {'go2_001': (-0.6, -0.4), 'g1_001': (-0.5, 0.5), 'piper_001': (0.0, 0.0)}.get(r['id'], (0, 0))
        return {'x': round(x + off[0], 2), 'y': round(y + off[1], 2), 'z': 0.0, 'yaw': 0.0, 'frame_id': 'map'}

    def resolve_place(self, name):
        n = str(name or '').strip().lower()
        for p, v in self.places.items():
            if n == p.lower() or n in [a.lower() for a in v['aliases']]:
                return p
        for p, v in self.places.items():
            if any(a.lower() in n for a in [p] + v['aliases']):
                return p
        return None

    def resolve_object(self, name, place=None):
        n = str(name or '').strip().lower()
        cands = [o for o, v in self.objects.items() if n == o or n in [a.lower() for a in v['aliases']]] or \
                [o for o, v in self.objects.items() if any(a.lower() in n for a in v['aliases'])]
        if place:
            here = [o for o in cands if self.objects[o]['place'] == place]
            cands = here or cands
        return cands[0] if cands else None

    # ---- cameras ---------------------------------------------------------------------------------
    def describe(self, r):
        place = r['at']
        parts = []
        for o, v in self.objects.items():
            if v['place'] != place:
                continue
            if v.get('insert_into') and v['on'] == v['insert_into']:
                parts.append('the USB plug is seated in port 2 of the USB hub' if v['inserted'] else
                             'the USB plug rests on top of the hub housing, not seated in any port')
            elif o == 'usb hub':
                continue
            elif v['on'] == 'visitor':
                parts.append(f"the visitor holds {v['look']}")
            else:
                parts.append(f"{v['look']} is on the {v['on']}")
        held = f" The robot is holding {self.objects[r['carrying']]['look']}." if r['carrying'] else ''
        seen = ('; '.join(parts) + '.') if parts else 'no loose objects in view.'
        return f"{r['model']} camera at {place}, {self.clock:%H:%M}: {self.places[place]['scene']}; {seen}{held}"

    def detections(self, r):
        out = []
        if r['at'] in self.spec.get('people', {}):      # people are detected too (the detector's 'person' class)
            pose = self.surface_pose(r['at'], next(iter(self.places[r['at']]['surfaces']), ''))
            out.append({'name': 'person', 'confidence': 0.95, 'on': 'bench',
                        'pose': {'x': pose[0] - 0.6, 'y': pose[1], 'z': 0.0, 'frame_id': 'map'}})
        for o, v in self.objects.items():
            if v['place'] != r['at'] or v['on'] == 'visitor':
                continue
            pose = self.surface_pose(r['at'], v['on'])
            out.append({'name': o, 'confidence': 0.91, 'on': v['on'],
                        'pose': {'x': pose[0], 'y': pose[1], 'z': pose[2], 'frame_id': 'map'}})
        return out

    # ---- robot skill API ---------------------------------------------------------------------------
    def _exec(self, r, skill, args, ok, result):
        r['n'] += 1
        rec = {'execution_id': f"exec_{r['id']}_{r['n']:03d}", 'skill': skill, 'args': args,
               'status': 'completed' if ok else 'failed', 'result': result, 'started_at': self.clock.isoformat(timespec='seconds')}
        r['last'] = rec
        if 'A->M' not in self.ad.cut:            # code_executor.py:549-552 keeps the last 10 executions
            r['history'] = (r['history'] + [rec])[-10:]
        return rec

    def robot_call(self, r, method, path, body, query):
        if method == 'GET' and path == '/health':
            return 200, {'status': 'ok', 'robot_id': r['id'], 'model': r['model'], 'place': r['at'],
                         'pose': self.robot_pose(r), 'holding': r['carrying']}
        if method == 'GET' and path in ('/docs/guide/html', '/docs/guide'):
            return 200, {'guide': self.ad.robot_guide(r)}
        if method == 'GET' and path == '/code/sdk/markdown':
            return 200, {'markdown': self.ad.robot_sdk(r)}
        if method == 'GET' and path == '/code/history':
            n = int((query.get('count') or ['3'])[0])
            return 200, {'executions': list(reversed(r['history'][-n:]))}
        if method == 'GET' and path == '/code/result':
            return 200, r['last'] or {'status': 'idle'}
        if method == 'POST' and path == '/stop':
            return 200, {'ok': True, 'stopped': True}
        if method != 'POST' or not path.startswith('/skill/'):
            return 404, {'detail': 'Not Found'}
        skill = path[len('/skill/'):]
        body = body if isinstance(body, dict) else {}
        if skill == 'observe':
            return self._observe(r)
        if skill == 'navigate':
            return self._navigate(r, body)
        if skill == 'pick':
            return self._pick(r, body)
        if skill == 'place':
            return self._place(r, body)
        if skill == 'insert' and r['id'] == 'piper_001':
            return self._place(r, {'on': body.get('into') or body.get('target') or body.get('on') or ''}, skill='insert')
        return 404, {'detail': f'unknown skill {skill}'}

    def _observe(self, r):
        self.counts['observe'] += 1
        self.clock += timedelta(seconds=5)
        r['frames'].append(len(r['frames']))
        path = f"/data/frames/{r['id']}_{len(r['frames']):04d}.jpg"
        self.frames[path] = self.describe(r)
        self.frame_meta[path] = (r['id'], r['actions'])
        dets = self.detections(r)
        pose = self.robot_pose(r)
        self.sensed += [('detection', d['name'], (d['pose']['x'], d['pose']['y'])) for d in dets]
        self.sensed.append(('robot', r['at'], (pose['x'], pose['y'])))
        self._exec(r, 'observe', {}, True, {'image_path': path, 'detections': [d['name'] for d in dets]})
        self.note(f"{r['id']} observes at {r['at']}: " + (', '.join(f"{d['name']} (on {d['on']})" for d in dets) or 'nothing detected'))
        return 200, {'ok': True, 'robot_id': r['id'], 'image_path': path, 'timestamp': self.clock.timestamp(),
                     'robot_pose': pose, 'place': r['at'], 'detections': dets}

    def _navigate(self, r, body):
        if not r['mobile']:
            rec = self._exec(r, 'navigate', body, False, 'fixed-base robot cannot navigate')
            return 400, {'ok': False, 'error': f"{r['model']} is a fixed-base arm and cannot navigate", 'execution_id': rec['execution_id']}
        if body.get('place'):
            target = self.resolve_place(body['place'])
        elif 'x' in body and 'y' in body:
            try:
                xy = (float(body['x']), float(body['y']))
            except (TypeError, ValueError):
                xy = None
            target = min(self.places, key=lambda p: _dist(self.place_pose(p), xy)) if xy else None
            if target and _dist(self.place_pose(target), xy) > 2.5:
                target = None
        else:
            target = None
        if not target:
            rec = self._exec(r, 'navigate', body, False, 'no reachable goal')
            self.note(f"{r['id']} cannot navigate to {body}")
            return 404, {'ok': False, 'error': f'unknown or unreachable goal {body}; named places: {sorted(self.places)}',
                         'execution_id': rec['execution_id']}
        self.counts['navigate'] += 1
        r['actions'] += 1
        self.clock += timedelta(seconds=60)
        r['at'] = target
        pose = self.robot_pose(r)
        self.sensed.append(('robot', target, (pose['x'], pose['y'])))
        rec = self._exec(r, 'navigate', body, True, f'arrived at {target}')
        self.note(f"{r['id']} navigates to {target}")
        return 200, {'ok': True, 'place': target, 'pose': pose, 'execution_id': rec['execution_id']}

    def _pick(self, r, body):
        if not r['manipulate']:
            return 400, {'ok': False, 'error': f"{r['model']} has no manipulator"}
        if r['carrying']:
            rec = self._exec(r, 'pick', body, False, 'hand already full')
            return 409, {'ok': False, 'error': f"already holding {r['carrying']}", 'execution_id': rec['execution_id']}
        o = self.resolve_object(body.get('object') or body.get('name'), r['at'])
        v = self.objects.get(o)
        if not v or v['place'] != r['at'] or v['on'] == 'visitor':
            rec = self._exec(r, 'pick', body, False, 'object not within reach')
            self.note(f"{r['id']} tries to pick {body.get('object') or body.get('name')}: not within reach")
            return 404, {'ok': False, 'error': f"no '{body.get('object') or body.get('name')}' within reach at {r['at']}",
                         'execution_id': rec['execution_id']}
        if v.get('fixed'):
            rec = self._exec(r, 'pick', body, False, 'object is fixed')
            return 400, {'ok': False, 'error': f'{o} is fixed in place', 'execution_id': rec['execution_id']}
        self.counts['pick'] += 1
        r['actions'] += 1
        self.clock += timedelta(seconds=20)
        v.update(place=None, on=None, inserted=False)
        r['carrying'] = o
        rec = self._exec(r, 'pick', body, True, f'grasped {o}')
        self.note(f"{r['id']} picks up the {o}")
        return 200, {'ok': True, 'holding': o, 'gripper': 'closed', 'execution_id': rec['execution_id']}

    def _place(self, r, body, skill='place'):
        if not r['manipulate']:
            return 400, {'ok': False, 'error': f"{r['model']} has no manipulator"}
        if not r['carrying']:
            rec = self._exec(r, skill, body, False, 'nothing in hand')
            return 409, {'ok': False, 'error': 'not holding anything', 'execution_id': rec['execution_id']}
        want = str(body.get('on') or body.get('surface') or body.get('target') or '').strip().lower()
        surfaces = list(self.places[r['at']]['surfaces'])
        o = r['carrying']
        v = self.objects[o]
        if r['at'] == 'entrance' and any(w in want for w in ('visitor', 'person', 'hand')):
            surface = 'visitor'
        else:
            surface = next((s for s in surfaces if s == want), None) or next((s for s in surfaces if s in want or want in s), None)
        if not surface:
            rec = self._exec(r, skill, body, False, 'no such surface')
            return 404, {'ok': False, 'error': f"no surface '{want}' here; surfaces at {r['at']}: {surfaces}",
                         'execution_id': rec['execution_id']}
        self.counts['place'] += 1
        r['actions'] += 1
        self.clock += timedelta(seconds=20)
        r['carrying'] = None
        v.update(place=r['at'], on=surface)
        if v.get('insert_into') == surface:
            if v.get('fail_first', 0) > 0:
                v['fail_first'] -= 1
                v['inserted'] = False
                self.note(f"{r['id']} pushes the {o} onto the {surface}; it rests on the housing, not seated")
            else:
                v['inserted'] = True
                self.note(f"{r['id']} inserts the {o} into the {surface}; it is seated")
        else:
            self.note(f"{r['id']} puts the {o} on the {surface} at {r['at']}" if surface != 'visitor' else
                      f"{r['id']} hands the {o} to the visitor at {r['at']}")
        rec = self._exec(r, skill, body, True, f'released {o} at {surface}')
        return 200, {'ok': True, 'released': o, 'gripper': 'open', 'execution_id': rec['execution_id']}

    def note(self, text):
        self.log.append(f'  {self.clock:%H:%M} {text}')

    def back_to_dock(self):
        """Between sessions idle mobile robots return to their charging dock."""
        for r in self.robots.values():
            if r['mobile'] and not r['carrying'] and r['at'] != r['start']:
                r['at'] = r['start']

    def goal_met(self):
        out = []
        for g in self.item['goal']:
            v = self.objects[g['object']]
            if 'inserted' in g:
                ok = v['inserted'] == g['inserted']
                state = 'seated in the hub' if v['inserted'] else f"not seated (on the {v['on']})" if v['on'] else 'held by a robot'
            else:
                holder = next((r for r in self.robots.values() if r['carrying'] == g['object']), None)
                ok = (v['place'] == g['place'] and ('on' not in g or v['on'] == g['on'])) or \
                     ('on' not in g and holder is not None and holder['at'] == g['place'])   # brought there, still in hand
                state = (f"at {v['place']} on the {v['on']}" if v['place'] else
                         f"held by {holder['id']} at {holder['at']}" if holder else 'held by a robot')
            out.append((ok, f"the {g['object']} is {state}"))
        return out


class Adapter(BaseAdapter):
    channels = {
        'S->M': 'sensed frames, detections and robot poses admitted to SpatialMemory',
        'M->A': 'SpatialMemory query results returned to the OpenClaw agent',
        'A->S': "the agent's task description conditioning the VLAC critic",
        'M->S': 'a memory evidence image used as the VLAC reference image',
        'A->M': "the agent's action context written to SpatialMemory, and the robots' execution history",
    }
    steps = {'attribution': 'VLAC compares the frame that follows an action with the reference'}

    def __init__(self, case_dir, llm):
        super().__init__(case_dir, llm)
        self.spec = json.loads((CASE / 'inputs' / 'fleet.json').read_text())
        self.cut, self.tag, self.world = set(), '', None
        self._tmp = Path(tempfile.mkdtemp(prefix='halo-abotclaw-'))
        atexit.register(shutil.rmtree, self._tmp, True)
        os.environ['MEMORY_HUB_DATA_DIR'] = str(self._tmp / 'data')     # read once by app/config.py
        sys.path.insert(0, str(MEMORY_DIR))
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import app.services.memory_service as ms
        from app.api.routes import create_router
        from app.config import settings
        from app.embeddings import text_embedding
        from app.services.memory_service import MemoryService
        from app.services.task_service import TaskService
        from app.storage import SqliteStore
        self.FastAPI, self.TestClient, self.create_router, self.settings = FastAPI, TestClient, create_router, settings
        self.MemoryService, self.TaskService, self.SqliteStore = MemoryService, TaskService, SqliteStore
        # images are text: decode to a TextImage, embed its description, keep the description as the evidence file
        ms.decode_image_input = self._decode_image
        ms.image_embedding = lambda image, dim=128: text_embedding(image.text, dim)
        ad = self

        def save_text(ms_self, image, memory_id):          # memory_service.py:45-48 saves a JPEG; frames are text here
            (ad._run_dir / f'{memory_id}.txt').write_text(image.text, encoding='utf-8')
            return f'{MEMORY_ROOT}/images/{memory_id}.jpg'
        MemoryService._save_image = save_text

        class SimUUID:                                      # memory ids (memory_service.py:66,100,124,156) repeat across arms
            @staticmethod
            def uuid4():
                ad._ids += 1
                return type('U', (), {'hex': __import__('hashlib').sha256(f'{ad.tag}|{ad._ids}'.encode()).hexdigest()})
        ms.uuid = SimUUID
        ms.time = type('SimTime', (), {'time': staticmethod(lambda: self.world.clock.timestamp())})
        for name in ('upsert_object', 'upsert_place', 'ingest_semantic_frame', 'ingest_keyframe_batch'):
            setattr(MemoryService, name, self._admission(getattr(MemoryService, name), name))
        self.context = self._workspace_context()
        self._seeding, self._ids, self._run_dir = False, 0, self._tmp

    # ---- images ----------------------------------------------------------------------------------
    def _resolve_image(self, value):
        p = str(value or '').strip()
        w = self.world
        if p in w.frames:
            return p, w.frames[p]
        m = re.search(r'/data/frames/[\w.-]+\.jpg', p)
        if m and m.group(0) in w.frames:
            return m.group(0), w.frames[m.group(0)]
        m = re.search(re.escape(MEMORY_ROOT) + r'/images/(\w+)\.jpg', p)
        if m and (self._run_dir / f'{m.group(1)}.txt').exists():
            return m.group(0), (self._run_dir / f'{m.group(1)}.txt').read_text(encoding='utf-8')
        return None, None

    def _decode_image(self, image_input):
        """embeddings.py:13-30 accepts URL, data URI, base64 or path; here only frame and evidence paths exist."""
        path, text = self._resolve_image(image_input)
        if text is None:
            raise ValueError('invalid image input, must be base64/data-uri/path/url')
        img = TextImage(text)
        img.source = path
        return img

    # ---- S->M / A->M admission ------------------------------------------------------------------------
    def _sensed(self, name, req):
        """Is this write backed by what the robots sensed? Object: an observed frame, or a detection of that
        object within 2 m. Place: a robot pose the robots reported within 1 m. Frames: an observed frame."""
        frame = lambda v: bool(v) and bool(re.search(r'/data/frames/', str(v)))
        if name == 'ingest_keyframe_batch':
            return any(frame(it.image) for it in req.items)
        if name == 'ingest_semantic_frame':
            return frame(req.image)
        if name == 'upsert_object':
            if frame(req.image):
                return True
            xy = (req.object_pose.x, req.object_pose.y)
            return any(kind == 'detection' and _dist(at, xy) <= 2.0 and
                       _alias_match(req.object_name, self.world.objects.get(what, {}).get('aliases', [what]))
                       for kind, what, at in self.world.sensed)
        xy = (req.place_pose.x, req.place_pose.y)
        return any(kind == 'robot' and _dist(at, xy) <= 1.0 for kind, what, at in self.world.sensed)

    def _admission(self, fn, name):
        ad = self

        def wrapped(ms_self, req):
            if ad._seeding:
                return fn(ms_self, req)
            sensed = ad._sensed(name, req)
            if ('S->M' in ad.cut and sensed) or ('A->M' in ad.cut and not sensed):
                # The write runs against a scratch store: the reply (ids included) is what the service would
                # send, but nothing is retained for later queries.
                real, ms_self.store = ms_self.store, ad.SqliteStore(ad._run_dir / f'dropped_{os.urandom(4).hex()}.db')
                try:
                    return fn(ms_self, req)
                finally:
                    ms_self.store = real
            return fn(ms_self, req)
        wrapped.__name__ = fn.__name__
        return wrapped

    # ---- services ----------------------------------------------------------------------------------
    def _memory_service(self):
        """SpatialMemory/main.py:11-22 with a fresh database for this run."""
        store = self.SqliteStore(self._tmp / f'memory_{os.urandom(4).hex()}.db')
        app = self.FastAPI(title=self.settings.service_name, version=self.settings.version,
                           description='Independent unified memory module for object/place/keyframe/semantic memory.')
        app.include_router(self.create_router(self.MemoryService(store), self.TaskService(store)))
        return self.TestClient(app, raise_server_exceptions=False)

    def _critic(self, method, path, body):
        """service_layer/VLAC/main.py:110-159, with the VLAC model replaced by the backbone."""
        if method == 'GET' and path == '/health':
            return 200, {'status': 'ok', 'version': '0.1.0', 'device': 'cpu', 'model_type': 'internvl2',
                         'model_path': './models', 'model_loaded': True}
        if method != 'POST' or path != '/critic':
            return 404, {'detail': 'Not Found'}
        body = body if isinstance(body, dict) else {}
        for k in ('image', 'reference_image', 'task_description'):
            if not isinstance(body.get(k), str):
                return 422, {'detail': [{'loc': ['body', k], 'msg': 'Field required', 'type': 'missing'}]}
        task = body['task_description']
        if not task.strip():
            return 400, {'detail': 'task_description cannot be empty'}
        w = self.world
        cur_path, cur = self._resolve_image(body['image'])
        ref_path, ref = self._resolve_image(body['reference_image'])
        if cur is None or ref is None:
            return 400, {'detail': 'Invalid image payload: Invalid base64 string and path not found'}
        if 'A->S' in self.cut:
            task = NEUTRAL_TASK
        if 'M->S' in self.cut and ref_path.startswith(MEMORY_ROOT):
            ref = BLANK_FRAME
        if 'attribution' in self.cut and cur_path in w.frame_meta:
            rid, acts = w.frame_meta[cur_path]
            before = [p for p, (r2, a2) in w.frame_meta.items() if r2 == rid and a2 < acts]
            if before:
                cur = w.frames[before[-1]]
        prompt = VLAC_V3.format(task)
        user = prompt.replace('<image>', f'[image: {ref}]', 1).replace('<image>', f'[image: {cur}]', 1)   # image_list=[reference, current]
        w.counts['critic'] += 1
        reply = self.llm(VLAC_SYSTEM + '\n\n' + VLAC_FORMAT, user, tag=f'{self.tag}|critic{w.counts["critic"]}')
        m = re.search(r'[-+]?\d+(?:\.\d+)?', reply)
        if not m:
            return 500, {'detail': f'Result parsing failed: could not convert {reply[:60]!r} to float'}
        critic_list = [float(m.group(0))]
        value_list = critic_to_value_simple(critic_list)
        w.note(f'critic: score {critic_list[0]:g} for "{body["task_description"][:80]}"')
        return 200, {'critic_list': critic_list, 'value_list': value_list, 'latency_ms': CRITIC_LATENCY_MS}

    def _route(self, method, url, body):
        from urllib.parse import urlsplit, parse_qs
        u = urlsplit(url if '://' in url else 'http://' + url)
        host = f'{u.scheme}://{u.netloc}'
        path, query = u.path or '/', parse_qs(u.query)
        svc = self.spec['hosts']['service']
        if u.hostname == svc and u.port == MEMORY_PORT:
            return self._memory_call(method, path + (('?' + u.query) if u.query else ''), body)
        if u.hostname == svc and u.port == VLAC_PORT:
            return self._critic(method, path, body)
        if u.hostname == svc:
            return 503, {'detail': 'service unavailable'}
        for r in self.world.robots.values():
            if host == r['base']:
                return self.world.robot_call(r, method, path, body, query)
        return 0, {'error': f'connection refused: {host}'}

    def _memory_call(self, method, path, body):
        w = self.world
        resp = self.mem.request(method, path, json=body if method != 'GET' else None)
        try:
            data = json.loads(resp.text.replace(str(self.settings.data_dir), MEMORY_ROOT))
        except ValueError:
            data = {'detail': resp.text[:300]}
        if path.startswith('/query/'):
            w.counts['memory_queries'] += 1
            if 'M->A' in self.cut and resp.status_code == 200:
                data = {'results': []}
            hits = data.get('results', []) if isinstance(data, dict) else []
            q = f"memory query {path} {json.dumps(body, ensure_ascii=False)[:80]}"
            w.note(f'{q}: rejected ({resp.status_code})' if resp.status_code != 200 else f'{q}: {len(hits)} result(s)'
                   + (': ' + '; '.join(f"{h.get('name')} at ({h['target_pose']['x']}, {h['target_pose']['y']})" for h in hits[:3]) if hits else ''))
        elif path.startswith('/memory/'):
            if resp.status_code == 200:
                w.counts['memory_writes'] += 1
                what = (body or {}).get('object_name') or (body or {}).get('place_name') or (body or {}).get('note') or ''
                w.note(f'memory write {path}: {str(what)[:80]}')
            else:
                w.note(f'memory write {path} rejected ({resp.status_code})')
        return resp.status_code, data

    def _seed(self):
        """Memory present before the first session, written through the service's own API."""
        w = self.world
        self._seeding = True
        try:
            if self.spec.get('seed_places'):
                for p in w.places:
                    x, y = w.place_pose(p)
                    self.mem.post('/memory/place/upsert', json={
                        'place_name': p, 'robot_id': 'go2_001', 'robot_type': 'quadruped',
                        'place_pose': {'x': x, 'y': y, 'z': 0.0, 'frame_id': 'map'}, 'alias': w.places[p]['aliases'],
                        'note': 'operator-labelled place anchor', 'timestamp': (w.clock - timedelta(days=30)).timestamp()})
            for s in self.world.item['seed']:
                ts = (w.clock - timedelta(hours=s['hours_ago'])).timestamp()
                x, y = w.place_pose(s['at'])
                rp = {'x': x - 0.5, 'y': y - 0.5, 'z': 0.0, 'frame_id': 'map'}
                if s['kind'] == 'object':
                    ox, oy, oz = w.surface_pose(s['at'], s['on'])
                    r = self.mem.post('/memory/object/upsert', json={
                        'object_name': s['object_name'], 'robot_id': s['robot_id'], 'robot_type': s['robot_type'],
                        'robot_pose': rp, 'object_pose': {'x': ox, 'y': oy, 'z': oz, 'frame_id': 'map'},
                        'detect_confidence': s['detect_confidence'], 'note': s['note'], 'timestamp': ts})
                else:
                    path = f"/data/frames/seed_{s['robot_id']}_{int(ts)}.jpg"
                    w.frames[path] = s['frame']
                    r = self.mem.post('/memory/semantic/ingest', json={
                        'robot_id': s['robot_id'], 'robot_type': s['robot_type'], 'robot_pose': rp, 'note': s['note'],
                        'tags': s['tags'], 'timestamp': ts, 'image': path})
                assert r.status_code == 200, r.text
        finally:
            self._seeding = False

    # ---- OpenClaw workspace context ---------------------------------------------------------------------
    def _workspace_context(self):
        h = self.spec['hosts']
        robot = (OPENCLAW / 'ROBOT.md').read_text(encoding='utf-8')
        for key, host in (('PIPER', 'piper'), ('G1', 'g1'), ('GO2', 'go2')):
            u = h[host]
            robot = robot.replace(f'<{key}_BASE_URL>', u).replace(f'http://<{key}_HOST>:<{key}_PORT>', u)
        fills = {
            '- Control/API endpoint for Piper:': f"- Control/API endpoint for Piper: {h['piper']}",
            '- Control/API endpoint for Unitree G1:': f"- Control/API endpoint for Unitree G1: {h['g1']}",
            '- Control/API endpoint for Unitree Go2:': f"- Control/API endpoint for Unitree Go2: {h['go2']}",
            '- Auth method / API key details:': '- Auth method / API key details: none (lab network, no key)',
            '- Camera list for each robot:': '- Camera list for each robot: Piper wrist camera; G1 head camera; Go2 front camera',
            '- E-stop / recovery procedure for each robot:': '- E-stop / recovery procedure for each robot: POST <base URL>/stop',
            '- Teleoperation fallback path:': '- Teleoperation fallback path: ask the human operator',
        }
        for a, b in fills.items():
            robot = robot.replace(a, b)
        service = (OPENCLAW / 'SERVICE.md').read_text(encoding='utf-8').replace('<SERVICE_HOST>', h['service'])
        setup = (OPENCLAW / 'setup.sh').read_text(encoding='utf-8')
        checklist = '\n'.join(re.findall(r"'(\d\. [^']*?)\\n'", setup))       # setup.sh insert_block (AGENTS.md patch)
        skills = []
        for d in sorted((OPENCLAW / 'skills').iterdir()):
            text = (d / 'SKILL.md').read_text(encoding='utf-8')
            skills.append(f'### skills/{d.name}/SKILL.md\n\n{text.strip()}')
        return ('## AGENTS.md (AbotClaw session checklist added by setup.sh)\n' + checklist +
                '\n\n## MISSION.md\n\n' + (OPENCLAW / 'MISSION.md').read_text(encoding='utf-8').strip() +
                '\n\n## ROBOT.md\n\n' + robot.strip() + '\n\n## SERVICE.md\n\n' + service.strip() +
                '\n\n## Skills\n\n' + '\n\n'.join(skills))

    def robot_guide(self, r):
        caps = ['navigate', 'observe'] if r['mobile'] else ['observe']
        if r['manipulate']:
            caps += ['pick', 'place'] + (['insert'] if r['id'] == 'piper_001' else [])
        places = sorted(self.world.places) if r['mobile'] else [r['at']]
        return (f"# {r['model']} ({r['id']}) agent server\nBase URL: {r['base']}. No API key on the lab network.\n"
                f"Skills: {', '.join(caps)} (POST /skill/<name>, JSON body). GET /health shows place, pose and what the robot holds. "
                f"GET /code/result is the last execution; GET /code/history?count=3 lists recent executions, newest first. "
                f"POST /stop halts motion. Named places on the shared map: {places}. "
                "Frames from /skill/observe are saved under image_path, which SpatialMemory and VLAC accept as an image path. "
                "Full reference: GET /code/sdk/markdown.")

    def robot_sdk(self, r):
        lines = [f"# {r['model']} skill reference ({r['base']})", '',
                 'POST /skill/observe {} -> {"image_path": "/data/frames/<robot>_<n>.jpg", "robot_pose": {...}, "place": "...", '
                 '"detections": [{"name": "cup", "confidence": 0.9, "on": "table", "pose": {"x": .., "y": .., "z": .., "frame_id": "map"}}]}']
        if r['mobile']:
            lines.append('POST /skill/navigate {"place": "<named place>"} or {"x": <m>, "y": <m>} (map frame) -> {"ok": true, "place": "...", "pose": {...}}')
        if r['manipulate']:
            lines += ['POST /skill/pick {"object": "<name of a detected object within reach>"} -> {"ok": true, "holding": "...", "gripper": "closed"}',
                      'POST /skill/place {"on": "<surface at the current place, or \'visitor\' to hand over>"} -> {"ok": true, "released": "...", "gripper": "open"}']
            if r['id'] == 'piper_001':
                lines.append('POST /skill/insert {"into": "<port or socket, e.g. hub>"} -> force-limited compliant insertion of the held '
                             'connector, then release -> {"ok": true, "released": "...", "gripper": "open"}')
            lines.append('Manipulation skills report that the motion was executed; whether it achieved the goal is not sensed. '
                         'Check the result with observe or the critic.')
        if not r['mobile']:
            lines.append(f"Fixed base at {r['at']}; reachable surfaces: {list(self.world.places[r['at']]['surfaces'])}.")
        lines += ['GET /health, GET /code/result, GET /code/history?count=3, POST /stop', 'Errors return ok=false with an error message.']
        return '\n'.join(lines)

    # ---- the agent loop ---------------------------------------------------------------------------------
    def _session(self, k, sess):
        w = self.world
        if k:
            w.back_to_dock()
        w.clock = max(w.clock, datetime.strptime(sess['time'], '%Y-%m-%d %H:%M'))
        system = RUNTIME % (sess['max_turns'], f"{w.clock:%Y-%m-%d %H:%M} ({w.clock:%A})") + '\n\n' + self.context
        transcript = [f"[New session {w.clock:%Y-%m-%d %H:%M}]\nHuman: {sess['user']}"]
        w.log.append(f"Session {k + 1} ({w.clock:%H:%M}) human: {sess['user']}")
        reply = None
        for t in range(1, sess['max_turns'] + 1):
            w.counts['turns'] += 1
            text = self.llm(system, '\n\n'.join(transcript) + '\n\nYour next JSON object:', tag=f'{self.tag}|S{k + 1}|t{t}')
            msg = self._parse(text)
            transcript.append(f'Turn {t}, you:\n{text.strip()}')
            if msg is None:
                transcript.append(f'Turn {t}, runtime: your message was not one JSON object as required; nothing was sent.')
                continue
            if msg.get('reply') is not None and not msg.get('requests'):
                reply = str(msg['reply'])
                break
            results = []
            for i, req in enumerate((msg.get('requests') or [])[:MAX_REQUESTS], 1):
                method = str(req.get('method', 'GET')).upper()
                url = str(req.get('url', ''))
                body = req.get('json', req.get('body'))
                if isinstance(body, str):
                    try:
                        body = json.loads(body)
                    except ValueError:
                        pass
                try:
                    code, data = self._route(method, url, body)
                except Exception as e:   # a malformed request must not stop the run
                    code, data = 0, {'error': f'{type(e).__name__}: {e}'}
                if not (200 <= code < 300):
                    w.counts['errors'] += 1
                out = json.dumps(data, ensure_ascii=False)
                out = out if len(out) <= MAX_BODY else out[:MAX_BODY] + ' ...(truncated)'
                results.append(f'[{i}] {method} {url} -> {code or "error"}\n{out}')
            transcript.append(f'Turn {t}, results:\n' + ('\n'.join(results) if results else '(no requests)'))
            if msg.get('reply') is not None:
                reply = str(msg['reply'])
                break
        w.log.append(f'  Reply to human: {reply}' if reply is not None else '  (no reply: turn limit reached)')
        return reply

    @staticmethod
    def _parse(text):
        s = text.strip()
        s = re.sub(r'^```(?:json)?\s*|\s*```$', '', s)
        for cand in (s, s[s.find('{'): s.rfind('}') + 1] if '{' in s else ''):
            try:
                v = json.loads(cand)
                if isinstance(v, dict):
                    return v
            except ValueError:
                continue
        return None

    # ---- harness interface ------------------------------------------------------------------------------
    def items(self):
        out = []
        for it in self.spec['items']:
            truth = '; '.join(f"{o} at {v['place']} on the {v['on']}" for o, v in self.spec['objects'].items() if o != 'usb hub')
            reqs = ' Then '.join(f"at {s['time'][-5:]} the human asks: \"{s['user']}\"" for s in it['sessions'])
            ctx = ('One OpenClaw agent runs a robot fleet: Go2 (quadruped scout with a camera), G1 (humanoid that can '
                   'carry one object) and a Piper arm fixed at its workcell, with a shared spatial memory and a progress '
                   f'critic. Each request starts a new agent session; memory and the robots keep their state. {reqs}. '
                   f'Where things were at the start: {truth}.')
            out.append({'id': it['id'], 'judge_context': ctx})
        return out

    def run(self, item, cut, sample):
        it = next(i for i in self.spec['items'] if i['id'] == item['id'])
        self.cut = set(cut)
        self.tag = f'{it["id"]}|s{sample}'             # names item and sample (and session/turn or critic call), not the arm
        self.world = World(self.spec, it, self)
        self._ids = 0
        self._run_dir = Path(tempfile.mkdtemp(prefix='run-', dir=self._tmp))
        self.mem = self._memory_service()
        self._seed()
        replies = [self._session(k, s) for k, s in enumerate(it['sessions'])]
        w = self.world
        goals = w.goal_met()
        ok = all(g[0] for g in goals)
        output = '\n'.join(w.log + ['', 'Outcome: ' + '; '.join(g[1] for g in goals) + '.'])
        return {
            'output': output,
            'replies': replies,
            'metrics': {
                'task_success': int(ok),
                'robot_actions': w.counts['navigate'] + w.counts['pick'] + w.counts['place'],
                'observations': w.counts['observe'],
                'memory_writes': w.counts['memory_writes'],
                'memory_queries': w.counts['memory_queries'],
                'critic_calls': w.counts['critic'],
                'turns': w.counts['turns'],
                'failed_requests': w.counts['errors'],
                'replied': sum(r is not None for r in replies),
            },
        }
