"""
Skill module: manager — self-contained skill loading, retrieval, injection.

Supports template (keyword-based), embedding, and multimodal retrieval modes.
SKILL.md format: YAML frontmatter (name/description/category) + Markdown body.

Migration notes:
  - Constructor accepts SkillConfig dataclass (primary) with optional overrides.
  - Missing skills_dir triggers a warning, not a FileNotFoundError.
  - _retrieve_template collects ALL matching task types (multi-type).
  - retrieve() returns list[Skill]; _retrieve_raw() returns list[dict].
  - retrieve_relevant() added from visualclaw-test for keyword-scored retrieval.
  - load()/reload() both update in-memory state.
  - generation property unified (self.generation attribute + get/increment methods).
"""

from __future__ import annotations

import glob
import logging
import os
import re
import threading
from dataclasses import dataclass, field as _field
from pathlib import Path
from typing import Any

from visualclaw.config import SkillConfig, VisionRetrievalConfig
from visualclaw.gateway.types import ImageMeta

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")

# ── Task-type keyword dictionaries ────────────────────────────────────────────

_CONV_TASK_TYPES: dict[str, list[str]] = {
    "coding": [
        "code", "debug", "implement", "function", "class", "bug", "error",
        "python", "java", "javascript", "typescript", "c++", "rust", "sql",
        "api", "library", "framework", "algorithm", "refactor", "test",
        "unittest", "lint", "compile", "build", "deploy", "dockerfile",
        "git", "commit", "pull request", "review",
    ],
    "research": [
        "research", "paper", "arxiv", "study", "literature", "source",
        "cite", "academic", "journal", "publication", "evidence", "survey",
        "review", "meta-analysis", "find information", "look up",
    ],
    "data_analysis": [
        "data", "dataset", "csv", "dataframe", "pandas", "sql query",
        "analytics", "metric", "dashboard", "visualize", "chart", "plot",
        "statistics", "aggregate", "pipeline", "etl", "schema", "database",
        "table", "column", "row", "query", "duckdb", "spark",
    ],
    "productivity": [
        "task", "plan", "schedule", "project", "workflow", "automate",
        "organize", "deadline", "priority", "todo", "agenda", "meeting",
        "goal", "milestone", "track progress", "manage",
    ],
    "security": [
        "security", "vulnerability", "exploit", "auth", "authentication",
        "authorization", "password", "token", "api key", "secret",
        "encrypt", "decrypt", "ssl", "tls", "injection", "xss", "csrf",
        "audit", "penetration", "threat", "permission", "access control",
    ],
    "communication": [
        "email", "message", "slack", "notify", "announcement", "draft",
        "write to", "reply", "response", "newsletter", "outreach",
        "communicate", "update", "report to", "summarize for",
    ],
    "automation": [
        "automate", "script", "cron", "scheduled", "pipeline", "batch",
        "ci/cd", "workflow", "trigger", "webhook", "bot", "scrape",
        "selenium", "playwright", "headless", "background job",
    ],
    "agentic": [
        "agent", "multi-agent", "sub-agent", "orchestrate", "spawn",
        "delegate", "autonomous", "long-running", "tool use", "mcp",
        "memory", "context window", "session", "agentic",
    ],
    "image_understanding": [
        "image", "picture", "photo", "photograph", "screenshot", "diagram",
        "figure", "illustration", "visual", "look at", "what is in",
        "describe this", "identify", "recognize", "detect", "object",
        "scene", "face", "color", "shape", "texture", "pattern",
        "logo", "icon", "thumbnail", "meme", "infographic",
    ],
    "document_ocr": [
        "ocr", "text in image", "read the", "extract text", "handwriting",
        "scan", "document", "receipt", "invoice", "form", "table in image",
        "pdf image", "scanned", "printed text", "typed text",
        "captcha", "license plate", "sign", "label",
    ],
    "visual_reasoning": [
        "chart", "graph", "plot", "bar chart", "pie chart", "line graph",
        "histogram", "scatter", "heatmap", "map", "floor plan",
        "architecture diagram", "flowchart", "uml", "sequence diagram",
        "compare images", "difference between", "spatial", "layout",
        "count", "how many", "which one", "where is",
    ],
    "image_generation": [
        "generate image", "create image", "draw", "sketch", "render",
        "design", "mockup", "wireframe", "ui design", "logo design",
        "edit image", "modify image", "resize", "crop", "filter",
        "style transfer", "inpaint", "outpaint",
    ],
    "video_understanding": [
        "video", "clip", "frame", "footage", "recording", "stream",
        "watch", "play", "timestamp", "scene change", "action",
        "summarize video", "transcribe video", "subtitle",
    ],
}


