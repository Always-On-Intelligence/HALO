"""Read the continuing loop off a trace: channels, evidence steps, and the level the trace supports.

A trace is the list of events one agent logged through the HALO plugin. Every event belongs to one
module of the loop (Sensing, Memory, or Action) or is a revision of the agent's own mechanism, and it
names the earlier events it used. Those `uses` links are the whole basis of the analysis:

- a channel X->Y is observed when an event of module Y used an event of module X;
- the five evidence steps are observed from how actions, outcomes, and revisions link to each other;
- a level is supported when the trace shows every condition of that level and of the levels below it.

The definitions follow `halo/read/protocol/PROTOCOL.md` and the survey's level checklist. A trace only
shows what the agent logged, so anything it does not show is "not observed", never "absent".
"""
from dataclasses import dataclass, field

MODULES = {'S': 'Sensing', 'M': 'Memory', 'A': 'Action'}
KINDS = {
    'observe': 'S',    # current observation, user input, external event, or execution state
    'outcome': 'S',    # later evidence about one of the agent's own actions
    'remember': 'M',   # information retained for later interactions
    'recall': 'M',     # retained information looked up again
    'act': 'A',        # silence, communication, preparation, or execution
    'revise': None,    # a durable change to the agent's own mechanism, not a module of the loop
}
CHANNELS = ['S->A', 'S->M', 'M->A', 'A->S', 'M->S', 'A->M']
STEPS = ['record', 'outcome', 'attribution', 'revision', 'later_use']
LEVELS = {
    0: 'Session local',
    1: 'Retained state',
    2: 'State-guided decision',
    3: 'Unrequested action',
    4: 'Attributed outcomes',
    5: 'Governed revision',
}
NEEDS = {
    1: 'something kept in memory and used in a later session',
    2: 'memory from an earlier session used by an action or an observation',
    3: 'an action the agent decided on by itself between requests (trigger "self")',
    4: 'an outcome linked to the action it concerns and then used by a later action or revision, through A→S or A→M',
    5: 'a revision by the agent, approved or bounded by the user, that a later action used',
}
GOVERNED = {'approved', 'bounded'}


def arrow(channel):
    return channel.replace('->', '→')


@dataclass
class Finding:
    observed: bool
    evidence: list = field(default_factory=list)   # event ids that show it
    note: str = ''


def _index(events):
    by_id = {e['id']: e for e in events}
    users = {e['id']: [] for e in events}            # event id -> events that used it
    for e in events:
        for u in e.get('uses', []):
            if u in users:
                users[u].append(e['id'])
    return by_id, users


def _descendants(start, users):
    """Every event that used `start`, directly or through other events."""
    seen, stack = set(), list(users.get(start, []))
    while stack:
        i = stack.pop()
        if i not in seen:
            seen.add(i)
            stack.extend(users.get(i, []))
    return seen


def _ancestors(start, by_id):
    """Every event that `start` used, directly or through other events."""
    seen, stack = set(), list(by_id[start].get('uses', []))
    while stack:
        i = stack.pop()
        if i not in seen and i in by_id:
            seen.add(i)
            stack.extend(by_id[i].get('uses', []))
    return seen


def channels(events):
    """For each of the six channels, the uses links that carried information across it."""
    by_id, _ = _index(events)
    found = {c: Finding(False) for c in CHANNELS}
    for e in events:
        to = KINDS[e['kind']]
        if to == 'M' and e['kind'] != 'remember':
            continue   # a lookup prompted by an input or an action writes nothing to Memory
        for u in e.get('uses', []):
            src = KINDS[by_id[u]['kind']] if u in by_id else None
            if to and src and src != to:
                f = found[f'{src}->{to}']
                f.observed = True
                f.evidence.append(f'{u}→{e["id"]}')
    return found


def steps(events):
    """The five evidence steps of the self-evolving loop, each judged on its own."""
    by_id, users = _index(events)
    kind = lambda i: by_id[i]['kind'] if i in by_id else None
    found = {s: Finding(False) for s in STEPS}

    for e in events:
        if e['kind'] == 'remember':
            acts = [u for u in e.get('uses', []) if kind(u) == 'act']
            outs = [u for u in e.get('uses', []) if kind(u) == 'outcome']
            if acts:
                found['record'].observed = True
                found['record'].evidence.append(f'{acts[0]}→{e["id"]}')
            if outs:
                found['outcome'].observed = True
                found['outcome'].evidence.append(f'{outs[0]}→{e["id"]}')

    for e in events:
        if e['kind'] != 'outcome' or kind(e.get('about')) != 'act':
            continue
        later = [i for i in _descendants(e['id'], users) if kind(i) in ('act', 'revise')]
        if later:
            found['attribution'].observed = True
            found['attribution'].evidence.append(f'{e["about"]}⇠{e["id"]}→{min(later, key=_seq)}')
    if not found['outcome'].observed and any(e['kind'] == 'outcome' for e in events):
        found['outcome'].note = 'outcomes were observed but none was kept in memory'
    if not found['attribution'].observed and any(e['kind'] == 'outcome' and e.get('about') for e in events):
        found['attribution'].note = 'outcomes name their action, but no later action or revision used them'

    for e in events:
        if e['kind'] != 'revise':
            continue
        if e.get('made_by') != 'agent':
            found['revision'].note = 'a change made by the user or a developer is not a revision by the agent'
            continue
        found['revision'].observed = True
        found['revision'].evidence.append(e['id'])
        later = [i for i in _descendants(e['id'], users) if kind(i) == 'act']
        if later:
            found['later_use'].observed = True
            found['later_use'].evidence.append(f'{e["id"]}→{min(later, key=_seq)}')
    return found


