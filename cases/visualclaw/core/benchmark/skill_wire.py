"""
Skill evolution wiring for video benchmarks.

Bridges the benchmark evaluation loop with VisualClaw's skill evolution
system.  After each evaluation round, failed samples are fed to SkillEvolver
which generates new skills via Bedrock/OpenAI, then injects them into
subsequent rounds.

Usage::

    wire = SkillWire(skills_dir="memory_data/skills", use_bedrock=True)
    # ... run benchmark rounds ...
    evolved = await wire.evolve_on_failures(failures)
    system_prompt = wire.get_system_prompt(task_description)
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from visualclaw.env import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _env(name: str, fallback: str | None = None) -> str | None:
    """Read a VisualClawArena env var with legacy MM_ARENA fallback."""
    return os.environ.get(name) or (os.environ.get(fallback) if fallback else None)


@dataclass
class BenchmarkSample:
    """Lightweight sample for skill evolution (mimics ConversationSample)."""
    prompt_text: str = ""
    response_text: str = ""
    reward: float = 0.0
    images: list = field(default_factory=list)
    image_descriptions: list = field(default_factory=list)


class SkillWire:
    """Wires skill evolution into benchmark evaluation loops.

    Parameters
    ----------
    skills_dir: Directory for skill storage (SKILL.md files).
    use_bedrock: Use AWS Bedrock for evolution LLM. If False, uses OpenAI.
    bedrock_model: Bedrock model ID for evolution.
    bedrock_region: AWS region for Bedrock.
    evolution_threshold: Evolve when success rate < threshold.
    max_new_skills: Max skills per evolution round.
    history_path: JSONL file for evolution history.
    """

    def __init__(
        self,
        skills_dir: str = "memory_data/skills",
        use_bedrock: bool = True,
        evolver_backend: str | None = None,
        bedrock_model: str = "us.anthropic.claude-sonnet-4-6",
        bedrock_region: str | None = None,
        claude_effort: str | None = None,
        claude_cli_path: str | None = None,
        evolution_threshold: float = 0.4,
        max_new_skills: int = 3,
        history_path: Optional[str] = None,
        governance=None,
        injection_mode: str = "full",
        hybrid_top_k: int = 3,
        utility_prune: bool = False,
        utility_prune_every: int = 100,
        utility_min_activations: int = 5,
        utility_prune_margin: float = 0.05,
    ):
        from visualclaw.modules.skill.manager import SkillManager
        from visualclaw.modules.skill.evolver import SkillEvolver

        if injection_mode not in ("full", "compact", "hybrid"):
            raise ValueError(
                f"injection_mode must be 'full', 'compact', or 'hybrid'; got {injection_mode!r}"
            )

        # Resolve Bedrock region: explicit arg → BEDROCK_REGION env → us-east-1.
        if bedrock_region is None:
            bedrock_region = os.environ.get("BEDROCK_REGION", "us-east-1")

        self.skills_dir = skills_dir
        self.threshold = evolution_threshold
        self.injection_mode = injection_mode
        self.hybrid_top_k = hybrid_top_k
        # F2: per-skill utility tracking + pruning
        self.utility_prune = utility_prune
        self.utility_prune_every = utility_prune_every
        self.utility_min_activations = utility_min_activations
        self.utility_prune_margin = utility_prune_margin
        self._util: dict[str, dict[str, int]] = {}   # name → {activations, correct}
        self._util_by_task: dict[str, dict[str, dict[str, int]]] = {}  # name → task_type → {a, c}
        self._last_injected: list[str] = []           # populated by get_system_prompt
        self._questions_since_prune = 0

        # Initialize skill manager
        # (v3 SkillManager doesn't accept governance kwarg; SkillWire keeps it
        #  on its own signature for back-compat but drops it here.)
        self.manager = SkillManager(
            skills_dir=skills_dir,
            retrieval_mode="template",
        )

        backend = (
            evolver_backend
            or _env("VISUALCLAW_ARENA_EVOLVER_BACKEND", "MM_ARENA_EVOLVER_BACKEND")
            or ""
            or ("bedrock" if use_bedrock else "openai")
        ).strip().lower()
        if backend == "claude":
            backend = "claude-code"
        if backend not in {"bedrock", "openai", "claude-code"}:
            raise ValueError(
                "evolver_backend must be one of bedrock, openai, claude-code; "
                f"got {evolver_backend!r}"
            )

        # Auto-promote to Bedrock when no explicit backend was requested and the
        # model is an Anthropic inference-profile ID. Without this, callers who
        # pass --evolver-model us.anthropic.* but forget USE_BEDROCK=1 silently
        # degrade to "no skills generated".
        if (
            not evolver_backend
            and not _env("VISUALCLAW_ARENA_EVOLVER_BACKEND", "MM_ARENA_EVOLVER_BACKEND")
            and backend == "openai"
            and bedrock_model.startswith(("us.anthropic.", "anthropic."))
        ):
            logger.info(
                "[SkillWire] auto-enabling Bedrock for Anthropic model id %s "
                "(USE_BEDROCK=1 was not set; promoting based on model id)",
                bedrock_model,
            )
            backend = "bedrock"

        # Initialize evolver with LLM client
        llm_client = None
        if backend == "bedrock":
            from visualclaw.bedrock_client import BedrockChatClient
            api_key = os.environ.get("BEDROCK_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "[SkillWire] Bedrock requested but BEDROCK_API_KEY is unset. "
                    "Set BEDROCK_API_KEY or pass use_bedrock=False with an "
                    "OPENAI_API_KEY fallback. Refusing to silently disable evolution."
                )
            llm_client = BedrockChatClient(
                model_id=bedrock_model,
                region=bedrock_region,
                api_key=api_key,
                governance=governance,
            )
            logger.info("[SkillWire] using Bedrock (%s, region=%s) for evolution",
                        bedrock_model, bedrock_region)
        elif backend == "claude-code":
            from visualclaw.claude_code_client import ClaudeCodeChatClient
            llm_client = ClaudeCodeChatClient(
                model=bedrock_model,
                effort=claude_effort or _env(
                    "VISUALCLAW_ARENA_CLAUDE_EVOLVER_EFFORT",
                    "MM_ARENA_CLAUDE_EVOLVER_EFFORT",
                ),
                cli_path=claude_cli_path,
                timeout=float(
                    _env(
                        "VISUALCLAW_ARENA_CLAUDE_EVOLVER_TIMEOUT",
                        "MM_ARENA_CLAUDE_EVOLVER_TIMEOUT",
                    )
                    or "240"
                ),
            )
            logger.info(
                "[SkillWire] using Claude Code (%s, effort=%s) for evolution",
                bedrock_model,
                llm_client.effort or "(default)",
            )
        elif not os.environ.get("OPENAI_API_KEY"):
            logger.warning(
                "[SkillWire] No OPENAI_API_KEY set and Bedrock disabled. "
                "Skill evolution will be skipped."
            )

        self.evolver = SkillEvolver(
            manager=self.manager,
            max_new_skills=max_new_skills,
            llm_client=llm_client,
            history_path=history_path or str(
                Path(skills_dir) / "benchmark_evolution_history.jsonl"
            ),
        )

        # Track stats
        self.total_evolved = 0
        self.evolution_rounds = 0
        self.all_evolved_names: list[str] = []

    def get_system_prompt(self, task_description: str = "", qa_type: str = "",
                          task_type: str = "") -> str:
        """Get current skill-augmented system prompt.

        Parameters
        ----------
        task_description: Description of the current task for skill retrieval.
        qa_type: Filter to only skills tagged for this QA type (via qa_types.json
            sidecar in skills_dir). Empty string disables filtering.
        task_type: Optional bench-specific task category (e.g., V-MME's
            "Action Reasoning"). If a ``task_types.json`` sidecar exists,
            skills whose task_types list excludes this task_type are dropped
            before injection (Idea-1 per-task-type routing).
        """
        skills = self.manager.retrieve(task_description)
        if not skills:
            return ""

        if qa_type:
            tags = self._load_qa_types()
            if tags:
                # Keep skills whose tags include qa_type, OR skills with no tag
                # (untagged skills are universally applicable).
                filtered = []
                for s in skills:
                    name = s.get("name", "") if isinstance(s, dict) else getattr(s, "name", "")
                    skill_tags = tags.get(name)
                    if skill_tags is None or qa_type in skill_tags:
                        filtered.append(s)
                skills = filtered

        if task_type:
            skills = self._filter_by_task_type(skills, task_type)

        if not skills:
            self._last_injected = []
            return ""
        # F2: remember which skills were active on this question so record_result
        # can credit/blame them.
        self._last_injected = [
            (s.get("name", "") if isinstance(s, dict) else getattr(s, "name", ""))
            for s in skills
        ]
        return self._render_skills(skills)

    def _render_skills(self, skills: list) -> str:
        if not skills:
            return ""
        if self.injection_mode == "compact":
            return self.manager.format_for_injection_compact(skills)
        if self.injection_mode == "hybrid":
            return self.manager.format_for_injection_hybrid(skills, full_top_k=self.hybrid_top_k)
        return self.manager.format_for_conversation(skills)

    def get_system_prompt_with_fallbacks(
        self, task_description: str = "", qa_type: str = "",
        task_type: str = "",
    ) -> tuple[str, list[str]]:
        """Return (primary_prompt, fallback_ladder).

        Fallback ladder is a list of progressively-degraded system prompts
        for use on Azure content_filter / jailbreak 400 blocks. Each
        successive ladder entry drops one more skill from the head of the
        retrieval ranking (most-relevant first; assumption being that a
        flagged prompt is most likely flagged because of the top-ranked
        skill body in the hybrid hot tier). Final entry is empty string.
        """
        # Replicate retrieval + filter from get_system_prompt to keep both paths
        # in sync. We can't just call get_system_prompt because we need the
        # underlying skills list for the ladder.
        skills = self.manager.retrieve(task_description)
        if not skills:
            self._last_injected = []
            return "", []
        if qa_type:
            tags = self._load_qa_types()
            if tags:
                filtered = []
                for s in skills:
                    name = s.get("name", "") if isinstance(s, dict) else getattr(s, "name", "")
                    skill_tags = tags.get(name)
                    if skill_tags is None or qa_type in skill_tags:
                        filtered.append(s)
                skills = filtered
        if task_type:
            skills = self._filter_by_task_type(skills, task_type)
        if not skills:
            self._last_injected = []
            return "", []
        self._last_injected = [
            (s.get("name", "") if isinstance(s, dict) else getattr(s, "name", ""))
            for s in skills
        ]
        primary = self._render_skills(skills)
        # Build ladder: drop top-1, drop top-2, ..., empty.
        ladder: list[str] = []
        for k in range(1, len(skills) + 1):
            remaining = skills[k:]
            ladder.append(self._render_skills(remaining) if remaining else "")
        return primary, ladder

    # ── F2: per-skill utility tracking ───────────────────────────────────────

    def record_result(self, correct: bool, task_type: str = "") -> None:
        """Credit/blame the last-injected skills with the question outcome.

        Call this after each question's correctness is scored. Maintains:
          - aggregate per-skill {activations, correct} (used by F2 prune)
          - per-skill per-task-type {activations, correct} (used by Idea-1
            per-task-type routing). The task_type is the bench's per-question
            category (e.g., V-MME's "Action Reasoning") and is opt-in: callers
            that don't pass it just feed the aggregate counters.
        """
        if not self._last_injected:
            return
        for name in self._last_injected:
            if not name:
                continue
            stats = self._util.setdefault(name, {"activations": 0, "correct": 0})
            stats["activations"] += 1
            if correct:
                stats["correct"] += 1
            if task_type:
                tt_map = self._util_by_task.setdefault(name, {})
                tt_stats = tt_map.setdefault(task_type, {"activations": 0, "correct": 0})
                tt_stats["activations"] += 1
                if correct:
                    tt_stats["correct"] += 1
        self._last_injected = []
        if self.utility_prune:
            self._questions_since_prune += 1
            if self._questions_since_prune >= self.utility_prune_every:
                self._prune_low_utility_skills()
                self._persist_utility()  # snapshot stats every prune window
                self._questions_since_prune = 0
        elif self._util and len(self._util) % 25 == 0:
            # Even without pruning, persist periodic snapshots so post-hoc
            # analysis has the per-skill stats regardless of prune setting.
            self._persist_utility()

    def _prune_low_utility_skills(self) -> int:
        """Drop skills whose accuracy lags the bank mean by ``margin``.

        Criteria: activations ≥ ``utility_min_activations`` AND
        accuracy < (bank-mean − ``utility_prune_margin``). Seed skills are
        eligible for pruning too — this is a performance signal, not a
        provenance signal. Returns the number of skills removed.
        """
        if not self._util:
            return 0
        eligible = [
            (n, s) for n, s in self._util.items()
            if s["activations"] >= self.utility_min_activations
        ]
        if not eligible:
            return 0
        total_act = sum(s["activations"] for _, s in eligible)
        total_cor = sum(s["correct"] for _, s in eligible)
        if total_act == 0:
            return 0
        bank_mean = total_cor / total_act
        floor = bank_mean - self.utility_prune_margin
        losers = [
            n for n, s in eligible
            if (s["correct"] / s["activations"]) < floor
        ]
        removed = 0
        for name in losers:
            if self.manager.remove_skill(name, delete_file=True):
                removed += 1
                # Persist tombstone so subsequent evolver rounds won't re-add
                self._util.pop(name, None)
        if removed:
            logger.info(
                "[SkillWire] F2 pruned %d low-utility skills (bank_mean=%.2f, floor=%.2f): %s",
                removed, bank_mean, floor, losers,
            )
            self._persist_utility()
        return removed

    def _persist_utility(self) -> None:
        """Dump skill utility stats to <skills_dir>/skill_utility.jsonl."""
        import json as _json
        path = Path(self.skills_dir) / "skill_utility.jsonl"
        try:
            with path.open("w") as f:
                for name, stats in sorted(self._util.items()):
                    rec = {
                        "name": name,
                        "activations": stats["activations"],
                        "correct": stats["correct"],
                        "accuracy": stats["correct"] / stats["activations"] if stats["activations"] else 0.0,
                    }
                    f.write(_json.dumps(rec) + "\n")
        except OSError:
            pass
        # Also persist per-task breakdown alongside aggregate stats
        if self._util_by_task:
            try:
                tt_path = Path(self.skills_dir) / "skill_utility_by_task.json"
                tt_path.write_text(_json.dumps(self._util_by_task, indent=2))
            except OSError:
                pass

    def _load_task_types(self) -> dict[str, list[str]]:
        """Load the task_types.json sidecar mapping skill_name -> allowed task types.

        Use Idea-1 to filter retrieved skills: only inject a skill on a question
        whose task_type is in the skill's allowed list. Skills without an entry
        in the file fall through (treated as universal — opt-in mechanism).
        """
        import json as _json
        path = Path(self.skills_dir) / "task_types.json"
        if not path.exists():
            return {}
        try:
            return _json.loads(path.read_text())
        except Exception:
            return {}

    def _filter_by_task_type(self, skills: list, task_type: str) -> list:
        """Drop skills whose task_types.json entry excludes the current task_type.
        Untagged skills (no entry) pass through unchanged.
        """
        if not task_type:
            return skills
        tags = self._load_task_types()
        if not tags:
            return skills
        out = []
        for s in skills:
            name = s.get("name", "") if isinstance(s, dict) else getattr(s, "name", "")
            allowed = tags.get(name)
            if allowed is None or task_type in allowed or "all" in allowed:
                out.append(s)
        return out

    def _load_qa_types(self) -> dict[str, list[str]]:
        """Load the qa_types.json sidecar mapping skill name → list of QA types."""
        import json as _json
        path = Path(self.skills_dir) / "qa_types.json"
        if not path.exists():
            return {}
        try:
            return _json.loads(path.read_text())
        except Exception:
            return {}

    def _save_qa_types(self, name_to_types: dict[str, list[str]]) -> None:
        """Persist the qa_types.json sidecar (merge with existing)."""
        import json as _json
        path = Path(self.skills_dir) / "qa_types.json"
        existing = self._load_qa_types()
        existing.update(name_to_types)
        try:
            path.write_text(_json.dumps(existing, indent=2))
        except OSError:
            pass

    def tag_recently_evolved(self, skill_names: list[str], qa_types: list[str]) -> None:
        """Fallback batch-level tag — only writes if the evolver did NOT write
        per-skill tags itself. The evolver (modules/skill/evolver.py) now writes
        per-skill qa_types directly to the sidecar based on its own JSON output;
        this batch-level helper is kept for back-compat and only fills in skills
        the evolver omitted.
        """
        if not skill_names or not qa_types:
            return
        existing = self._load_qa_types()
        # Only add tags for skills the evolver didn't already tag
        new_tags = {n: list(qa_types) for n in skill_names if n not in existing}
        if new_tags:
            self._save_qa_types(new_tags)

    async def evolve_on_failures(
        self,
        failures: list[BenchmarkSample],
        force: bool = False,
        memory_context: str = "",
        memory_context_position: str = "before_instructions",
        memory_context_title: str | None = None,
        memory_context_intro: str | None = None,
    ) -> list[dict]:
        """Run skill evolution on failed samples.

        Parameters
        ----------
        failures: List of BenchmarkSample objects with reward <= 0.
        force: Force evolution even if success rate is above threshold.
        memory_context: Optional context from memory to inform evolution.
            Default behavior injects successful-pattern context before the
            instruction section, preserving the original v3.1 fusion path.
        memory_context_position: Where to inject memory_context in the evolver
            prompt. "before_instructions" preserves the original behavior;
            "prefix" inserts it before the failed-conversation block.

        Returns
        -------
        List of newly created skill dicts.
        """
        if not failures:
            return []

        # Check if we should evolve
        if not force and not self.evolver.should_evolve(failures, self.threshold):
            logger.info("[SkillWire] success rate above threshold, skipping evolution")
            return []

        # Get current skill bank
        current_skills = {
            "general_skills": self.manager.skills.get("general_skills", []),
            "task_specific_skills": self.manager.skills.get("task_specific_skills", {}),
            "common_mistakes": self.manager.skills.get("common_mistakes", []),
        }

        # If memory context is provided, temporarily patch the evolver's
        # prompt builder to include successful patterns.
        _orig_builder = self.evolver._build_analysis_prompt_full
        if memory_context:
            def _patched_builder(failed_samples, cur_skills, next_idx):
                prompt, images = _orig_builder(failed_samples, cur_skills, next_idx)
                title = memory_context_title or "Successful Patterns from Memory"
                intro = memory_context_intro or (
                    "The following are patterns from questions the assistant answered "
                    "CORRECTLY. Use these as positive examples — generated skills should "
                    "reinforce these patterns while also fixing the failures above."
                )
                memory_section = (
                    "\n\n---\n"
                    f"## {title}\n\n"
                    f"{intro}\n\n"
                    f"{memory_context}\n"
                )
                anchor = (
                    "## Failed Conversations"
                    if memory_context_position == "prefix"
                    else "## Instructions"
                )
                insert_at = prompt.find(anchor)
                if insert_at > 0:
                    prompt = prompt[:insert_at] + memory_section + "\n" + prompt[insert_at:]
                else:
                    prompt += memory_section
                return prompt, images
            self.evolver._build_analysis_prompt_full = _patched_builder

        try:
            new_skills = await self.evolver.evolve(failures, current_skills)
        except Exception as e:
            logger.error("[SkillWire] evolution failed: %s", e)
            return []
        finally:
            self.evolver._build_analysis_prompt_full = _orig_builder

        if new_skills:
            names = [
                (s.get("name", "?") if isinstance(s, dict) else str(s))
                for s in new_skills
            ]
            self.total_evolved += len(new_skills)
            self.evolution_rounds += 1
            self.all_evolved_names.extend(names)
            logger.info(
                "[SkillWire] evolved %d new skills (memory-informed=%s): %s",
                len(new_skills), bool(memory_context), names,
            )

        return new_skills

    def make_failure_sample(
        self,
        question: str,
        response: str,
        correct_answer: str = "",
        image_descriptions: Optional[list[str]] = None,
        has_video: bool = False,
    ) -> BenchmarkSample:
        """Create a BenchmarkSample from a failed evaluation.

        Parameters
        ----------
        question: The question that was asked.
        response: The model's incorrect response.
        correct_answer: The expected answer (for feedback).
        image_descriptions: Descriptions of images/frames shown.
        has_video: Whether video frames were involved.
        """
        prompt = question
        if correct_answer:
            prompt += f"\n\n[Expected answer: {correct_answer}]"

        descs = image_descriptions or []
        if has_video and not descs:
            descs = ["[video frames from egocentric recording]"]

        return BenchmarkSample(
            prompt_text=prompt,
            response_text=response,
            reward=-1.0,
            images=["<frame>"] * len(descs) if descs else [],
            image_descriptions=descs,
        )

    @property
    def stats(self) -> dict:
        return {
            "evolution_rounds": self.evolution_rounds,
            "total_skills_evolved": self.total_evolved,
            "all_evolved_names": self.all_evolved_names,
            "current_skill_count": len(self.manager.skills.get("general_skills", [])) + sum(
                len(v) for v in self.manager.skills.get("task_specific_skills", {}).values()
            ),
        }
