"""Draw the loop-closure levels the way the survey's Figure 10 does, with a little motion.

    python3 scripts/levels.py        writes src/assets/levels-en.svg and src/assets/levels-zh.svg

Each level is a band: its code, name, and one line on the left, a step of the staircase in the middle, and
on the right what the level adds to the system below it. Colours follow the survey's palette, and the text
uses the docs' CSS variables, so the SVG is inlined into the page and follows its light or dark theme.

The animation lights the levels from L0 to L5, one after another, and keeps each lit, because a level
includes every level below it. A small block climbs the staircase to the level being lit, and a dot runs
once through that level's diagram. After L5 the drawing rests, then starts again.
"""
import math
from pathlib import Path

COLORS = ['#8c8c8c', '#8B692E', '#556B88', '#984A3B', '#607A6D', '#6C5F7A']
W, ROW, GAP, TOP = 760, 88, 8, 8
BOX_X, BOX_W, BOX_H = 352, 400, 72
PERIOD = 12.0
START, SLOT, REST = 0.3, 1.75, 11.3

TEXT = {
    'en': {
        'names': ['Session local', 'Retained state', 'State-guided decision', 'Unrequested action',
                  'Attributed outcomes', 'Governed revision'],
        'lines': [['Respond now, and nothing', 'carries over.'], ['Carry state across', 'interactions.'],
                  ['Let retained state shape', 'the next move.'], ['Act or wait, with no', 'request.'],
                  ['Trace a reply or rating to', 'the decision it concerns.'],
                  ['Revise the mechanism within', 'conditions the user set.']],
        'sensing': ['Sensing'], 'immediate': ['Immediate', 'response'], 'context': ['Short-term', 'context'],
        'session': 'within one session', 'system': 'L{} system', 'write': 'write', 'memory': ['Memory'],
        'access': 'access', 'later': ['Later', 'interaction'], 'boundary': 'interaction boundary',
        'ctxmem': 'context + memory', 'policy': ['Action', 'policy'], 'response': ['Response'], 'update': 'update',
        'proposal': ['Action', 'proposal'], 'initiate': ['Initiate', 'interaction?'], 'silent': ['Stay', 'silent'],
        'yes': 'yes', 'no': 'no', 'execution': ['Authorized', 'execution'], 'world': ['World & user'],
        'verifier': ['Verifier'], 'outcome': 'outcome', 'attribution': ['Attribution'],
        'revision': ['Mechanism', 'revision'], 'gate': ['Gate'], 'commit': ['Commit v2'], 'keep': ['Keep v1'],
        'pass': 'pass', 'fail': 'fail', 'future': 'future policy',
        'title': 'Loop-closure levels L0 to L5, each adding to the system below it',
    },
    'zh': {
        'names': ['会话内', '留存状态', '状态引导决策', '未经请求的行动', '结果归因', '受治理的修订'],
        'lines': [['当下回应，什么也不带到', '下一次。'], ['跨交互保留状态。', ''], ['用保留的状态决定', '下一步。'],
                  ['没有请求，也会决定', '行动还是等待。'], ['把回复或评分追溯到', '它对应的决策。'],
                  ['在用户设定的条件内', '修订机制。']],
        'sensing': ['感知'], 'immediate': ['即时回应'], 'context': ['短期上下文'],
        'session': '同一会话内', 'system': 'L{} 系统', 'write': '写入', 'memory': ['记忆库'],
        'access': '读取', 'later': ['之后的交互'], 'boundary': '交互边界',
        'ctxmem': '上下文 + 记忆', 'policy': ['行动策略'], 'response': ['回应'], 'update': '更新',
        'proposal': ['行动提议'], 'initiate': ['发起交互？'], 'silent': ['保持沉默'],
        'yes': '是', 'no': '否', 'execution': ['授权执行'], 'world': ['世界与用户'],
        'verifier': ['验证'], 'outcome': '结果', 'attribution': ['归因'],
        'revision': ['机制修订'], 'gate': ['条件门'], 'commit': ['提交 v2'], 'keep': ['保留 v1'],
        'pass': '通过', 'fail': '未通过', 'future': '之后的策略',
        'title': '闭环等级 L0 到 L5，每一级都建立在下一级的系统之上',
    },
}