def _seq(event_id):
    return int(event_id.lstrip('e')) if event_id.lstrip('e').isdigit() else 0


def chain(events):
    """One action whose outcome led to a revision that a later action used, if the trace has one."""
    by_id, users = _index(events)
    for o in events:
        if o['kind'] != 'outcome' or by_id.get(o.get('about'), {}).get('kind') != 'act':
            continue
        for r in sorted(_descendants(o['id'], users), key=_seq):
            if by_id[r]['kind'] != 'revise' or by_id[r].get('made_by') != 'agent':
                continue
            later = [i for i in _descendants(r, users) if by_id[i]['kind'] == 'act']
            if later:
                return [o['about'], o['id'], r, min(later, key=_seq)]
    return []


def level(events, found_channels=None, found_steps=None):
    """The highest level whose conditions, and those of every level below it, the trace shows.

    Returns (level or None, {level: Finding}) where each Finding says whether that level's own
    condition was observed and which events show it.
    """
    if not events:
        return None, {}
    by_id, _ = _index(events)
    found_channels = found_channels or channels(events)
    found_steps = found_steps or steps(events)
    session = lambda i: by_id[i].get('session') or ''
    checks = {0: Finding(True, [events[0]['id']])}

    # L1, state durability: something kept in memory is used in a later session
    # L2, state-guided decision: such retained state reaches a decision of Action or of Sensing
    durable, guided = Finding(False), Finding(False)
    for e in events:
        for a in _ancestors(e['id'], by_id):
            if by_id[a]['kind'] == 'remember' and session(a) != session(e['id']):
                if not durable.evidence:
                    durable.observed, durable.evidence = True, [f'{a}→{e["id"]}']
                if e['kind'] in ('act', 'observe', 'outcome') and not guided.evidence:
                    guided.observed, guided.evidence = True, [f'{a}→{e["id"]}']
    checks[1], checks[2] = durable, guided

    # L3, operational continuity: the agent decided between requests whether to act
    own = [e['id'] for e in events if e['kind'] == 'act' and e.get('trigger') == 'self']
    checks[3] = Finding(bool(own), own[:3])

    # L4, attribution through an edge from Action: A->S for a check during execution, A->M for a later outcome
    edge = found_channels['A->S'].observed or found_channels['A->M'].observed
    attributed = found_steps['attribution'].observed and edge
    checks[4] = Finding(attributed, found_steps['attribution'].evidence[:3])

    # L5, governed self-evolution: a revision by the agent, within the user's approval or bounds, used later
    governed = [e['id'] for e in events if e['kind'] == 'revise' and e.get('made_by') == 'agent'
                and e.get('governance') in GOVERNED and e['id'] in {x.split('→')[0] for x in found_steps['later_use'].evidence}]
    checks[5] = Finding(bool(governed), governed[:3])
    for n in range(1, 6):
        checks[n].note = '' if checks[n].observed else f'needs {NEEDS[n]}'

    reached = 0
    for n in range(1, 6):
        if not checks[n].observed:
            break
        reached = n
    return reached, checks


def report(events, agent='', session=''):
    """The diagnosis of one trace as Markdown, with the same rows as the survey's tables."""
    if not events:
        return f'No events logged{" for " + agent if agent else ""} yet. Call halo_guide to see what to log.'
    ch, st = channels(events), steps(events)
    reached, checks = level(events, ch, st)
    sessions = sorted({e.get('session') or '' for e in events} - {''})
    lines = [f'# HALO report{": " + agent if agent else ""}', '',
             f'{len(events)} events in {max(len(sessions), 1)} session(s), from {events[0]["ts"][:16]} to {events[-1]["ts"][:16]} UTC.'
             + (f' Scope: session `{session}`.' if session else ''), '',
             f'**The trace supports L{reached} ({LEVELS[reached]}).** A level is a lower bound: the agent may do more than it logged.', '',
             '## Channels', '', '| Channel | In this trace | Evidence |', '|---|---|---|']
    for c in CHANNELS:
        f = ch[c]
        lines.append(f'| {arrow(c)}{" (basic)" if c == "S->A" else ""} | {"observed" if f.observed else "not observed"} | {", ".join(f.evidence[:3])} |')
    lines += ['', '## Evidence for self-evolution', '', '| Step | In this trace | Evidence |', '|---|---|---|']
    for s in STEPS:
        f = st[s]
        lines.append(f'| {s.replace("_", " ")} | {"observed" if f.observed else "not observed"} | {", ".join(f.evidence[:3]) or f.note} |')
    linked = chain(events)
    lines += ['', 'One connected chain: ' + (' → '.join(linked) + ' (action, outcome, revision, later action).' if linked
                                           else 'none, no outcome of an action led to a revision that a later action used.')]
    lines += ['', '## Levels', '', '| Level | Condition in this trace | Evidence |', '|---|---|---|']
    for n in range(0, 6):
        f = checks[n]
        lines.append(f'| L{n} {LEVELS[n]} | {"observed" if f.observed else "not observed"} | {", ".join(f.evidence[:3]) or f.note} |')
    if reached < 5:
        lines += ['', f'To support L{reached + 1}, the trace needs {NEEDS[reached + 1]}.']
    lines += ['', 'All events were logged by the agent itself through HALO. HALO checks how they link, not whether they happened.']
    return '\n'.join(lines)
