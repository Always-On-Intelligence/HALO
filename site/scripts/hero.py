"""Draw the landing-page illustration: the loop's three modules on a plate, with HALO's ring above them.

The drawing is animated with SMIL, which also runs inside an <img>: a step travels S->M, M->A, then A->S,
each channel's label lights up once a step has crossed it, the step is logged up to the ring, and a bead
for each logged event gathers on the ring. Then the cycle starts again.

    python3 scripts/hero.py        writes src/assets/hero-light.svg and src/assets/hero-dark.svg
"""
import math
from pathlib import Path

C, S = math.cos(math.radians(30)), math.sin(math.radians(30))
U = 24.0  # pixels per unit


def iso(x, y, z=0.0):
    return ((x - y) * C * U, (x + y) * S * U - z * U)


def poly(points, cls):
    return f'<polygon class="{cls}" points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in points)}"/>'


def line(points, cls, extra=''):
    d = 'M' + ' L'.join(f'{x:.1f},{y:.1f}' for x, y in points)
    return f'<path class="{cls}" d="{d}"{extra}/>'


def cuboid(x, y, w, d, h, label):
    """Faces of a box whose footprint starts at (x, y), visible from the front."""
    top = [iso(x, y, h), iso(x + w, y, h), iso(x + w, y + d, h), iso(x, y + d, h)]
    right = [iso(x + w, y, 0), iso(x + w, y + d, 0), iso(x + w, y + d, h), iso(x + w, y, h)]
    left = [iso(x, y + d, 0), iso(x + w, y + d, 0), iso(x + w, y + d, h), iso(x, y + d, h)]
    cx, cy = iso(x + w / 2, y + d / 2, h)
    # text lying on the top face: x axis along (C, S), y axis along (-C, S)
    text = (f'<text class="label" transform="matrix({C:.4f},{S:.4f},{-C:.4f},{S:.4f},{cx:.1f},{cy:.1f})" '
            f'x="0" y="7" text-anchor="middle">{label}</text>')
    return [poly(right, 'side'), poly(left, 'front'), poly(top, 'top'), text]


def arrow(a, b, z=0.02, inset=0.0):
    (x0, y0), (x1, y1) = a, b
    p0, p1 = iso(x0, y0, z), iso(x1, y1, z)
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    head = [(p1[0] - 7 * math.cos(ang - 0.45), p1[1] - 7 * math.sin(ang - 0.45)), p1,
            (p1[0] - 7 * math.cos(ang + 0.45), p1[1] - 7 * math.sin(ang + 0.45))]
    return [line([p0, p1], 'flow'), line(head, 'flow')]


def ellipse(cx, cy, z, r, cls, n=96):
    pts = [iso(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n), z) for k in range(n + 1)]
    return line(pts, cls)


PERIOD = 10.0  # seconds per cycle


def pace(*points):
    """keyTimes and values for a property that holds each value from the given second until the next one."""
    times, values = [], []
    for t, v in points:
        times.append(f'{t / PERIOD:.4f}')
        values.append(str(v))
    return ';'.join(times), ';'.join(values)


def fade(start, end=9.2, shown=1):
    """Opacity 0 until `start`, `shown` until `end`, then 0 again, on the shared cycle."""
    kt, vals = pace((0, 0), (start, 0), (start + 0.25, shown), (end, shown), (end + 0.5, 0), (PERIOD, 0))
    return (f'<animate attributeName="opacity" dur="{PERIOD}s" repeatCount="indefinite" calcMode="linear" '
            f'keyTimes="{kt}" values="{vals}"/>')


def travel(path_id, start, length):
    """A dot that moves along a path from `start` for `length` seconds and is hidden otherwise."""
    a, b = start / PERIOD, (start + length) / PERIOD
    return (f'<circle class="packet" r="3.4" opacity="0">'
            f'<animateMotion dur="{PERIOD}s" repeatCount="indefinite" calcMode="linear" '
            f'keyPoints="0;0;1;1" keyTimes="0;{a:.4f};{b:.4f};1"><mpath href="#{path_id}"/></animateMotion>'
            f'<animate attributeName="opacity" dur="{PERIOD}s" repeatCount="indefinite" calcMode="discrete" '
            f'keyTimes="0;{a:.4f};{b:.4f}" values="0;1;0"/></circle>')


