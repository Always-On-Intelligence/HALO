"""Small dotenv loader for VisualClaw auth/config environment.

The project intentionally avoids a runtime dependency on ``python-dotenv``.
This parser supports the simple, portable subset used by ``.env.example``:

    KEY=value
    export KEY=value
    KEY="value with spaces"

Existing process environment values win unless ``override=True`` is passed.
Lines are parsed as data and never evaluated as shell code.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_dotenv(path: str | os.PathLike[str] | None = None, *, override: bool = False) -> Path | None:
    """Load a VisualClaw ``.env`` file into ``os.environ``.

    Resolution order:
    1. explicit ``path`` argument
    2. ``VISUALCLAW_ENV_FILE`` environment variable
    3. ``.env`` in the current working directory

    Returns the loaded path, or ``None`` when no file exists.
    """

    env_path = Path(
        path
        or os.environ.get("VISUALCLAW_ENV_FILE", "")
        or Path.cwd() / ".env"
    ).expanduser()
    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not _KEY_RE.match(key):
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = _strip_quotes(value)

    return env_path
