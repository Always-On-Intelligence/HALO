"""Abstract base for agent engines.

Forked structurally from ClawArena `src/clawarena/engines/base.py`. The
contract is the same: an engine knows how to invoke one agent backend with
a message + a staged workspace, then return what happened. The runner is
responsible for staging the workspace, extracting keyframes, and scoring
the post-agent workspace state — engines never touch scoring.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentResult:
    status: str                       # "success" | "failed" | "timeout"
    answer: str                       # concatenation of all TextBlocks from the agent
    error: str | None = None
    returncode: int | None = None
    raw: Any = None                   # backend-specific final message (for debugging)
    transcript: list[dict] = field(default_factory=list)  # serialized turn-by-turn log


class AgentEngine(ABC):
    """Invoke one agent backend over a workspace; return what the agent said."""

    name: str = ""

    @abstractmethod
    async def run_agent(
        self,
        *,
        message: str,
        workspace: Path,
        session_id: str | None = None,
        timeout: float | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> AgentResult:
        """Run the agent once. Workspace is the dir the agent will treat as cwd.
        The agent may freely read/write inside `workspace`; the runner inspects
        post-agent workspace state via check scripts."""