def scene():
    out = []
    n = 12
    # plate: top, two sides, and a grid of short pegs like the reference illustrations
    out += [poly([iso(n, 0, 0), iso(n, n, 0), iso(n, n, -0.6), iso(n, 0, -0.6)], 'side'),
            poly([iso(0, n, 0), iso(n, n, 0), iso(n, n, -0.6), iso(0, n, -0.6)], 'front'),
            poly([iso(0, 0, 0), iso(n, 0, 0), iso(n, n, 0), iso(0, n, 0)], 'top')]
    for i in range(1, n):
        out.append(line([iso(i, 0.3), iso(i, n - 0.3)], 'grid'))
        out.append(line([iso(0.3, i), iso(n - 0.3, i)], 'grid'))
    blocks = {'M': (2.0, 2.0), 'S': (2.0, 7.4), 'A': (7.4, 2.0)}
    w = 2.6
    centers = {k: (x + w / 2, y + w / 2) for k, (x, y) in blocks.items()}
    # flows on the plate between the modules, drawn before the blocks
    def edge(a, b, off=1.55):
        (ax, ay), (bx, by) = centers[a], centers[b]
        dx, dy = bx - ax, by - ay
        dist = math.hypot(dx, dy)
        ux, uy = dx / dist, dy / dist
        return (ax + ux * off, ay + uy * off), (bx - ux * off, by - uy * off)
    for a, b in (('S', 'M'), ('M', 'A'), ('S', 'A')):
        out += arrow(*edge(a, b))
    # A->S: Action guiding what Sensing checks, drawn as an arc in front of the loop
    (ax, ay), (sx, sy) = centers['A'], centers['S']
    arc = [iso(*pt) for pt in [((1 - t) ** 2 * (ax + 0.35) + 2 * (1 - t) * t * 9.4 + t ** 2 * (sx + 1.55),
                                 (1 - t) ** 2 * (ay + 1.55) + 2 * (1 - t) * t * 9.4 + t ** 2 * (sy + 0.35))
                                for t in [k / 24 for k in range(25)]]]
    out.append(line(arc, 'flow back', ' id="ch-as"'))
    end, before = arc[-1], arc[-3]
    ang = math.atan2(end[1] - before[1], end[0] - before[0])
    out.append(line([(end[0] - 7 * math.cos(ang - 0.45), end[1] - 7 * math.sin(ang - 0.45)), end,
                     (end[0] - 7 * math.cos(ang + 0.45), end[1] - 7 * math.sin(ang + 0.45))], 'flow back'))
    # invisible copies of the forward edges for the moving steps to follow
    for a, b, pid in (('S', 'M', 'ch-sm'), ('M', 'A', 'ch-ma')):
        p0, p1 = edge(a, b)
        out.append(line([iso(*p0, 0.02), iso(*p1, 0.02)], 'track', f' id="{pid}"'))
    ring_c = tuple(sum(c[i] for c in centers.values()) / 3 for i in (0, 1))   # over the middle of the loop
    # dashed sight lines from the ring down to each module
    for k, (cx, cy) in centers.items():
        out.append(line([iso(cx, cy, 8.2), iso(cx, cy, 1.9)], 'sight'))
    for k in ('M', 'S', 'A'):
        x, y = blocks[k]
        out += cuboid(x, y, w, w, 1.7, k)
    # the halo: a ring floating above the loop
    out.append(ellipse(*ring_c, 8.2, 4.6, 'ring'))
    out.append(ellipse(*ring_c, 8.45, 4.6, 'ring2'))

    # animation: three steps cross three channels, each is logged up to the ring
    steps = [('ch-sm', 0.4, 'M', 'S→M'), ('ch-ma', 2.6, 'A', 'M→A'), ('ch-as', 4.8, 'S', 'A→S')]
    beads = [112, 72, 32]
    rx, ry = iso(ring_c[0] + 4.6 * math.cos(math.radians(-45)), ring_c[1] + 4.6 * math.sin(math.radians(-45)), 8.2)
    lx, ly = rx + 26, ry - 34
    for k, (pid, t0, dest, name) in enumerate(steps):
        length = 1.0 if pid != 'ch-as' else 1.3
        out.append(travel(pid, t0, length))
        arrive = t0 + length
        # the channel list beside the ring: grey until a step has crossed the channel, then solid
        y = ly + 22 * k
        out.append(f'<circle class="todo" cx="{lx:.1f}" cy="{y - 4:.1f}" r="4"/>'
                   f'<text class="chan dim" x="{lx + 12:.1f}" y="{y:.1f}">{name}</text>')
        out.append(f'<g opacity="0"><circle class="done" cx="{lx:.1f}" cy="{y - 4:.1f}" r="4"/>'
                   f'<text class="chan" x="{lx + 12:.1f}" y="{y:.1f}">{name}</text>{fade(arrive)}</g>')
        # logged: a dot rises from the module to the ring
        cx, cy = centers[dest]
        bottom, top = iso(cx, cy, 1.9), iso(cx, cy, 8.2)
        out.append(line([bottom, top], 'track', f' id="up-{k}"'))
        out.append(travel(f'up-{k}', arrive, 0.6))
        # the ring keeps a bead for each logged event
        a = math.radians(beads[k])
        bx, by = iso(ring_c[0] + 4.6 * math.cos(a), ring_c[1] + 4.6 * math.sin(a), 8.2)
        out.append(f'<circle class="bead" cx="{bx:.1f}" cy="{by:.1f}" r="4" opacity="0">{fade(arrive + 0.6)}</circle>')
    # the ring brightens once the three steps are in the trace, as a report would
    out.append(f'<g opacity="0">{ellipse(*ring_c, 8.2, 4.6, "ring-on")}{fade(7.4, shown=0.9)}</g>')
    return out


