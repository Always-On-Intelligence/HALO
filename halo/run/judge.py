"""Blind pairwise judge: compares the unmodified run with the cut run in random order."""
import hashlib, re

def judge_pair(llm, rubric, context, original, modified, tag):
    flip = int(hashlib.sha256(tag.encode()).hexdigest(), 16) % 2 == 1
    a, b = (modified, original) if flip else (original, modified)
    system = ('You are a careful, blind judge. You compare two outputs produced by an assistant for the same situation. '
              'You do not know how either output was produced. ' + rubric.strip() +
              ' Reply with exactly one token: A, B, or TIE.')
    user = f'Situation:\n{context}\n\nOutput A:\n{a}\n\nOutput B:\n{b}\n\nWhich output is better? Reply A, B, or TIE.'
    text = llm(system, user, tag='judge:' + tag)
    m = re.search(r'\b(A|B|TIE)\b', text.strip().upper())
    choice = m.group(1) if m else 'TIE'
    if choice == 'TIE':
        return 'tie', text
    picked_original = (choice == 'A') != flip
    return ('original' if picked_original else 'modified'), text
