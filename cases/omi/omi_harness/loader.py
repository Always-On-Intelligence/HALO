"""Import layer for running Omi's backend modules outside their deployment.

Three kinds of upstream module names exist inside one run:

* vendored: a file under core/backend/ (copied unchanged from BasedHardware/omi). Loaded normally.
* faked: a file under omi_harness/fakes/ with the same dotted name. These replace storage
  (Firestore, Pinecone, Redis, the canonical memory service), the model clients, notification
  delivery and the thread-pool executors. Each fake keeps the upstream function signatures.
* stubbed: any other upstream module that a vendored module imports at module level. Its
  attributes are inert placeholders (falsy, callable, iterable-empty). They cover telemetry,
  billing gates, rollout flags, shadow evaluations and integrations this configuration does not
  use. Every call to a placeholder at run time is recorded in STUB_CALLS so it can be reviewed.

Vendored modules get two harness-level substitutions when they load, and nothing else: their
module-global ``datetime``/``time`` names read the simulated scenario clock, and ``uuid.uuid4``
is deterministic per call site, so that runs with the same inputs build byte-identical prompts.
"""
from __future__ import annotations

import collections
import datetime as _dt
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys
import threading
import time as _time
import types
import uuid as _uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
CORE = Path(os.environ.get('OMI_CORE_BACKEND', CASE / 'core' / 'backend'))
FAKES = HERE / 'fakes'
UPSTREAM_TOP = {'database', 'utils', 'models', 'config', 'routers', 'services', 'testing', 'jobs'}

STUB_CALLS: collections.Counter = collections.Counter()
STUBBED_MODULES: set = set()


# --------------------------------------------------------------------------------------------
# simulated clock and deterministic ids
# --------------------------------------------------------------------------------------------
class SimClock:
    """Scenario time. The adapter moves it forward as the scripted day unfolds."""

    def __init__(self):
        self._now = _dt.datetime(2026, 10, 5, 8, 0, tzinfo=_dt.timezone.utc)
        self._lock = threading.Lock()

    def set(self, when: _dt.datetime):
        with self._lock:
            self._now = when.astimezone(_dt.timezone.utc)

    def advance(self, seconds: float):
        with self._lock:
            self._now = self._now + _dt.timedelta(seconds=seconds)

    def now(self) -> _dt.datetime:
        return self._now

    def time(self) -> float:
        return self._now.timestamp()


CLOCK = SimClock()
_REAL_DATETIME = _dt.datetime


class _SimDatetimeMeta(type):
    def __instancecheck__(cls, obj):
        return isinstance(obj, _REAL_DATETIME)

    def __subclasscheck__(cls, sub):
        return issubclass(sub, _REAL_DATETIME)


class SimDatetime(_REAL_DATETIME, metaclass=_SimDatetimeMeta):
    """datetime whose now()/utcnow()/today() read the scenario clock."""

    @classmethod
    def now(cls, tz=None):
        n = CLOCK.now()
        if tz is None:
            return n.astimezone().replace(tzinfo=None)
        return n.astimezone(tz)

    @classmethod
    def utcnow(cls):
        return CLOCK.now().replace(tzinfo=None)

    @classmethod
    def today(cls):
        return cls.now()


class _SimTimeModule(types.ModuleType):
    """`time` as seen by vendored modules: time() is scenario time, everything else is real."""

    def __init__(self):
        super().__init__('time')

    def __getattr__(self, name):
        return getattr(_time, name)

    @staticmethod
    def time():
        return CLOCK.time()

    @staticmethod
    def time_ns():
        return int(CLOCK.time() * 1e9)


SIM_TIME = _SimTimeModule()


class _DeterministicUuid(types.ModuleType):
    """`uuid` as seen by vendored modules: uuid4() derives from (run seed, call site, count)."""

    def __init__(self):
        super().__init__('uuid')
        self.seed = 'unset'
        self.counters: collections.Counter = collections.Counter()

    def reset(self, seed: str):
        self.seed, self.counters = seed, collections.Counter()

    def __getattr__(self, name):
        return getattr(_uuid, name)

    def uuid4(self):
        f = sys._getframe(1)
        site = f'{f.f_code.co_filename}:{f.f_lineno}'
        self.counters[site] += 1
        h = hashlib.sha256(f'{self.seed}|{site}|{self.counters[site]}'.encode()).digest()
        return _uuid.UUID(bytes=h[:16], version=4)


SIM_UUID = _DeterministicUuid()


class _SimDatetimeModule(types.ModuleType):
    """`import datetime` as seen by vendored modules."""

    def __init__(self):
        super().__init__('datetime')
        self.datetime = SimDatetime

    def __getattr__(self, name):
        return getattr(_dt, name)