def row_y(level):
    return TOP + (5 - level) * (ROW + GAP)


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def pace(*points):
    return ';'.join(f'{t / PERIOD:.4f}' for t, _ in points), ';'.join(str(v) for _, v in points)


def light(start, end=REST, shown=1):
    kt, vals = pace((0, 0), (start, 0), (start + 0.25, shown), (end, shown), (end + 0.4, 0), (PERIOD, 0))
    return (f'<animate attributeName="opacity" dur="{PERIOD}s" repeatCount="indefinite" calcMode="linear" '
            f'keyTimes="{kt}" values="{vals}"/>')


class Box:
    """One level's diagram, in coordinates local to its box."""

    def __init__(self, level, color):
        self.level, self.color, self.parts = level, color, []

    def node(self, x, y, w, h, lines, kind='plain'):
        cls = {'plain': 'lv-node', 'system': 'lv-node lv-sys', 'gate': 'lv-node lv-gate', 'store': 'lv-node lv-store'}[kind]
        fill = f' style="fill:url(#lv-hatch-{self.level})"' if kind == 'system' else ''
        rx = 3 if kind == 'gate' else 6
        self.parts.append(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"{fill} '
                          f'stroke="{self.color}"/>')
        n = len(lines)
        for i, line in enumerate(lines):
            ty = y + h / 2 + (i - (n - 1) / 2) * 13 + 4
            self.parts.append(f'<text class="lv-t" x="{x + w / 2}" y="{ty:.1f}" text-anchor="middle">{esc(line)}</text>')
        return (x + w / 2, y + h / 2, x, y, w, h)

    def arrow(self, points, label=None, at=None, dashed=False):
        d = 'M' + ' L'.join(f'{x:.1f},{y:.1f}' for x, y in points)
        self.parts.append(f'<path class="lv-a{" lv-dash" if dashed else ""}" d="{d}" marker-end="url(#lv-arr)"/>')
        if label:
            lx, ly = at
            self.parts.append(f'<text class="lv-s" x="{lx}" y="{ly}" text-anchor="middle">{esc(label)}</text>')

    def text(self, x, y, s, anchor='middle'):
        self.parts.append(f'<text class="lv-s" x="{x}" y="{y}" text-anchor="{anchor}">{esc(s)}</text>')


def right(n):
    return (n[2] + n[4], n[1])


def left(n):
    return (n[2], n[1])


