"""
Skill Evolver: analyze failed samples and generate new skills via LLM.

VisualClaw adaptation:
  - Constructor accepts SkillConfig dataclass (primary) with optional direct kwargs.
  - Missing LLM configuration logs a warning instead of raising (gateway must start).
  - _call_llm returns empty string when no client is configured.
  - FailedSample dataclass extended with prompt_text/response_text aliases.
  - Prompt construction and name-management logic from visualclaw-test.
  - Gateway-specific notification (_notify_rl) and vision support preserved.

Environment variables:
    OPENAI_API_KEY        — API key for the LLM provider
    OPENAI_BASE_URL       — custom API base URL (default: https://api.openai.com/v1)
    SKILL_EVOLVER_MODEL   — model name (fallback when skill_cfg.evolution.llm_model empty)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from visualclaw.config import SkillConfig
from visualclaw.env import load_dotenv
from visualclaw.gateway.types import ImageMeta

load_dotenv()

logger = logging.getLogger(__name__)

# Slug validation: lowercase letters, digits, hyphens, starting with a letter.
_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,}$")
# Pattern for auto-assigned dynamic names: dyn-NNN.
_DYN_RE = re.compile(r"^dyn-(\d+)$")

_DEFAULT_CATEGORIES = [
    "coding", "research", "data_analysis", "security",
    "communication", "automation", "agentic",
    "image_understanding", "document_ocr", "visual_reasoning",
    "image_generation", "video_understanding",
]


# ── FailedSample dataclass ────────────────────────────────────────────────────

@dataclass
class FailedSample:
    """A failed turn used to drive skill evolution.

    Supports both gateway-style (prompt/response + images) and
    visualclaw-test style (prompt_text/response_text) field names.
    """
    prompt:         str                   = ""
    response:       str                   = ""
    images:         list[ImageMeta] | None = None
    image_descs:    list[str] | None       = None
    prompt_text:    str                   = ""   # alias for prompt
    response_text:  str                   = ""   # alias for response
    reward:         float                 = 0.0

    def __post_init__(self) -> None:
        # Ensure both naming conventions stay in sync.
        if not self.prompt_text:
            self.prompt_text = self.prompt
        elif not self.prompt:
            self.prompt = self.prompt_text
        if not self.response_text:
            self.response_text = self.response
        elif not self.response:
            self.response = self.response_text


# ── SkillEvolver ──────────────────────────────────────────────────────────────

class SkillEvolver:
    """
    Analyze failed conversation samples and generate new skills via an LLM.

    Generated skills follow Claude skill format:
    ``{"name": str, "description": str, "content": str, "category": str}``

    Parameters
    ----------
    skill_cfg:
        SkillConfig dataclass — used for evolution settings and history path.
    manager:
        SkillManager reference for add_skills / get_generation / etc.
    gateway_base_url:
        Gateway base URL for RL notification (unused, kept for compat).
    max_new_skills:
        Override for skill_cfg.evolution.max_new_skills_per_run.
    llm_model:
        Override for skill_cfg.evolution.llm_model.
    llm_client:
        Optional drop-in LLM client (must implement chat_complete(prompt) -> str).
    history_path:
        Override for skill_cfg.evolution_history_path.
    """

    def __init__(
        self,
        skill_cfg=None,                  # SkillConfig — evolution settings
        manager=None,                    # SkillManager reference
        gateway_base_url: str = "http://127.0.0.1:30100",
        # Direct kwargs (override cfg):
        max_new_skills: int | None = None,
        llm_model: str | None = None,
        llm_client=None,
        history_path: str | None = None,
    ) -> None:
        self._cfg         = skill_cfg
        self._manager     = manager
        self._gateway_url = gateway_base_url

        _evo_cfg = getattr(skill_cfg, "evolution", None) if skill_cfg else None

        self.max_new_skills = max_new_skills or getattr(
            _evo_cfg, "max_new_skills_per_run", 3
        )
        _model = (
            llm_model
            or getattr(_evo_cfg, "llm_model", "")
            or os.environ.get("SKILL_EVOLVER_MODEL", "")
        )
        self.max_completion_tokens = 3000
        self.history_path = history_path or (
            str(getattr(skill_cfg, "evolution_history_path", "")) if skill_cfg else None
        )
        self.update_history: list[dict] = []

        if llm_client is not None:
            self._custom_client = llm_client
            self._openai_client = None
            self._openai_model  = None
        else:
            self._custom_client = None
            api_key  = os.environ.get("OPENAI_API_KEY", "")
            base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            if api_key and _model:
                try:
                    from openai import OpenAI
                    self._openai_client = OpenAI(api_key=api_key, base_url=base_url)
                    self._openai_model  = _model
                except ImportError:
                    logger.warning(
                        "[SkillEvolver] openai package not installed; evolution disabled"
                    )
                    self._openai_client = None
                    self._openai_model  = None
            else:
                logger.warning(
                    "[SkillEvolver] no LLM configured (need OPENAI_API_KEY + model); "
                    "evolution disabled"
                )
                self._openai_client = None
                self._openai_model  = None

    # ── Public interface ──────────────────────────────────────────────────────

    def should_evolve(self, batch_or_rate, threshold: float | None = None) -> bool:
        """Return True if evolution should run.

        Accepts either a success rate (float) or a list of samples (batch).
        When a batch is provided the success rate is computed as in visualclaw-test.
        """
        cfg_threshold = (
            self._cfg.evolution.success_rate_threshold
            if (self._cfg and self._cfg.evolution)
            else 0.4
        )
        _threshold = threshold if threshold is not None else cfg_threshold

        if isinstance(batch_or_rate, (int, float)):
            return batch_or_rate < _threshold

        # batch (list of samples)
        batch = batch_or_rate
        if not batch:
            return False
        successes = sum(1 for s in batch if getattr(s, "reward", 0) > 0)
        rate = successes / len(batch)
        logger.info(
            "[SkillEvolver] success_rate=%.2f threshold=%.2f evolve=%s",
            rate, _threshold, rate < _threshold,
        )
        return rate < _threshold

    async def evolve(
        self,
        failed_samples: list,
        current_skills: dict[str, Any] | None = None,
    ) -> list[str]:
        """Run a full evolution step.  Returns list of new skill names.

        Accepts either visualclaw-test style (failed_samples, current_skills dict)
        or gateway style (failed_samples only, uses manager.skills internally).
        """
        if not failed_samples:
            return []

        # Resolve the skill bank dict.
        if current_skills is None:
            current_skills = self._manager.skills if self._manager else {
                "general_skills": [], "task_specific_skills": {}, "common_mistakes": []
            }

        next_dyn_idx = self._next_dyn_index(current_skills)
        prompt, image_urls = self._build_analysis_prompt_full(
            failed_samples, current_skills, next_dyn_idx
        )

        try:
            if image_urls:
                response_text = await self._call_llm_async(prompt, image_urls)
            else:
                response_text = await asyncio.to_thread(self._call_llm, prompt)

            if not response_text:
                return []

            raw_skills = self._parse_skills_response(response_text)
            skills = self._finalise_names(raw_skills, next_dyn_idx)
            skills = skills[: self.max_new_skills]

            added: list[str] = []
            qa_types_map: dict[str, list[str]] = {}

            # F1: flatten existing skills once for semantic-dedup comparisons.
            # Rebuilt on each evolve() call since add_skill mutates the bank.
            _existing_flat = (
                current_skills.get("general_skills", [])
                + [s for cat in current_skills.get("task_specific_skills", {}).values() for s in cat]
                + current_skills.get("common_mistakes", [])
            )

            for d in skills:
                if not isinstance(d, dict) or not d.get("name"):
                    continue
                # F1: reject name-duplicate skills via token Jaccard. Stops the
                # bank-bloat failure mode observed on V-MME (64 skills with 7
                # near-duplicate counting-exhaustive variants).
                if (
                    (
                        os.environ.get("VISUALCLAW_ARENA_DISABLE_SKILL_HYGIENE")
                        or os.environ.get("MM_ARENA_DISABLE_SKILL_HYGIENE")
                    )
                    != "1"
                    and self._is_semantic_duplicate(d, _existing_flat, threshold=0.5)
                ):
                    continue
                if self._manager is not None:
                    from visualclaw.modules.skill.manager import Skill
                    skill_obj = Skill(
                        name=d.get("name", ""),
                        description=d.get("description", ""),
                        content=d.get("content", ""),
                        category=d.get("category", "general"),
                        generation=self._manager.get_generation() + 1,
                    )
                    if self._manager.add_skill(skill_obj, write_to_disk=True):
                        added.append(skill_obj.name)
                        _existing_flat.append(d)  # subsequent dedup checks include it
                        # Capture per-skill qa_types for sidecar persistence
                        qt = d.get("qa_types")
                        if isinstance(qt, list) and qt:
                            qa_types_map[skill_obj.name] = [str(t) for t in qt]

            # Persist per-skill qa_types to <skills_dir>/qa_types.json sidecar
            if qa_types_map and self._manager is not None:
                try:
                    from pathlib import Path as _P
                    import json as _json
                    skills_dir = _P(self._manager._skills_dir)
                    sidecar = skills_dir / "qa_types.json"
                    existing: dict = {}
                    if sidecar.exists():
                        try:
                            existing = _json.loads(sidecar.read_text())
                        except Exception:
                            existing = {}
                    existing.update(qa_types_map)
                    sidecar.write_text(_json.dumps(existing, indent=2))
                    logger.info(
                        "[SkillEvolver] persisted qa_types for %d skills → %s",
                        len(qa_types_map), sidecar,
                    )
                except Exception as exc:
                    logger.warning("[SkillEvolver] qa_types sidecar write failed: %s", exc)

            # Build history record.
            record = {
                "timestamp":              datetime.now().isoformat(timespec="seconds"),
                "num_failures_analyzed":  len(failed_samples),
                "num_skills_generated":   len(added),
                "skill_names":            added,
                "skills": [
                    {
                        "name":        d.get("name"),
                        "category":    d.get("category", "general"),
                        "description": d.get("description", ""),
                        "content":     d.get("content", ""),
                    }
                    for d in skills
                ],
                "failure_prompts": [
                    getattr(s, "prompt_text", getattr(s, "prompt", ""))[-300:]
                    for s in failed_samples[:6]
                ],
            }
            self.update_history.append(record)
            if self.history_path:
                self._append_history(record)

            if added and self._manager is not None:
                self._manager.increment_generation()
                asyncio.create_task(self._notify_rl())

            logger.info(
                "[SkillEvolver] generated %d new skills from %d failures: %s",
                len(added), len(failed_samples), added,
            )
            return added

        except Exception as exc:
            logger.error("[SkillEvolver] evolution failed: %s", exc, exc_info=True)
            return []

    def get_update_summary(self) -> dict:
        if not self.update_history:
            return {"total_updates": 0, "total_skills_generated": 0}
        return {
            "total_updates":        len(self.update_history),
            "total_skills_generated": sum(
                h["num_skills_generated"] for h in self.update_history
            ),
            "all_skill_names": [
                n for h in self.update_history for n in h.get("skill_names", [])
            ],
        }

    # ── LLM calls ─────────────────────────────────────────────────────────────

    def _call_llm(self, prompt: str) -> str:
        """Synchronous LLM call (text-only)."""
        if self._custom_client is not None:
            return self._custom_client.chat_complete(prompt)
        if self._openai_client is None:
            logger.warning("[SkillEvolver] no LLM client configured; skipping evolution")
            return "[]"
        response = self._openai_client.chat.completions.create(
            model=self._openai_model,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=self.max_completion_tokens,
        )
        return response.choices[0].message.content

    async def _call_llm_async(self, prompt: str, image_urls: list[str]) -> str:
        """Async LLM call with optional image attachments (gateway-style httpx)."""
        model   = (self._openai_model or "")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        api_base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

        if not api_key:
            logger.warning("[SkillEvolver] OPENAI_API_KEY not set — evolution skipped")
            return ""

        content: list[dict] = []
        for url in image_urls[:8]:
            content.append({"type": "image_url", "image_url": {"url": url, "detail": "low"}})
        content.append({"type": "text", "text": prompt})

        body: dict = {
            "model":                  model,
            "messages":               [{"role": "user", "content": content if image_urls else prompt}],
            "max_completion_tokens":  3000,
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{api_base.rstrip('/')}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code != 200:
                    logger.warning("[SkillEvolver] LLM returned %d", resp.status_code)
                    return ""
                return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as exc:
            logger.warning("[SkillEvolver] async LLM call failed: %s", exc)
            return ""

    # ── Prompt construction ───────────────────────────────────────────────────

    def _build_analysis_prompt_full(
        self,
        failed_samples: list,
        current_skills: dict[str, Any],
        next_dyn_idx: int,
    ) -> tuple[str, list[str]]:
        """Build analysis prompt and collect image URLs from failed samples."""
        failure_blocks: list[str] = []
        image_urls: list[str] = []
        has_vision = False

        for i, sample in enumerate(failed_samples[:6]):
            prompt_text   = getattr(sample, "prompt_text", "") or getattr(sample, "prompt", "")
            response_text = getattr(sample, "response_text", "") or getattr(sample, "response", "")
            reward        = getattr(sample, "reward", 0.0)

            images = getattr(sample, "images", None) or []
            if images:
                has_vision = True
                for img in images[:2]:
                    if getattr(img, "url", None) and len(image_urls) < 8:
                        image_urls.append(img.url)
                img_note = f"\n**Images ({len(images)}):** "
                img_descs = getattr(sample, "image_descs", None)
                if img_descs:
                    img_note += "; ".join(img_descs[:3])
                else:
                    img_note += "[attached above]"
            else:
                img_note = ""

            failure_blocks.append(
                f"### Failure {i + 1}  (reward={reward:.1f})\n"
                f"**Conversation context (last 600 chars):**\n"
                f"```\n...{prompt_text[-600:]}\n```\n"
                f"{img_note}\n"
                f"**Assistant response (first 500 chars):**\n"
                f"```\n{response_text[:500]}{'...' if len(response_text) > 500 else ''}\n```"
            )

        # Existing skill names to avoid duplication.
        existing: list[str] = []
        for s in current_skills.get("general_skills", []):
            existing.append(s.get("name", ""))
        for tt, skills in current_skills.get("task_specific_skills", {}).items():
            for s in skills:
                existing.append(f"[{tt}] {s.get('name', '')}")
        for s in current_skills.get("common_mistakes", []):
            existing.append(f"[mistake] {s.get('name', '')}")

        available_cats = list(
            current_skills.get("task_specific_skills", {}).keys()
        ) or _DEFAULT_CATEGORIES

        example_name = f"dyn-{next_dyn_idx:03d}"

        vision_guidance = ""
        if has_vision:
            vision_guidance = (
                "\n**Vision failures detected:** Generate skills with appropriate vision "
                "categories (image_understanding, document_ocr, visual_reasoning, "
                "video_understanding).\n\n"
            )

        prompt = (
            "You are a skill engineer for an AI assistant trained with RL.\n"
            "Your job: analyze the failed conversations below and generate NEW skills "
            "that would have prevented those failures.\n\n"
            "---\n"
            "## Failed Conversations\n\n"
            + "\n\n".join(failure_blocks)
            + "\n\n---\n"
            "## Existing Skills (do NOT duplicate any of these)\n\n"
            + json.dumps(existing, indent=2)
            + "\n\n---\n"
            + vision_guidance
            + "## Instructions\n\n"
            f"Generate **1 to {self.max_new_skills}** new skills that directly address "
            "the failure patterns observed above. Focus on actionable, concrete guidance "
            "that the assistant can follow in future conversations.\n\n"
            "Each skill must follow **Claude skill format**:\n"
            "- `name`: a lowercase hyphenated slug (e.g. `handle-partial-input`). "
            f"Use `{example_name}` only if you can't find a descriptive name.\n"
            "- `description`: one sentence — when to trigger this skill and what it achieves.\n"
            "- `content`: 6–15 lines of actionable Markdown. Include: "
            "a heading, numbered steps or bullet points, a concrete example or code snippet "
            "if relevant, and an **Anti-pattern** section.\n"
            f"- `category`: one of {available_cats} or `\"general\"` or `\"common_mistakes\"`.\n"
            "- `qa_types` (optional): list of question formats this skill applies to. "
            "Inspect each failure's `[QA type: ...]` prefix above; tag each generated skill "
            "ONLY with the type(s) whose failure patterns it addresses. Common values: "
            "`[\"mc_single\"]` (single-letter MC), `[\"mc_multi\"]` (multi-letter MC), "
            "`[\"binary\"]` (Yes/No), `[\"open_ended\"]` (free-text). Omit or use "
            "`[\"all\"]` only if the skill genuinely applies to every format.\n\n"
            "**Output:** Return ONLY a valid JSON array. "
            "No markdown code fences, no prose outside the JSON.\n\n"
            "**Example output:**\n"
            "[\n"
            "  {\n"
            f'    "name": "{example_name}",\n'
            '    "description": "Use when the user provides a path that may not exist. '
            'Always verify file existence before reading or writing.",\n'
            '    "content": "## Verify File Existence Before Acting\\n\\n'
            "1. Check that the path exists: `os.path.exists(path)`\\n"
            "2. If it doesn't exist, tell the user and ask for the correct path.\\n"
            "3. Never assume a path is valid just because the user mentioned it.\\n\\n"
            '**Anti-pattern:** Calling `open(path)` without checking existence first.",\n'
            '    "category": "coding",\n'
            '    "qa_types": ["mc_single"]\n'
            "  }\n"
            "]"
        )
        return prompt, image_urls

    # Kept for direct usage as per visualclaw-test style.
    def _build_analysis_prompt(
        self,
        failed_samples: list,
        current_skills: dict[str, Any],
        next_dyn_idx: int,
    ) -> str:
        prompt, _ = self._build_analysis_prompt_full(failed_samples, current_skills, next_dyn_idx)
        return prompt

    # ── Response parsing ──────────────────────────────────────────────────────

    # ── F1: token-overlap deduplication ───────────────────────────────────────

    @staticmethod
    def _tokenize_name(name: str) -> set[str]:
        """Skill-name tokens: split on '-' and '_' after lowercasing."""
        return {t for t in re.split(r"[-_]+", name.lower().strip()) if t}

    _NAME_STOPWORDS = frozenset({
        "video", "mc", "and", "with", "for", "the", "of", "in", "to", "a",
    })

    @classmethod
    def _name_jaccard(cls, a: str, b: str) -> float:
        """Jaccard overlap on name tokens (after dropping common stopwords)."""
        ta = cls._tokenize_name(a) - cls._NAME_STOPWORDS
        tb = cls._tokenize_name(b) - cls._NAME_STOPWORDS
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        union = len(ta | tb)
        return inter / union if union else 0.0

    def _is_semantic_duplicate(
        self, new_skill, existing: list, threshold: float = 0.5,
    ) -> bool:
        """Reject if the new skill's name has Jaccard ≥ threshold against any existing.

        Token-based (no ML model): splits on ``-`` and ``_``, drops noise tokens
        (``video``, ``mc``, prepositions) before computing overlap. Tuned to catch
        the observed name-drift failure mode where the evolver emits 5–7 variants
        of the same concept (e.g., ``video-counting-exhaustive-verification`` vs
        ``video-counting-with-exhaustive-enumeration`` = 3/4 stopword-stripped
        Jaccard = 0.75, well above the 0.5 threshold).
        """
        if not existing:
            return False
        new_name = (
            new_skill.get("name", "") if isinstance(new_skill, dict)
            else getattr(new_skill, "name", "")
        )
        if not new_name:
            return False
        for s in existing:
            existing_name = (
                s.get("name", "") if isinstance(s, dict) else getattr(s, "name", "")
            )
            if not existing_name:
                continue
            j = self._name_jaccard(new_name, existing_name)
            if j >= threshold:
                logger.info(
                    "[SkillEvolver] rejecting token-duplicate skill %r (jaccard=%.2f to %r)",
                    new_name, j, existing_name,
                )
                return True
        return False

    def _parse_skills_response(self, response: str) -> list[dict]:
        """Extract and validate JSON skill array from LLM response."""
        skills: list | None = None
        # Direct parse.
        try:
            result = json.loads(response)
            if isinstance(result, list):
                skills = result
        except (json.JSONDecodeError, ValueError):
            pass

        if skills is None:
            # Strip markdown code fences.
            clean = re.sub(r"```(?:json)?\s*", "", response).strip()

            j_start = clean.find("[")
            j_end   = clean.rfind("]") + 1
            if j_start == -1 or j_end <= j_start:
                logger.warning("[SkillEvolver] no JSON array found in response:\n%s", response[:400])
                return []

            try:
                skills = json.loads(clean[j_start:j_end])
            except json.JSONDecodeError as exc:
                logger.warning(
                    "[SkillEvolver] JSON parse error: %s\nResponse excerpt: %s",
                    exc, clean[j_start: j_start + 500],
                )
                return []

        valid = []
        for s in skills:
            missing = [k for k in ("name", "description", "content") if not s.get(k)]
            if missing:
                logger.warning(
                    "[SkillEvolver] skipping skill — missing fields %s: %s",
                    missing, str(s)[:200],
                )
                continue
            name = str(s.get("name", "")).strip()
            if (
                (
                    os.environ.get("VISUALCLAW_ARENA_DISABLE_SKILL_HYGIENE")
                    or os.environ.get("MM_ARENA_DISABLE_SKILL_HYGIENE")
                )
                != "1"
                and _DYN_RE.match(name)
            ):
                logger.warning(
                    "[SkillEvolver] rejecting dyn-* placeholder skill (evolver attention dilution): %s",
                    name,
                )
                continue
            content = str(s.get("content", ""))
            # Reject episodic/one-shot skills that reference specific failure
            # indices ("Failure 3", "Failure 5") — these don't generalize.
            if (
                (
                    os.environ.get("VISUALCLAW_ARENA_DISABLE_SKILL_HYGIENE")
                    or os.environ.get("MM_ARENA_DISABLE_SKILL_HYGIENE")
                )
                != "1"
                and re.search(r"\bFailure\s+\d+\b", content)
            ):
                logger.warning(
                    "[SkillEvolver] rejecting episodic skill referencing 'Failure N': %s",
                    name,
                )
                continue
            valid.append(s)
        return valid

    # ── Name / slug management ────────────────────────────────────────────────

    def _next_dyn_index(self, current_skills: dict[str, Any]) -> int:
        """Return the next available dyn-NNN index across the skill bank."""
        max_idx = 0
        for skill in current_skills.get("general_skills", []):
            m = _DYN_RE.match(skill.get("name", ""))
            if m:
                max_idx = max(max_idx, int(m.group(1)))
        for skills in current_skills.get("task_specific_skills", {}).values():
            for skill in skills:
                m = _DYN_RE.match(skill.get("name", ""))
                if m:
                    max_idx = max(max_idx, int(m.group(1)))
        return max_idx + 1

    def _finalise_names(self, skills: list[dict], start_idx: int) -> list[dict]:
        """Ensure every skill has a valid slug name.

        - Keeps valid lowercase-hyphenated slugs from the LLM.
        - Assigns dyn-NNN to invalid or duplicate names.
        """
        seen: set[str] = set()
        result = []
        dyn_counter = start_idx

        for skill in skills:
            updated = dict(skill)
            name = skill.get("name", "").strip().lower()

            if _SLUG_RE.match(name) and name not in seen:
                pass  # keep as-is
            else:
                name = f"dyn-{dyn_counter:03d}"
                dyn_counter += 1

            seen.add(name)
            updated["name"] = name

            cat = skill.get("category", "general")
            if not isinstance(cat, str) or not cat.strip():
                cat = "general"
            updated["category"] = cat.strip()

            result.append(updated)
        return result

    # ── History persistence ───────────────────────────────────────────────────

    def _append_history(self, record: dict) -> None:
        hp = self.history_path
        if not hp:
            return
        path = Path(hp).expanduser().resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("[SkillEvolver] could not write history: %s", exc)

    # ── Gateway notification ──────────────────────────────────────────────────

    async def _notify_rl(self) -> None:
        gen = self._manager.get_generation() if self._manager else 0
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"{self._gateway_url}/v1/rl/internal/skill_gen",
                    json={"skill_generation": gen},
                )
        except Exception as exc:
            logger.debug("[SkillEvolver] RL notify failed: %s", exc)