def render(theme):
    ink, top, side, front, grid, faint = ({'light': ('#1c1c1c', '#ffffff', '#efefef', '#e2e2e2', '#d9d9d9', '#8a8a8a'),
                                           'dark': ('#e8e8e8', '#151515', '#1f1f1f', '#292929', '#333333', '#7a7a7a')}[theme])
    body = scene()
    style = (f'.top{{fill:{top};stroke:{ink};stroke-width:1.1;stroke-linejoin:round}}'
             f'.side{{fill:{side};stroke:{ink};stroke-width:1.1;stroke-linejoin:round}}'
             f'.front{{fill:{front};stroke:{ink};stroke-width:1.1;stroke-linejoin:round}}'
             f'.grid{{fill:none;stroke:{grid};stroke-width:0.8}}'
             f'.flow{{fill:none;stroke:{ink};stroke-width:1.2;stroke-linecap:round;stroke-linejoin:round}}'
             f'.sight{{fill:none;stroke:{faint};stroke-width:0.9;stroke-dasharray:3 4}}'
             f'.ring{{fill:none;stroke:{ink};stroke-width:1.6}}'
             f'.ring2{{fill:none;stroke:{faint};stroke-width:0.8}}'
             f'.ring-on{{fill:none;stroke:{ink};stroke-width:3}}'
             f'.back{{stroke:{faint};stroke-dasharray:4 4}}'
             f'.track{{fill:none;stroke:none}}'
             f'.packet{{fill:{ink}}}'
             f'.bead{{fill:{top};stroke:{ink};stroke-width:1.6}}'
             f'.chan{{fill:{ink};font:600 12px ui-monospace,"Geist Mono",Menlo,monospace}}'
             f'.chan.dim{{fill:{faint};font-weight:500}}'
             f'.todo{{fill:none;stroke:{faint};stroke-width:1.2}}'
             f'.done{{fill:{ink};stroke:{ink};stroke-width:1.2}}'
             f'.label{{fill:{ink};font:600 22px "Geist Mono",ui-monospace,Menlo,monospace}}')
    xs, ys = zip(*(iso(x, y, z) for x in (0, 12) for y in (0, 12) for z in (-0.6, 10.2)))
    pad = 12
    x0, y0, x1, y1 = min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.0f} {y0:.0f} {x1 - x0:.0f} {y1 - y0:.0f}" '
            f'width="{x1 - x0:.0f}" height="{y1 - y0:.0f}" role="img" aria-label="Sensing, Memory, and Action on a plate, with a ring above them">'
            f'<style>{style}</style>' + ''.join(body) + '</svg>\n')


if __name__ == '__main__':
    out = Path(__file__).resolve().parents[1] / 'src' / 'assets'
    for theme in ('light', 'dark'):
        (out / f'hero-{theme}.svg').write_text(render(theme))
    print('wrote', out / 'hero-light.svg', out / 'hero-dark.svg')