SIM_DATETIME_MODULE = _SimDatetimeModule()


def _sim_globals(module):
    g = module.__dict__
    for k, v in list(g.items()):
        if v is _REAL_DATETIME:
            g[k] = SimDatetime
        elif v is _dt:
            g[k] = SIM_DATETIME_MODULE
        elif v is _time:
            g[k] = SIM_TIME
        elif v is _uuid:
            g[k] = SIM_UUID
        elif v is _uuid.uuid4:
            g[k] = SIM_UUID.uuid4
        elif v is _time.time:
            g[k] = SIM_TIME.time


# --------------------------------------------------------------------------------------------
# placeholders for stubbed upstream modules
# --------------------------------------------------------------------------------------------
class Placeholder:
    """Inert stand-in for an attribute of a stubbed module."""

    def __init__(self, name):
        object.__setattr__(self, '_name', name)

    def __getattr__(self, attr):
        if attr.startswith('__') and attr.endswith('__'):
            raise AttributeError(attr)
        return Placeholder(f'{self._name}.{attr}')

    def __call__(self, *args, **kwargs):
        # decorator use (@stubbed_decorator or @stubbed_factory(...)): keep the decorated object
        if len(args) == 1 and not kwargs and isinstance(args[0], (types.FunctionType, type, staticmethod, classmethod)):
            return args[0]
        STUB_CALLS[self._name] += 1
        return Placeholder(self._name + '()')

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __contains__(self, item):
        return False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __await__(self):
        if False:
            yield
        return None

    def __mro_entries__(self, bases):
        return (object,)

    def __or__(self, other):        # used in annotations: StubbedType | None
        return self

    __ror__ = __or__

    def __getitem__(self, item):    # used in annotations: StubbedGeneric[...]
        return self

    def __repr__(self):
        return f'<stub {self._name}>'

    def __str__(self):
        return ''

    def __eq__(self, other):
        return other is self

    def __hash__(self):
        return id(self)

    def __int__(self):
        return 0

    def __float__(self):
        return 0.0

    def __index__(self):
        return 0

    def __lt__(self, other):
        return False

    __gt__ = __le__ = __ge__ = __lt__


class StubModule(types.ModuleType):
    def __getattr__(self, attr):
        if attr.startswith('__') and attr.endswith('__'):
            raise AttributeError(attr)
        return Placeholder(f'{self.__name__}.{attr}')


# --------------------------------------------------------------------------------------------
# finder
# --------------------------------------------------------------------------------------------
class _VendoredLoader(importlib.machinery.SourceFileLoader):
    def exec_module(self, module):
        super().exec_module(module)
        _sim_globals(module)


class OmiFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path, target=None):
        if fullname.split('.')[0] not in UPSTREAM_TOP:
            return None
        rel = Path(*fullname.split('.'))
        fake_file, fake_pkg = FAKES / rel.with_suffix('.py'), FAKES / rel / '__init__.py'
        if fake_file.exists():
            return importlib.util.spec_from_file_location(fullname, fake_file)
        if fake_pkg.exists():
            return importlib.util.spec_from_file_location(fullname, fake_pkg,
                                                          submodule_search_locations=[str(fake_pkg.parent)])
        core_file, core_pkg = CORE / rel.with_suffix('.py'), CORE / rel / '__init__.py'
        if core_file.exists():
            return importlib.util.spec_from_file_location(fullname, core_file,
                                                          loader=_VendoredLoader(fullname, str(core_file)))
        if core_pkg.exists():
            return importlib.util.spec_from_file_location(fullname, core_pkg,
                                                          loader=_VendoredLoader(fullname, str(core_pkg)),
                                                          submodule_search_locations=[str(core_pkg.parent)])
        dirs = [str(d) for d in (FAKES / rel, CORE / rel) if d.is_dir()]
        if dirs:   # upstream namespace package (a directory without __init__.py)
            spec = importlib.machinery.ModuleSpec(fullname, None, is_package=True)
            spec.submodule_search_locations = dirs
            return spec
        STUBBED_MODULES.add(fullname)
        return importlib.machinery.ModuleSpec(fullname, self, is_package=True)

    def create_module(self, spec):
        m = StubModule(spec.name)
        m.__path__ = []
        return m

    def exec_module(self, module):
        pass


_INSTALLED = False


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    sys.meta_path.insert(0, OmiFinder())
    _INSTALLED = True


def vendored_files():
    """Upstream files loaded from core/ in this process (relative to backend/)."""
    out = []
    for name, m in list(sys.modules.items()):
        f = getattr(m, '__file__', None)
        if f and str(f).startswith(str(CORE)):
            out.append(str(Path(f).relative_to(CORE)))
    return sorted(out)
