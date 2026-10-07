"""A toy reminder service for testing the harness offline (backend mock:echo).

Memory keeps the user's notes. Action writes a reminder from the current event and the notes.
M->A is cut by withholding the notes from Action; A->M by not recording sent reminders.
"""
from halo.run.adapter import BaseAdapter


class Adapter(BaseAdapter):
    channels = {'M->A': 'notes given to the reminder prompt', 'A->M': 'sent reminders recorded in the notes'}

    def items(self):
        return [{'id': 'dentist', 'notes': ['prefers mornings'], 'events': ['dentist at 9', 'dentist moved to 10'],
                 'judge_context': 'User prefers morning reminders.'}]

    def run(self, item, cut, sample):
        notes, sent = list(item['notes']), []
        for ev in item['events']:
            shown = [] if 'M->A' in cut else notes
            msg = self.llm('Write a reminder.', f'notes: {shown}\nevent: {ev}', tag=f'{item["id"]}|s{sample}')
            sent.append(msg)
            if 'A->M' not in cut:
                notes.append(f'sent: {msg}')
        return {'output': '\n'.join(sent), 'metrics': {'notes': len(notes)}}
