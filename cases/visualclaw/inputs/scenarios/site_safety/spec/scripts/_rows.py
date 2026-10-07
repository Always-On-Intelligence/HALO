"""Shared executable check for row-style JSON deliverables (VisualClawArena exec_check style).

A deliverable is a JSON list of objects (a dict holding one such list is also accepted). Each expected
row is matched by its name field, and every expected key must hold the expected value. Prints PASS or
the reasons for FAIL; the exit code is 0 on PASS and 1 otherwise.
"""
import json
import re
import sys
from pathlib import Path


def _norm(text):
    text = str(text).lower().replace("µ", "u").replace("μ", "u")
    return re.sub(r"[^a-z0-9]+", "", text)


def _rows(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        if len(lists) == 1:
            return lists[0]
    return None


def _same(value, expected):
    if isinstance(expected, bool):
        if isinstance(value, bool):
            return value == expected
        return str(value).strip().lower() == str(expected).lower()
    if isinstance(expected, int):
        try:
            return float(value) == expected
        except (TypeError, ValueError):
            return False
    if isinstance(expected, list):
        got = [_norm(x) for x in (value if isinstance(value, list) else [value])]
        return len(got) == len(expected) and all(any(_norm(e) in g for g in got) for e in expected)
    return _norm(value) == _norm(expected)


def check(workspace, relpath, name_key, expected, cite_key=None, exact_rows=False):
    path = Path(workspace) / relpath
    if not path.exists():
        print(f"FAIL: {relpath} was not written")
        return 1
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {relpath} is not valid JSON ({exc})")
        return 1
    rows = _rows(data)
    if rows is None:
        print(f"FAIL: {relpath} must be a JSON list of objects")
        return 1
    problems = []
    for exp in expected:
        want = _norm(exp[name_key])
        match = [r for r in rows if isinstance(r, dict) and r.get(name_key) is not None
                 and (_norm(r[name_key]) == want or want in _norm(r[name_key]) or _norm(r[name_key]) in want)]
        if not match:
            problems.append(f"no row for {exp[name_key]!r}")
            continue
        row = match[0]
        for key, value in exp.items():
            if key == name_key:
                continue
            if key not in row:
                problems.append(f"{exp[name_key]}: missing key {key!r}")
            elif not _same(row[key], value):
                problems.append(f"{exp[name_key]}: {key}={row[key]!r}, expected {value!r}")
        if cite_key and "[clip @" not in str(row.get(cite_key, "")):
            problems.append(f"{exp[name_key]}: {cite_key} lacks a [clip @ MM:SS] citation")
    if exact_rows and len(rows) != len(expected):
        problems.append(f"expected {len(expected)} rows, found {len(rows)}")
    if problems:
        print("FAIL: " + "; ".join(problems))
        return 1
    print("PASS")
    return 0


def main(relpath, name_key, expected, cite_key=None, exact_rows=False):
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    sys.exit(check(workspace, relpath, name_key, expected, cite_key, exact_rows))