def diagrams(T):
    """Each level's box and the path a dot follows through it."""
    out = []
    # L0: sensing, an immediate response, and context that lasts one session
    b = Box(0, COLORS[0])
    s = b.node(14, 18, 74, 26, T['sensing'])
    r = b.node(120, 12, 104, 38, T['immediate'])
    c = b.node(256, 12, 106, 38, T['context'])
    b.arrow([right(s), (left(r)[0] - 2, r[1])])
    b.arrow([right(r), (left(c)[0] - 2, c[1])])
    b.arrow([(c[0], 50), (c[0], 62), (s[0], 62), (s[0], 46)])
    b.text(196, 70, T['session'])
    out.append((b, [(s[0], s[1]), (r[0], r[1]), (c[0], c[1]), (c[0], 62), (s[0], 62), (s[0], s[1])]))
    # L1: the system below writes to a memory that a later interaction reads
    b = Box(1, COLORS[1])
    s = b.node(10, 22, 86, 26, [T['system'].format(0)], 'system')
    m = b.node(148, 17, 86, 36, T['memory'], 'store')
    l = b.node(292, 17, 98, 36, T['later'])
    b.arrow([right(s), (left(m)[0] - 2, m[1])], T['write'], (122, 30))
    b.arrow([right(m), (left(l)[0] - 2, l[1])], T['access'], (252, 30))
    b.parts.append('<path class="lv-bound" d="M268,4 L268,62"/>')
    b.text(268, 70, T['boundary'])
    out.append((b, [(s[0], s[1]), (m[0], m[1]), (l[0], l[1])]))
    # L2: retained state guides the action policy, and the response updates it
    b = Box(2, COLORS[2])
    s = b.node(10, 18, 86, 26, [T['system'].format(1)], 'system')
    p = b.node(158, 12, 92, 38, T['policy'])
    r = b.node(296, 12, 92, 38, T['response'])
    b.arrow([right(s), (left(p)[0] - 2, p[1])], T['ctxmem'], (127, 8))
    b.arrow([right(p), (left(r)[0] - 2, r[1])])
    b.arrow([(r[0], 50), (r[0], 62), (s[0], 62), (s[0], 46)])
    b.text(196, 70, T['update'])
    out.append((b, [(s[0], s[1]), (p[0], p[1]), (r[0], r[1]), (r[0], 62), (s[0], 62), (s[0], s[1])]))
    # L3: a proposal, a decision whether to start an interaction, or silence
    b = Box(3, COLORS[3])
    s = b.node(6, 18, 80, 26, [T['system'].format(2)], 'system')
    p = b.node(106, 12, 84, 38, T['proposal'])
    i = b.node(210, 12, 92, 38, T['initiate'], 'gate')
    q = b.node(330, 12, 64, 38, T['silent'])
    b.arrow([right(s), (left(p)[0] - 2, p[1])])
    b.arrow([right(p), (left(i)[0] - 2, i[1])])
    b.arrow([right(i), (left(q)[0] - 2, q[1])], T['no'], (316, 26))
    b.arrow([(i[0], 50), (i[0], 62), (s[0], 62), (s[0], 46)])
    b.text(150, 70, T['yes'])
    out.append((b, [(s[0], s[1]), (p[0], p[1]), (i[0], i[1]), (i[0], 62), (s[0], 62), (s[0], s[1])]))
    # L4: authorized execution in the world, checked by a verifier, and the outcome fed back
    b = Box(4, COLORS[4])
    s = b.node(6, 28, 80, 26, [T['system'].format(3)], 'system')
    e = b.node(104, 22, 96, 38, T['execution'])
    w = b.node(218, 24, 86, 34, T['world'])
    v = b.node(322, 24, 72, 34, T['verifier'])
    b.arrow([right(s), (left(e)[0] - 2, e[1])])
    b.arrow([right(e), (left(w)[0] - 2, w[1])])
    b.arrow([right(w), (left(v)[0] - 2, v[1])])
    b.arrow([(v[0], 24), (v[0], 10), (s[0], 10), (s[0], 26)])
    b.text(196, 8, T['outcome'])
    out.append((b, [(s[0], s[1]), (e[0], e[1]), (w[0], w[1]), (v[0], v[1]), (v[0], 10), (s[0], 10), (s[0], s[1])]))
    # L5: attribution leads to a mechanism revision that a gate commits or rejects
    b = Box(5, COLORS[5])
    s = b.node(4, 24, 72, 26, [T['system'].format(4)], 'system')
    a = b.node(92, 24, 76, 26, T['attribution'])
    r = b.node(184, 17, 80, 40, T['revision'])
    g = b.node(280, 19, 46, 36, T['gate'], 'gate')
    c = b.node(338, 2, 58, 24, T['commit'])
    k = b.node(338, 46, 58, 24, T['keep'])
    b.arrow([right(s), (left(a)[0] - 2, a[1])])
    b.arrow([right(a), (left(r)[0] - 2, r[1])])
    b.arrow([right(r), (left(g)[0] - 2, g[1])])
    b.arrow([(326, 30), (336, 14)], T['pass'], (322, 13))
    b.arrow([(326, 44), (336, 58)], T['fail'], (321, 69))
    b.parts.append(f'<path class="lv-a" d="M367,70 L367,71 L40,71 L40,52" marker-end="url(#lv-arr)"/>')
    b.text(130, 69, T['future'])
    out.append((b, [(s[0], s[1]), (a[0], a[1]), (r[0], r[1]), (g[0], g[1]), (c[0], c[1])]))
    return out


