"""Model backends. Each backend runs one prompt and returns the final text.

Backends are selected by name, e.g. ``codex:gpt-6-astra`` or ``claude:claude-opus-5-5``.
Paths to local CLIs come from environment variables so nothing machine-specific is
hard-coded: HALO_CODEX_BIN and HALO_CLAUDE_BIN.
"""
from .cli import run_prompt, BackendError  # noqa: F401