# ── Skill dataclass ───────────────────────────────────────────────────────────

@dataclass
class Skill:
    """Unified skill representation (matches SKILL.md format)."""
    name:           str
    description:    str
    content:        str
    category:       str
    keywords:       list        = _field(default_factory=list)
    generation:     int         = 0
    text_embedding: object      = _field(default=None, repr=False)
    mm_embedding:   object      = _field(default=None, repr=False)


# ── SKILL.md parser ────────────────────────────────────────────────────────────

def _parse_skill_md(path: str | Path) -> dict[str, Any] | None:
    """Parse a SKILL.md file. Returns dict or None on failure."""
    try:
        with open(str(path), encoding="utf-8") as f:
            raw = f.read()
    except OSError as exc:
        logger.warning("[SkillManager] cannot read %s: %s", path, exc)
        return None

    if not raw.startswith("---"):
        return None
    end_idx = raw.find("\n---", 3)
    if end_idx == -1:
        return None

    fm_text = raw[3:end_idx].strip()
    body = raw[end_idx + 4:].strip()

    fm: dict[str, str] = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()

    name = fm.get("name", "").strip()
    description = fm.get("description", "").strip()
    if not name or not description:
        logger.warning("[SkillManager] skipping %s — missing name or description", path)
        return None

    return {
        "name": name,
        "description": description,
        "category": fm.get("category", "general").strip(),
        "content": body,
    }


# ── Dict → Skill conversion ───────────────────────────────────────────────────

def _dict_to_skill(d: dict) -> Skill:
    return Skill(
        name=d.get("name", ""),
        description=d.get("description", ""),
        content=d.get("content", ""),
        category=d.get("category", "general"),
    )


# ── SkillManager ───────────────────────────────────────────────────────────────