def slab(level):
    y0 = row_y(level)
    cx, cy = 262 + 13 * level, y0 + 46
    top = f'{cx},{cy - 13} {cx + 30},{cy} {cx},{cy + 13} {cx - 30},{cy}'
    rightf = f'{cx + 30},{cy} {cx},{cy + 13} {cx},{cy + 22} {cx + 30},{cy + 9}'
    leftf = f'{cx - 30},{cy} {cx},{cy + 13} {cx},{cy + 22} {cx - 30},{cy + 9}'
    return cx, cy, top, rightf, leftf


def render(lang):
    T = TEXT[lang]
    H = row_y(0) + ROW + TOP
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" class="lv-svg" '
             f'aria-label="{esc(T["title"])}">',
             '<style>'
             '.lv-svg{width:100%;height:auto;display:block}'
             '.lv-code{font:600 26px var(--halo-display);fill:var(--sl-color-white)}'
             '.lv-name{font:500 16px var(--halo-display);fill:var(--sl-color-white)}'
             '.lv-line{font:400 12px var(--sl-font)}'
             '.lv-node{fill:var(--sl-color-black);stroke-width:1.1}'
             '.lv-gate{stroke-dasharray:3 2}'
             '.lv-store{stroke-width:1.6}'
             '.lv-t{font:500 11px var(--sl-font);fill:var(--sl-color-white)}'
             '.lv-s{font:400 10px var(--sl-font);fill:var(--sl-color-gray-3)}'
             '.lv-a{fill:none;stroke:var(--sl-color-gray-3);stroke-width:1.1}'
             '.lv-bound{fill:none;stroke:var(--sl-color-gray-4);stroke-width:1;stroke-dasharray:3 3}'
             '.lv-band{stroke:none}'
             '.lv-slab-top{stroke:var(--sl-color-gray-3);stroke-width:.9}'
             '.lv-slab-side{stroke:var(--sl-color-gray-3);stroke-width:.9}'
             '</style>',
             '<defs><marker id="lv-arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" '
             'orient="auto-start-reverse"><path d="M0 0 8 4 0 8z" fill="var(--sl-color-gray-3)"/></marker>']
    for k, col in enumerate(COLORS):
        parts.append(f'<pattern id="lv-hatch-{k}" width="6" height="6" patternUnits="userSpaceOnUse" '
                     f'patternTransform="rotate(45)"><rect width="6" height="6" fill="var(--sl-color-black)"/>'
                     f'<line x1="0" y1="0" x2="0" y2="6" stroke="{col}" stroke-opacity=".35" stroke-width="2"/></pattern>')
    parts.append('</defs>')

    boxes = diagrams(T)
    climb = []
    for k in range(6):
        col, y0, t_k = COLORS[k], row_y(k), START + SLOT * k
        # the band: faint always, stronger once the level is lit
        parts.append(f'<rect class="lv-band" x="4" y="{y0}" width="{W - 8}" height="{ROW}" rx="10" fill="{col}" fill-opacity=".07"/>')
        parts.append(f'<rect x="4" y="{y0}" width="{W - 8}" height="{ROW}" rx="10" fill="{col}" fill-opacity=".16" '
                     f'stroke="{col}" stroke-opacity=".55" stroke-width="1.2" opacity="0">{light(t_k)}</rect>')
        # code, name, and one line
        parts.append(f'<text class="lv-code" x="18" y="{y0 + 36}">L{k}</text>')
        parts.append(f'<text class="lv-name" x="58" y="{y0 + 35}">{esc(T["names"][k])}</text>')
        for i, line in enumerate(T['lines'][k]):
            if line:
                parts.append(f'<text class="lv-line" x="18" y="{y0 + 58 + 15 * i}" fill="{col}">{esc(line)}</text>')
        # the step
        cx, cy, top, rf, lf = slab(k)
        parts.append(f'<polygon class="lv-slab-side" points="{rf}" fill="{col}" fill-opacity=".25"/>'
                     f'<polygon class="lv-slab-side" points="{lf}" fill="{col}" fill-opacity=".38"/>'
                     f'<polygon class="lv-slab-top" points="{top}" fill="var(--sl-color-black)"/>'
                     f'<polygon points="{top}" fill="{col}" fill-opacity=".85" opacity="0">{light(t_k)}</polygon>')
        climb.append((cx, cy - 6))
        # what the level adds
        box, flow = boxes[k]
        bx, by = BOX_X, y0 + (ROW - BOX_H) / 2
        parts.append(f'<g transform="translate({bx},{by})">'
                     f'<rect x="0" y="0" width="{BOX_W}" height="{BOX_H}" rx="8" fill="var(--sl-color-black)" '
                     f'fill-opacity=".55" stroke="{col}" stroke-opacity=".5"/>' + ''.join(box.parts))
        d = 'M' + ' L'.join(f'{x:.1f},{y:.1f}' for x, y in flow)
        parts.append(f'<path id="lv-flow-{lang}-{k}" d="{d}" fill="none" stroke="none"/>')
        a, b = (t_k + 0.15) / PERIOD, (t_k + 1.5) / PERIOD
        parts.append(f'<circle r="3.4" fill="{col}" opacity="0">'
                     f'<animateMotion dur="{PERIOD}s" repeatCount="indefinite" calcMode="linear" keyPoints="0;0;1;1" '
                     f'keyTimes="0;{a:.4f};{b:.4f};1"><mpath href="#lv-flow-{lang}-{k}"/></animateMotion>'
                     f'<animate attributeName="opacity" dur="{PERIOD}s" repeatCount="indefinite" calcMode="discrete" '
                     f'keyTimes="0;{a:.4f};{b:.4f}" values="0;1;0"/></circle></g>')

    # the climber: a small block that moves up one step whenever a level lights
    lengths = [0.0]
    for (x0, y0), (x1, y1) in zip(climb, climb[1:]):
        lengths.append(lengths[-1] + math.hypot(x1 - x0, y1 - y0))
    pts = [l / lengths[-1] for l in lengths]
    path = 'M' + ' L'.join(f'{x:.1f},{y:.1f}' for x, y in climb)
    times, points = [0.0], [0.0]
    for k in range(1, 6):
        t_k = START + SLOT * k
        times += [(t_k - 0.45) / PERIOD, t_k / PERIOD]
        points += [pts[k - 1], pts[k]]
    times += [REST / PERIOD, (REST + 0.4) / PERIOD, 1.0]
    points += [1.0, 1.0, 0.0]
    kt = ';'.join(f'{t:.4f}' for t in times)
    kp = ';'.join(f'{p:.4f}' for p in points)
    vis = pace((0, 0), (START, 0), (START + 0.2, 1), (REST, 1), (REST + 0.4, 0), (PERIOD, 0))
    parts.append(f'<path id="lv-climb-{lang}" d="{path}" fill="none" stroke="none"/>'
                 f'<g opacity="0"><polygon points="0,-9 8,-5 0,-1 -8,-5" fill="var(--sl-color-white)"/>'
                 f'<polygon points="-8,-5 0,-1 0,6 -8,2" fill="var(--sl-color-gray-2)"/>'
                 f'<polygon points="8,-5 0,-1 0,6 8,2" fill="var(--sl-color-gray-3)"/>'
                 f'<animateMotion dur="{PERIOD}s" repeatCount="indefinite" calcMode="linear" keyPoints="{kp}" '
                 f'keyTimes="{kt}"><mpath href="#lv-climb-{lang}"/></animateMotion>'
                 f'<animate attributeName="opacity" dur="{PERIOD}s" repeatCount="indefinite" calcMode="linear" '
                 f'keyTimes="{vis[0]}" values="{vis[1]}"/></g>')
    parts.append('</svg>\n')
    return ''.join(parts)


if __name__ == '__main__':
    out = Path(__file__).resolve().parents[1] / 'src' / 'assets'
    for lang in ('en', 'zh'):
        (out / f'levels-{lang}.svg').write_text(render(lang))
    print('wrote', out / 'levels-en.svg', out / 'levels-zh.svg')
