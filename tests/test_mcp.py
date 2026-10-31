"""The plugin's analysis and ledger, on a reminder service that learns the user's timing over three days."""
import pytest

from halo.mcp.analysis import chain, channels, level, report, steps
from halo.mcp.ledger import Ledger, LedgerError

DAYS = [
    # day 1: the user states a preference, the service keeps it
    ('day1', 'observe', 'user asks for reminders before meetings', [], {}),
    ('day1', 'remember', 'preference: remind before meetings', ['e1'], {}),
    # day 2: the service reminds on its own, keeps a record, hears it was too early
    ('day2', 'observe', 'calendar shows a 10:00 meeting', [], {}),
    ('day2', 'recall', 'reminder preference', ['e2'], {}),
    ('day2', 'act', 'reminded the user at 9:30', ['e3', 'e4'], {'trigger': 'self'}),
    ('day2', 'remember', 'record: reminder sent at 9:30', ['e5'], {}),
    ('day2', 'outcome', 'user: 30 minutes is too early', [], {'about': 'e5'}),
    ('day2', 'remember', 'the 9:30 reminder was too early', ['e7', 'e6'], {}),
    ('day2', 'revise', 'remind 10 minutes before instead of 30', ['e8'],
     {'target': 'reminder timing rule', 'made_by': 'agent', 'governance': 'approved'}),
    # day 3: the revised rule is used
    ('day3', 'observe', 'calendar shows a 14:00 meeting', [], {}),
    ('day3', 'act', 'reminded the user at 13:50', ['e10', 'e9'], {'trigger': 'self'}),
]


def trace(tmp_path, rows=DAYS, agent='dot'):
    ledger = Ledger(tmp_path / 'ledger.sqlite')
    for session, kind, summary, uses, extra in rows:
        ledger.add(agent, kind, summary, uses, session, **extra)
    return ledger, ledger.events(agent)


def test_channels_follow_uses_links(tmp_path):
    _, events = trace(tmp_path)
    found = channels(events)
    assert {c for c, f in found.items() if f.observed} == {'S->A', 'S->M', 'M->A', 'A->M'}
    assert 'e4→e5' in found['M->A'].evidence and 'e5→e6' in found['A->M'].evidence


def test_steps_and_chain(tmp_path):
    _, events = trace(tmp_path)
    found = steps(events)
    assert all(found[s].observed for s in found)
    assert chain(events) == ['e5', 'e7', 'e9', 'e11']


def test_full_trace_supports_l5(tmp_path):
    _, events = trace(tmp_path)
    reached, checks = level(events)
    assert reached == 5 and checks[3].evidence[0] == 'e5'


@pytest.mark.parametrize('cut, expected', [
    (lambda rows: rows[:8] + [('day3', 'act', 'reminded 10 minutes before, as the user said', ['e8'],
                               {'trigger': 'self'})], 4),                         # outcome used, no revision
    (lambda rows: rows[:8], 3),                                                  # outcome kept but never used
    (lambda rows: [r[:4] + ({},) if r[1] == 'act' else r for r in rows[:6]], 2),  # requested actions only
    (lambda rows: [('day1',) + r[1:] for r in rows], 0),                         # one session, nothing durable
])
def test_levels_drop_when_conditions_are_missing(tmp_path, cut, expected):
    _, events = trace(tmp_path, cut(DAYS))
    assert level(events)[0] == expected


def test_user_written_change_is_not_a_revision(tmp_path):
    rows = DAYS[:8] + [('day2', 'revise', 'user rewrote the rule', ['e8'],
                        {'target': 'reminder rule', 'made_by': 'user', 'governance': 'approved'})] + DAYS[9:]
    _, events = trace(tmp_path, rows)
    found = steps(events)
    assert not found['revision'].observed and 'not a revision' in found['revision'].note
    assert level(events)[0] == 4


def test_recall_prompted_by_input_is_not_a_write(tmp_path):
    rows = [('day1', 'observe', 'user mentions a meeting', [], {}), ('day1', 'recall', 'meeting preferences', ['e1'], {})]
    _, events = trace(tmp_path, rows)
    assert not channels(events)['S->M'].observed


def test_ledger_rejects_unknown_links(tmp_path):
    ledger, _ = trace(tmp_path, DAYS[:3])
    with pytest.raises(LedgerError, match='unknown event id'):
        ledger.add('dot', 'act', 'reminded', ['e99'], 'day2', trigger='self')
    with pytest.raises(LedgerError, match='about must be'):
        ledger.add('dot', 'outcome', 'reply', [], 'day2', about='e1')
    with pytest.raises(LedgerError, match='unknown event id'):
        ledger.add('grok-bot', 'remember', 'not mine', ['e1'], 'day1')   # ids are per agent


def test_report_mentions_level_and_rows(tmp_path):
    _, events = trace(tmp_path)
    text = report(events, 'dot')
    assert 'supports L5 (Governed revision)' in text and '| M→S | not observed |' in text