class SkillManager:
    """
    Self-contained skill library: load, retrieve, inject, version-track.

    Constructor accepts either a SkillConfig dataclass (primary) with optional
    field overrides, or legacy positional arguments for backward compatibility.

    Retrieval modes:
      template   — keyword-based multi-type detection (zero latency)
      embedding  — SentenceTransformer cosine similarity
      multimodal — fuse text + image embedding (vision_retrieval.enabled)
    """

    # ── Stop words for keyword tokenisation ──────────────────────────────────

    _STOP_WORDS = frozenset({
        "the", "is", "and", "or", "of", "to", "in", "for", "on", "at",
        "by", "an", "as", "it", "be", "do", "if", "no", "not", "are",
        "was", "were", "been", "has", "have", "had", "this", "that",
        "with", "from", "will", "can", "should", "would", "could",
        "use", "when", "any", "all", "each", "every", "more", "than",
        "also", "but", "its", "does", "did", "may", "might", "into",
        "what", "how", "who", "where", "which", "why", "your", "you",
        "skill", "follow", "instead", "before", "after",
    })

    def __init__(
        self,
        skill_cfg=None,                       # SkillConfig from visualclaw.config
        vision_cfg=None,                      # VisionRetrievalConfig (optional)
        # Field overrides — take precedence over skill_cfg values when supplied:
        skills_dir: str | None = None,
        retrieval_mode: str | None = None,
        embedding_model_path: str | None = None,
        task_specific_top_k: int | None = None,
    ) -> None:
        # Preserve original config references for downstream code that reads them.
        self._skill_cfg  = skill_cfg
        self._vision_cfg = vision_cfg

        # Resolve effective values (override > cfg > built-in default).
        _skills_dir = skills_dir or (str(skill_cfg.skills_dir) if skill_cfg else "skills")
        _retrieval_mode = retrieval_mode or (skill_cfg.retrieval_mode if skill_cfg else "template")
        _task_specific_top_k = task_specific_top_k
        if _task_specific_top_k is None:
            _task_specific_top_k = getattr(skill_cfg, "task_specific_top_k", None)
        _embedding_model = (
            embedding_model_path
            or getattr(skill_cfg, "embedding_model_path", None)
            or getattr(skill_cfg, "embedding_model", "all-MiniLM-L6-v2")
        )

        if _retrieval_mode not in ("template", "embedding", "multimodal", "composite"):
            logger.warning(
                "[SkillManager] unknown retrieval_mode '%s', falling back to 'template'",
                _retrieval_mode,
            )
            _retrieval_mode = "template"

        self._skills_dir        = _skills_dir
        self.retrieval_mode     = _retrieval_mode
        self.embedding_model_path = _embedding_model
        self._task_specific_top_k = _task_specific_top_k

        # Generation counter — incremented each time new skills are added so
        # the RL trainer can discard pre-evolution samples.
        self.generation: int = 0

        self._lock               = threading.RLock()
        self._embed_model        = None
        self._embed_cache        = None            # unified cache used by embedding mode
        self._skill_embeddings_cache = None        # alias kept for visualclaw-test compat
        self._vision_embed_cache = None

        # Initialise the skill bank (gracefully handle missing directory).
        if not os.path.isdir(_skills_dir):
            logger.warning(
                "[SkillManager] skills_dir not found: %s — starting with empty skill bank",
                _skills_dir,
            )
            self.skills: dict[str, Any] = {
                "general_skills": [],
                "task_specific_skills": {},
                "common_mistakes": [],
            }
        else:
            self.skills = self._load_skills()
            n_gen = len(self.skills.get("general_skills", []))
            n_task = sum(len(v) for v in self.skills.get("task_specific_skills", {}).values())
            n_mistakes = len(self.skills.get("common_mistakes", []))
            logger.info(
                "[SkillManager] loaded %d general + %d task-specific + %d mistakes "
                "from %s | mode=%s",
                n_gen, n_task, n_mistakes, _skills_dir, _retrieval_mode,
            )

        if _retrieval_mode == "embedding" and self.skills.get("general_skills"):
            try:
                self._compute_skill_embeddings()
            except Exception as exc:
                logger.warning("[SkillManager] embedding precompute skipped: %s", exc)

    # ── Loading ──────────────────────────────────────────────────────────────

    def _load_skills(self) -> dict[str, Any]:
        """Scan skills_dir for */SKILL.md files and parse each."""
        result: dict[str, Any] = {
            "general_skills": [],
            "task_specific_skills": {},
            "common_mistakes": [],
        }
        paths = sorted(glob.glob(os.path.join(self._skills_dir, "*", "SKILL.md")))
        if not paths:
            logger.warning("[SkillManager] no SKILL.md files found in %s", self._skills_dir)
            return result

        for path in paths:
            skill = _parse_skill_md(path)
            if skill is None:
                continue
            cat = skill["category"]
            if cat == "general":
                result["general_skills"].append(skill)
            elif cat == "common_mistakes":
                result["common_mistakes"].append(skill)
            else:
                result.setdefault("task_specific_skills", {}).setdefault(cat, []).append(skill)

        return result

    def load(self) -> int:
        """Scan skills_dir for */SKILL.md files. Returns count loaded."""
        self.skills = self._load_skills()
        self._skill_embeddings_cache = None
        self._embed_cache = None
        self._vision_embed_cache = None
        count = (
            len(self.skills.get("general_skills", []))
            + sum(len(v) for v in self.skills.get("task_specific_skills", {}).values())
            + len(self.skills.get("common_mistakes", []))
        )
        # DEBUG, not INFO — __init__ already emits a more informative breakdown
        # ("N general + M task-specific + K mistakes | mode=...") on startup,
        # and SkillHandler.__init__ calls load() right after, so keeping INFO
        # here would double-log every boot.
        logger.debug("[SkillManager] loaded %d skills from %s", count, self._skills_dir)
        return count

    def reload(self) -> int:
        """Re-scan the skills directory and rebuild the skill bank. Returns count."""
        count = self.load()
        if self.retrieval_mode == "embedding":
            try:
                self._compute_skill_embeddings()
            except Exception as exc:
                logger.warning("[SkillManager] embedding recompute skipped: %s", exc)
        logger.info("[SkillManager] reloaded skills from %s", self._skills_dir)
        return count

    # ── Embedding helpers ─────────────────────────────────────────────────────

    def _get_embedding_model(self):
        if self._embed_model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise ImportError(
                    "sentence-transformers is required for embedding retrieval. "
                    "Install with: pip install sentence-transformers"
                )
            model_name = self.embedding_model_path or "all-MiniLM-L6-v2"
            logger.info("[SkillManager] loading embedding model: %s", model_name)
            self._embed_model = SentenceTransformer(model_name)
        return self._embed_model

    @staticmethod
    def _skill_to_text(skill: dict[str, Any]) -> str:
        parts = [
            skill.get("name", "").strip(),
            skill.get("description", "").strip(),
        ]
        content = skill.get("content", "").strip()
        if content:
            parts.append(content[:200])
        return ". ".join(p for p in parts if p)

    def _compute_skill_embeddings(self) -> dict:
        """Build and cache embeddings for all skills (visualclaw-test style)."""
        if self._skill_embeddings_cache is not None:
            return self._skill_embeddings_cache

        import numpy as np

        general_items = [
            ("general", None, s) for s in self.skills.get("general_skills", [])
        ]
        task_items = [
            ("task_specific", tt, s)
            for tt, skills in self.skills.get("task_specific_skills", {}).items()
            for s in skills
        ]
        all_items = general_items + task_items
        texts = [self._skill_to_text(it[2]) for it in all_items]

        model = self._get_embedding_model()
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        self._skill_embeddings_cache = {
            "items": all_items,
            "embeddings": embeddings,
            "n_general": len(general_items),
        }
        # Keep the gateway-style flat cache in sync.
        all_flat = [it[2] for it in all_items] + self.skills.get("common_mistakes", [])
        flat_texts = [self._skill_to_text(s) for s in all_flat]
        flat_embs = model.encode(
            flat_texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        ) if all_flat else embeddings
        self._embed_cache = {"skills": all_flat, "embeddings": np.array(flat_embs)}

        logger.info("[SkillManager] cached %d skill embeddings", len(all_items))
        return self._skill_embeddings_cache

    def _build_embed_cache(self) -> dict:
        """Build flat embedding cache for gateway-style retrieval."""
        try:
            import numpy as np
            all_skills = (
                self.skills.get("general_skills", [])
                + [s for cat in self.skills.get("task_specific_skills", {}).values() for s in cat]
                + self.skills.get("common_mistakes", [])
            )
            if not all_skills:
                return {}
            texts = [
                f"{s.get('name','')}. {s.get('description','')}. {s.get('content','')[:200]}"
                for s in all_skills
            ]
            embeddings = self._get_embedding_model().encode(
                texts, normalize_embeddings=True, show_progress_bar=False
            )
            return {"skills": all_skills, "embeddings": np.array(embeddings)}
        except Exception as exc:
            logger.warning("[SkillManager] embed cache build failed: %s", exc)
            return {}

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def retrieve(
        self,
        task_description: str,
        top_k: int = 6,
        images: list[ImageMeta] | None = None,
    ) -> list[Skill]:
        """Retrieve top-k skills for *task_description*. Returns list[Skill]."""
        raw = self._retrieve_raw(task_description, top_k, images=images)
        return [_dict_to_skill(s) for s in raw]

    def _retrieve_raw(
        self,
        task_description: str,
        top_k: int = 6,
        images: list[ImageMeta] | None = None,
    ) -> list[dict]:
        """Internal retrieval returning raw dicts."""
        # Use top_k from cfg if not overridden by caller's default.
        effective_top_k = top_k
        if self._skill_cfg is not None:
            effective_top_k = self._skill_cfg.top_k if top_k == 6 else top_k

        mode = self.retrieval_mode

        if mode == "embedding":
            return self._retrieve_embedding(task_description, effective_top_k)

        if mode in ("multimodal", "composite") and images:
            return self._retrieve_multimodal(task_description, images, effective_top_k)

        # Default: template (multi-type keyword matching).
        return self._retrieve_template(task_description, effective_top_k)

    def _retrieve_template(self, task_description: str, top_k: int = 6) -> list[dict]:
        """Keyword-based multi-type retrieval."""
        desc = task_description.lower()
        # Collect ALL matching task types (not just the first).
        matched_types = [
            ttype
            for ttype, keywords in _CONV_TASK_TYPES.items()
            if ttype in self.skills.get("task_specific_skills", {})
            and any(kw in desc for kw in keywords)
        ]

        general  = self.skills.get("general_skills", [])[:top_k]
        mistakes = self.skills.get("common_mistakes", [])[:5]

        task_sk: list[dict] = []
        seen_names: set[str] = set()
        for ttype in matched_types:
            for s in self.skills.get("task_specific_skills", {}).get(ttype, []):
                name = s.get("name", "")
                if name not in seen_names:
                    seen_names.add(name)
                    task_sk.append(s)

        if self._task_specific_top_k is not None:
            task_sk = task_sk[: self._task_specific_top_k]

        return general + task_sk + mistakes

    def _retrieve_embedding(self, query: str, top_k: int) -> list[dict]:
        try:
            import numpy as np

            if self._embed_model is None:
                self._get_embedding_model()
            if self._embed_cache is None:
                self._embed_cache = self._build_embed_cache()
            if not self._embed_cache:
                return self._retrieve_template(query, top_k)

            q_emb = self._embed_model.encode(
                [query], normalize_embeddings=True, show_progress_bar=False
            )[0]
            sims = self._embed_cache["embeddings"] @ q_emb
            indices = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)[:top_k]
            return [self._embed_cache["skills"][i] for i in indices]
        except Exception as exc:
            logger.warning("[SkillManager] embedding retrieval failed: %s", exc)
            return self._retrieve_template(query, top_k)

    def _retrieve_multimodal(
        self, query: str, images: list[ImageMeta], top_k: int
    ) -> list[dict]:
        """Fuse text embedding + image embeddings."""
        has_img_embs = any(img.embedding for img in images)
        if not has_img_embs:
            return self._retrieve_embedding(query, top_k)

        try:
            import numpy as np

            if self._embed_model is None:
                self._get_embedding_model()
            if self._embed_cache is None:
                self._embed_cache = self._build_embed_cache()
            if not self._embed_cache:
                return self._retrieve_template(query, top_k)

            # Fusion weights come from VisionRetrievalConfig when available.
            tw = 0.3
            iw = 0.7
            if self._vision_cfg is not None:
                tw = self._vision_cfg.fusion.text_weight
                iw = self._vision_cfg.fusion.image_weight

            t_emb = self._embed_model.encode(
                [query], normalize_embeddings=True, show_progress_bar=False
            )[0]
            img_vecs = [img.embedding for img in images if img.embedding]
            mean_img = np.mean(img_vecs, axis=0)
            mean_img = mean_img / (np.linalg.norm(mean_img) + 1e-9)

            q_emb = tw * np.array(t_emb) + iw * mean_img
            q_emb = q_emb / (np.linalg.norm(q_emb) + 1e-9)

            sims = self._embed_cache["embeddings"] @ q_emb
            indices = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)[:top_k]
            return [self._embed_cache["skills"][i] for i in indices]
        except Exception as exc:
            logger.warning("[SkillManager] multimodal retrieval failed: %s", exc)
            return self._retrieve_embedding(query, top_k)

    def retrieve_relevant(
        self,
        task_description: str,
        top_k: int = 6,
        min_relevance: float = 0.07,
    ) -> list[dict]:
        """Retrieve skills filtered by keyword relevance (overlap coefficient).

        Scans all categories — avoids missing relevant skills due to task-type
        misclassification. Skills below *min_relevance* are discarded and results
        are sorted by score descending.  Designed for synergy mode where injecting
        irrelevant skills is worse than injecting none.
        """
        all_skills: list[dict] = []
        seen_names: set[str] = set()
        for category_skills in self.skills.values():
            if isinstance(category_skills, list):
                for s in category_skills:
                    name = s.get("name", "")
                    if name not in seen_names:
                        seen_names.add(name)
                        all_skills.append(s)
            elif isinstance(category_skills, dict):
                for sub_skills in category_skills.values():
                    for s in sub_skills:
                        name = s.get("name", "")
                        if name not in seen_names:
                            seen_names.add(name)
                            all_skills.append(s)
        if not all_skills:
            return []

        task_terms = self._tokenize_text(task_description)
        if not task_terms:
            return all_skills[:top_k]

        scored: list[tuple[float, dict]] = []
        for skill in all_skills:
            # Score on name + description only to avoid false positives from
            # generic words in skill body text.
            skill_text = skill.get("name", "") + " " + skill.get("description", "")
            skill_terms = self._tokenize_text(skill_text)
            if not skill_terms:
                continue
            intersection = task_terms & skill_terms
            # Overlap coefficient: |A∩B| / min(|A|, |B|)
            relevance = len(intersection) / min(len(task_terms), len(skill_terms))
            if relevance >= min_relevance:
                scored.append((relevance, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s[1] for s in scored[:top_k]]

    # ── Formatting ────────────────────────────────────────────────────────────

    def format_for_injection(self, skills: list) -> str:
        """Format skills as '# Skills\\n\\n## {name}\\n{content}\\n\\n...'"""
        if not skills:
            return ""
        parts = ["# Skills\n"]
        for s in skills:
            if isinstance(s, dict):
                name = s.get("name", "")
                content = s.get("content", "")
            else:
                name = getattr(s, "name", "")
                content = getattr(s, "content", "")
            parts.append(f"## {name}\n{content}")
        return "\n\n".join(parts)

    def format_for_injection_compact(self, skills: list) -> str:
        """Catalogue-only injection: name + category + description, no bodies.

        Keeps per-turn prompt cost flat regardless of skill-library size.
        The full body of any entry can be fetched on demand via
        GET /v1/skill/lookup?name=<name>.
        """
        if not skills:
            return ""
        lines = [
            "# Available Skills",
            "_Call `skill_lookup(name=...)` to view full content._",
            "_When you need full instructions for a skill, make a GET request to "
            "/v1/skill/lookup?name=<skill_name>._",
            "",
        ]
        for s in skills:
            if isinstance(s, dict):
                name = s.get("name", "")
                desc = s.get("description", "")
                cat = s.get("category", "general")
            else:
                name = getattr(s, "name", "")
                desc = getattr(s, "description", "")
                cat = getattr(s, "category", "general")
            if not name:
                continue
            lines.append(f"- `{name}` [{cat}] — {desc}")
        return "\n".join(lines)

    def format_for_injection_hybrid(self, skills: list, full_top_k: int = 3) -> str:
        """Hot/cold injection: top-K skills get full bodies, the rest are catalogue.

        The LLM receives the most-relevant skills inline (directly actionable)
        plus an index of alternates.  Task-specific skills bubble up to the hot
        tier so queries like "debug this" see `debug-systematically` full-body
        rather than three cross-cutting general principles.

        Bodies aren't omitted like in compact mode; the lookup endpoint is still
        available for cold-tier entries if a caller wires it to a tool.
        """
        if not skills:
            return ""

        def _unpack(s) -> tuple[str, str, str, str]:
            if isinstance(s, dict):
                return (
                    s.get("name", ""),
                    s.get("description", ""),
                    s.get("category", "general"),
                    s.get("content", ""),
                )
            return (
                getattr(s, "name", ""),
                getattr(s, "description", ""),
                getattr(s, "category", "general"),
                getattr(s, "content", ""),
            )

        # Prefer task-specific skills (category ≠ general/common_mistakes) for
        # the hot tier — they're the ones the LLM likely needs body-level
        # instructions for on this turn.
        def _rank_key(indexed):
            i, s = indexed
            _, _, cat, _ = _unpack(s)
            is_generic = cat in ("general", "common_mistakes")
            return (1 if is_generic else 0, i)

        ordered = [s for _, s in sorted(enumerate(skills), key=_rank_key)]
        hot = ordered[:full_top_k]
        cold = ordered[full_top_k:]

        sections: list[str] = []
        if hot:
            hot_parts = ["# Skills"]
            for s in hot:
                name, _, _, content = _unpack(s)
                if not name:
                    continue
                hot_parts.append(f"## {name}\n{content}")
            sections.append("\n\n".join(hot_parts))

        if cold:
            cold_parts = [
                "# More available skills",
                "_Full content on request via GET /v1/skill/lookup?name=<skill_name>._",
            ]
            for s in cold:
                name, desc, cat, _ = _unpack(s)
                if not name:
                    continue
                cold_parts.append(f"- `{name}` [{cat}] — {desc}")
            sections.append("\n".join(cold_parts))

        return "\n\n".join(sections)

    def find_skill_by_name(self, name: str) -> dict | None:
        """Return the raw skill dict whose ``name`` matches, or None.

        Used by the /v1/skill/lookup endpoint to serve full content on demand
        after a compact-mode injection.
        """
        if not name:
            return None
        for s in self.skills.get("general_skills", []):
            if isinstance(s, dict) and s.get("name") == name:
                return s
        for cat_skills in self.skills.get("task_specific_skills", {}).values():
            for s in cat_skills:
                if isinstance(s, dict) and s.get("name") == name:
                    return s
        for s in self.skills.get("common_mistakes", []):
            if isinstance(s, dict) and s.get("name") == name:
                return s
        return None

    def format_for_conversation(self, skills: list) -> str:
        """Format skill list into a block for insertion into a system prompt."""
        if not skills:
            return ""
        lines = ["## Active Skills"]
        for skill in skills:
            if isinstance(skill, dict):
                name = skill.get("name", "")
                description = skill.get("description", "")
                content = skill.get("content", "")
            else:
                name = getattr(skill, "name", "")
                description = getattr(skill, "description", "")
                content = getattr(skill, "content", "")
            lines.append(f"\n### {name}")
            if description:
                lines.append(f"_{description}_")
            if content:
                lines.append("")
                lines.append(content)
        return "\n".join(lines)

    # ── Generation tracking ───────────────────────────────────────────────────

    def get_generation(self) -> int:
        return self.generation

    def increment_generation(self) -> None:
        with self._lock:
            self.generation += 1

    # ── Mutation ──────────────────────────────────────────────────────────────

    def add_skill(self, skill: Skill | dict, write_to_disk: bool = True) -> bool:
        """Add skill to store. Returns True if added, False if duplicate."""
        if isinstance(skill, Skill):
            d: dict = {
                "name": skill.name,
                "description": skill.description,
                "content": skill.content,
                "category": skill.category,
            }
        else:
            d = dict(skill)

        name = d.get("name", "").strip()
        if not name:
            logger.warning("[SkillManager] add_skill called with missing name")
            return False

        with self._lock:
            existing = self._get_all_names()
            if name in existing:
                logger.info("[SkillManager] skipping duplicate skill: %s", name)
                return False

            cat = d.get("category", "general").strip()
            if cat == "general":
                self.skills.setdefault("general_skills", []).append(d)
            elif cat == "common_mistakes":
                self.skills.setdefault("common_mistakes", []).append(d)
            else:
                (
                    self.skills.setdefault("task_specific_skills", {})
                    .setdefault(cat, [])
                    .append(d)
                )
            self._embed_cache = None
            self._skill_embeddings_cache = None
            self._vision_embed_cache = None

        if write_to_disk:
            self._write_skill_file(d)
        logger.info("[SkillManager] added skill: %s", name)
        return True

    def remove_skill(self, name: str, delete_file: bool = True) -> bool:
        """Remove a skill from the in-memory bank; optionally delete its SKILL.md.

        Returns True if the skill was found and removed. Used by F2 (utility-based
        pruning) in benchmark/skill_wire.py.
        """
        if not name:
            return False
        found = False
        with self._lock:
            # general_skills
            g = self.skills.get("general_skills", [])
            for i, s in enumerate(g):
                if isinstance(s, dict) and s.get("name") == name:
                    del g[i]
                    found = True
                    break
            # task_specific_skills
            if not found:
                for cat, lst in list(self.skills.get("task_specific_skills", {}).items()):
                    for i, s in enumerate(lst):
                        if isinstance(s, dict) and s.get("name") == name:
                            del lst[i]
                            found = True
                            break
                    if found:
                        break
            # common_mistakes
            if not found:
                cm = self.skills.get("common_mistakes", [])
                for i, s in enumerate(cm):
                    if isinstance(s, dict) and s.get("name") == name:
                        del cm[i]
                        found = True
                        break
            if found:
                self._embed_cache = None
                self._skill_embeddings_cache = None
                self._vision_embed_cache = None

        if found and delete_file:
            skill_dir = os.path.join(self._skills_dir, name)
            if os.path.realpath(skill_dir).startswith(
                os.path.realpath(self._skills_dir) + os.sep
            ):
                import shutil
                try:
                    shutil.rmtree(skill_dir, ignore_errors=True)
                except OSError:
                    pass
            logger.info("[SkillManager] removed skill: %s", name)
        return found

    def add_skills(self, new_skills: list[dict], category: str = "general") -> int:
        """Add multiple skills; returns count actually added.

        Increments self.generation when at least one skill is added, signalling
        the RL trainer to discard pre-evolution samples.
        """
        added = 0
        for skill in new_skills:
            if isinstance(skill, dict) and "category" not in skill:
                skill = {**skill, "category": category}
            if self.add_skill(skill):
                added += 1
        if added > 0:
            self.generation += 1
        return added

    def _write_skill_file(self, skill: dict) -> None:
        """Persist a single skill to its SKILL.md file."""
        skills_dir = self._skills_dir
        if self._skill_cfg is not None:
            skills_dir = str(Path(self._skill_cfg.skills_dir).expanduser().resolve())

        name = skill.get("name", "unknown")
        skill_dir = os.path.join(skills_dir, name)

        # Path traversal guard.
        if not os.path.realpath(skill_dir).startswith(
            os.path.realpath(skills_dir) + os.sep
        ):
            logger.warning("[SkillManager] blocked path traversal: %s", name)
            return

        os.makedirs(skill_dir, exist_ok=True)
        description = skill.get("description", "")
        category = skill.get("category", "general")
        content = skill.get("content", "")
        fm_lines = [f"name: {name}", f"description: {description}"]
        if category and category != "general":
            fm_lines.append(f"category: {category}")
        text = f"---\n{chr(10).join(fm_lines)}\n---\n\n{content}\n"
        try:
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write(text)
            logger.info("[SkillManager] wrote skill file: %s/%s", skill_dir, "SKILL.md")
        except OSError as exc:
            logger.warning("[SkillManager] cannot write skill file: %s", exc)

    # Alias for visualclaw-test compatibility.
    def _write_skill_md(self, skill: dict) -> None:
        self._write_skill_file(skill)

    def save(self, path: str | None = None) -> None:
        """Persist all in-memory skills to SKILL.md files.

        *path* is ignored — always writes to skills_dir (kept for compat).
        """
        all_skills = (
            self.skills.get("general_skills", [])
            + [s for cat in self.skills.get("task_specific_skills", {}).values() for s in cat]
            + self.skills.get("common_mistakes", [])
        )
        for skill in all_skills:
            self._write_skill_file(skill)
        logger.info("[SkillManager] saved %d skills to %s", len(all_skills), self._skills_dir)

    def _get_all_names(self) -> set[str]:
        names: set[str] = set()
        for s in self.skills.get("general_skills", []):
            if s.get("name"):
                names.add(s["name"])
        for cat_skills in self.skills.get("task_specific_skills", {}).values():
            for s in cat_skills:
                if s.get("name"):
                    names.add(s["name"])
        for s in self.skills.get("common_mistakes", []):
            if s.get("name"):
                names.add(s["name"])
        return names

    # Alias for visualclaw-test compatibility.
    def _get_all_skill_names(self) -> set[str]:
        return self._get_all_names()

    def get_skill_count(self) -> dict:
        return {
            "general": len(self.skills.get("general_skills", [])),
            "task_specific": sum(
                len(v) for v in self.skills.get("task_specific_skills", {}).values()
            ),
            "common_mistakes": len(self.skills.get("common_mistakes", [])),
        }

    # ── Text tokenisation helpers (from visualclaw-test) ────────────────────────

    @staticmethod
    def _stem(word: str) -> str:
        """Lightweight suffix stripping (not a full stemmer)."""
        for suffix in (
            "ation", "tion", "sion", "ment", "ness", "ious",
            "ical", "ally", "ible", "able", "ting", "ing",
            "ful", "ous", "ive", "ity", "ise", "ize",
            "ies", "ily", "ely", "ure", "ant", "ent",
            "ist", "ism", "ory", "ary",
            "ly", "ed", "er", "es",
        ):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                return word[: -len(suffix)]
        return word

    @staticmethod
    def _tokenize_text(text: str) -> set[str]:
        """Split text into meaningful keyword tokens.

        - Splits on non-alphanumeric characters.
        - Filters stop words and short tokens (< 3 chars).
        - Applies lightweight stemming for better matching.
        """
        raw = re.findall(r"[a-zA-Z0-9]+", text.lower())
        tokens: set[str] = set()
        for tok in raw:
            if len(tok) >= 3 and tok not in SkillManager._STOP_WORDS:
                stemmed = SkillManager._stem(tok)
                if len(stemmed) >= 3:
                    tokens.add(stemmed)
                else:
                    tokens.add(tok)
        return tokens
