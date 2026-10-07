"""
Unified configuration for VisualClaw.

Single configuration dataclass:

  VisualClawConfig is the compatibility-named nested dataclass used by the
    gateway and modules.
    Load with load_config(); supports four-level priority merge.

"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# ${VAR} placeholder expansion
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")


def expand_env_placeholders(obj: Any) -> Any:
    """Recursively expand ``${VAR}`` in all string values of *obj*.

    Supports arbitrarily nested dicts and lists (as produced by YAML / JSON
    loaders).  If the referenced environment variable is **not** set the
    placeholder is left unchanged — this avoids silent data loss and makes
    missing variables easy to spot at runtime.

    Examples::

        os.environ["API_KEY"] = "secret"
        expand_env_placeholders({"key": "${API_KEY}"})
        # → {"key": "secret"}

        expand_env_placeholders({"key": "${MISSING_VAR}"})
        # → {"key": "${MISSING_VAR}"}
    """
    if isinstance(obj, dict):
        return {k: expand_env_placeholders(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_env_placeholders(item) for item in obj]
    if isinstance(obj, str):
        return _PLACEHOLDER_RE.sub(
            lambda m: os.environ.get(m.group(1), m.group(0)), obj
        )
    return obj


# ── Sub-section dataclasses ─────────────────────────────────────────────────

@dataclass
class DaemonConfig:
    config_dir:  str = "~/.visualclaw"
    pid_path:    str = "~/.visualclaw/visualclaw.pid"
    log_path:    str = "~/.visualclaw/visualclaw.log"
    config_path: str = "~/.visualclaw/config.yaml"


@dataclass
class GatewayConfig:
    host:                str = "0.0.0.0"
    port:                int = 30100
    enabled_modules:     list[str] = field(default_factory=list)
    request_timeout_sec: int = 30
    session_store_dir:   str = "~/.visualclaw/sessions"


@dataclass
class ProviderEntry:
    api_base: str = ""
    api_key:  str = ""


@dataclass
class BedrockEntry:
    region:     str = "us-east-1"
    access_key: str = ""
    secret_key: str = ""


@dataclass
class OpenRouterEntry:
    api_base:        str            = "https://openrouter.ai/api/v1"
    api_key:         str            = ""
    route:           str            = ""
    fallback_models: list[str]      = field(default_factory=list)
    data_policy:     str            = ""
    app_name:        str            = "VisualClaw"
    app_url:         str            = ""


@dataclass
class ProvidersConfig:
    openai:     ProviderEntry   = field(default_factory=ProviderEntry)
    anthropic:  ProviderEntry   = field(default_factory=ProviderEntry)
    bedrock:    BedrockEntry    = field(default_factory=BedrockEntry)
    openrouter: OpenRouterEntry = field(default_factory=OpenRouterEntry)


@dataclass
class ProxyConfig:
    streaming:                  bool = True
    session_id_header:          str  = "X-Session-Id"
    agent_type_header:          str  = "X-Agent-Type"
    turn_type_header:           str  = "X-Turn-Type"
    session_done_header:        str  = "X-Session-Done"
    context_window:             int  = 32768
    openclaw_config_path:       str  = "~/.openclaw/openclaw.json"
    openclaw_prompt_cache_path: str  = "records/system_prompt_cache.json"
    openclaw_env_data_dir:      str  = "records/env_rollout"
    providers:                  ProvidersConfig = field(default_factory=ProvidersConfig)


@dataclass
class AgentAdaptersConfig:
    copaw_config_path:    str = "~/.copaw/config.json"
    ironclaw_env_path:    str = "~/.ironclaw/.env"
    picoclaw_config_path: str = "~/.picoclaw/config.json"
    zeroclaw_config_path: str = "~/.zeroclaw/config.yaml"
    nanoclaw_config_path: str = "~/.nanoclaw/config.yaml"


@dataclass
class SkillEvolutionConfig:
    enabled:                bool  = True
    success_rate_threshold: float = 0.4
    llm_model:              str   = "gpt-5.2"
    max_new_skills_per_run: int   = 5


@dataclass
class SkillConfig:
    skills_dir:             str   = "skills"
    retrieval_mode:         str   = "template"
    top_k:                  int   = 6     # general_skills cap
    task_specific_top_k:    int   = 10    # task-specific skills cap across all matched types
    embedding_model:        str   = "all-MiniLM-L6-v2"
    embedding_model_path:   str   = ""    # e.g. Qwen/Qwen3-Embedding-0.6B for semantic mode
    min_relevance:          float = 0.07  # for retrieve_relevant()
    evolution_history_path: str   = "skills/evolution_history.jsonl"
    evolution:              SkillEvolutionConfig = field(default_factory=SkillEvolutionConfig)


@dataclass
class MemoryRetrievalConfig:
    top_k: int = 5
    mode:  str = "keyword"   # "keyword" | "hybrid" | "embedding"


@dataclass
class MemorySummarizationConfig:
    enabled:            bool = True
    llm_model:          str  = "gpt-5.2"
    max_summary_tokens: int  = 200


@dataclass
class MemoryConsolidationConfig:
    enabled:              bool  = True
    similarity_threshold: float = 0.80
    decay_after_days:     int   = 30
    decay_factor:         float = 0.05
    min_importance:       float = 0.15
    decay_mode:           str   = "linear"   # "linear" | "exponential"


@dataclass
class MemoryPolicyConfig:
    profile:               str   = "balanced"  # balanced | recall | precision | recent
    max_injected_units:    int   = 6
    max_injected_tokens:   int   = 800
    recent_bonus_hours:    int   = 72
    keyword_weight:        float = 1.0
    metadata_weight:       float = 0.45
    importance_weight:     float = 0.5
    recency_weight:        float = 0.3


@dataclass
class MemoryConfig:
    backend:          str = "sqlite"
    data_dir:         str = "memory_data/memory"
    user_memory_path: str = "memory_data/user_memory.md"
    scope:            str = "default"
    retrieval:        MemoryRetrievalConfig     = field(default_factory=MemoryRetrievalConfig)
    policy:           MemoryPolicyConfig        = field(default_factory=MemoryPolicyConfig)
    consolidation:    MemoryConsolidationConfig = field(default_factory=MemoryConsolidationConfig)
    # Kept for code that still references summarization directly.
    summarization:    MemorySummarizationConfig = field(default_factory=MemorySummarizationConfig)
    # Embedding settings.
    use_embeddings:   bool = False
    embedding_mode:   str  = "hashing"         # "hashing" | "semantic"
    embedding_model:  str  = "all-MiniLM-L6-v2"
    # Session buffering.
    flush_every:      int  = 5
    auto_consolidate: bool = True

    # Backward-compatibility properties for code that reads these directly.
    @property
    def max_injected_units(self) -> int:
        return self.policy.max_injected_units

    @property
    def max_injected_tokens(self) -> int:
        return self.policy.max_injected_tokens


@dataclass
class PRMConfig:
    enabled:        bool = True
    provider:       str  = "openai"
    model:          str  = "gpt-5.2"
    api_base:       str  = ""
    majority_votes: int  = 3


@dataclass
class OPDConfig:
    enabled:         bool  = False
    teacher_url:     str   = ""
    teacher_model:   str   = ""
    teacher_api_key: str   = ""
    kl_penalty_coef: float = 0.1


@dataclass
class ActiveModelConfig:
    name:     str = ""
    provider: str = ""


@dataclass
class RLConfig:
    enabled:       bool  = False
    backend:       str   = "tinker"
    batch_size:    int   = 4
    learning_rate: float = 1e-4
    max_steps:     int   = 1000
    loss_fn:       str   = "importance_sampling"
    records_dir:   str   = "records"
    prm:           PRMConfig         = field(default_factory=PRMConfig)
    opd:           OPDConfig         = field(default_factory=OPDConfig)
    active_model:  ActiveModelConfig = field(default_factory=ActiveModelConfig)


@dataclass
class ImageCacheConfig:
    enabled:     bool = True
    dir:         str  = "~/.visualclaw/image_cache"
    max_entries: int  = 5000
    ttl_seconds: int  = 86400


@dataclass
class ImageConfig:
    enabled:               bool = True
    generate_descriptions: bool = False
    description_model:     str  = "gpt-5.2"
    output_format:         str  = "preserve"
    cache:                 ImageCacheConfig = field(default_factory=ImageCacheConfig)


@dataclass
class FrameHasherConfig:
    hamming_threshold: int = 6


@dataclass
class LightweightEncoderConfig:
    output_dim: int = 128


@dataclass
class ChangeGateConfig:
    tau_minor:               float = 0.08
    tau_major:               float = 0.20
    silence_force_major_sec: int   = 10
    # Temporal decay: start lowering thresholds after this many seconds of
    # no MAJOR trigger, down to `decay_floor` multiplier at silence_force_major_sec.
    # Set decay_start_sec >= silence_force_major_sec to disable decay.
    decay_start_sec:         float = 4.0
    decay_floor:             float = 0.3
    # Scene-complexity adaptation (EMA of cosine distances tunes thresholds):
    # static scenes → factor `adaptive_low` (raises thresholds, fewer triggers);
    # dynamic scenes → factor `adaptive_high` (lowers thresholds, more triggers).
    adaptive:                bool  = True
    adaptive_alpha:          float = 0.15
    adaptive_low:            float = 1.3
    adaptive_high:           float = 0.7


@dataclass
class StateMemoryConfig:
    max_total:    int = 120
    max_keyframes: int = 10


@dataclass
class ContextBuilderConfig:
    max_keyframes_in_context: int = 5


@dataclass
class VideoConfig:
    enabled:              bool = False
    vlm_model:            str  = "gemini-2.0-flash"
    state_memory_dir:     str  = ""
    frame_hasher:         FrameHasherConfig         = field(default_factory=FrameHasherConfig)
    lightweight_encoder:  LightweightEncoderConfig  = field(default_factory=LightweightEncoderConfig)
    change_gate:          ChangeGateConfig           = field(default_factory=ChangeGateConfig)
    state_memory:         StateMemoryConfig          = field(default_factory=StateMemoryConfig)
    context_builder:      ContextBuilderConfig       = field(default_factory=ContextBuilderConfig)


@dataclass
class MultimodalConfig:
    image: ImageConfig = field(default_factory=ImageConfig)
    video: VideoConfig = field(default_factory=VideoConfig)


@dataclass
class VisionIndexConfig:
    backend: str = "faiss"
    metric:  str = "cosine"


@dataclass
class VisionCacheConfig:
    enabled:     bool = True
    max_entries: int  = 10000
    ttl_seconds: int  = 86400


@dataclass
class VisionFusionConfig:
    text_weight:  float = 0.3
    image_weight: float = 0.7


@dataclass
class VisionRetrievalConfig:
    enabled:    bool  = False
    model:      str   = "siglip"
    model_path: str   = ""
    cache_dir:  str   = "~/.visualclaw/vision_cache"
    dimension:  int   = 768
    fusion:     VisionFusionConfig = field(default_factory=VisionFusionConfig)
    index:      VisionIndexConfig  = field(default_factory=VisionIndexConfig)
    cache:      VisionCacheConfig  = field(default_factory=VisionCacheConfig)


@dataclass
class GovernanceAuditConfig:
    enabled:        bool = True
    dir:            str  = ".autoharness"
    retention_days: int  = 30


@dataclass
class GovernanceConfig:
    enabled:                   bool  = False
    constitution_path:         str   = "constitution.yaml"
    cost_tracking:             bool  = True
    cost_default_model:        str   = "gpt-5.2"
    state_memory_token_budget: int   = 8000
    audit:                     GovernanceAuditConfig = field(default_factory=GovernanceAuditConfig)


@dataclass
class CalendarConfig:
    enabled:          bool = False
    credentials_path: str  = "~/.visualclaw/client_secrets.json"
    token_path:       str  = "~/.visualclaw/calendar_token.json"


@dataclass
class SchedulerConfig:
    enabled:                bool = False
    mode:                   str  = "idle"
    idle_threshold_minutes: int  = 30
    sleep_start:            str  = "23:00"
    sleep_end:              str  = "07:00"
    min_window_minutes:     int  = 15
    log_path:               str  = "~/.visualclaw/scheduler.log"
    calendar:               CalendarConfig = field(default_factory=CalendarConfig)


@dataclass
class AudioConfig:
    enabled:     bool = False
    sample_rate: int  = 16000


@dataclass
class GeminiLiveConfig:
    enabled: bool = False
    model:   str  = "gemini-2.5-flash"
    api_key: str  = ""


@dataclass
class LiveConfig:
    enabled:              bool  = False
    glasses_port:         int   = 8765
    glasses_http_enabled: bool  = False  # Legacy /v1/video/frame + /v1/glasses/chat for iOS app
    camera_fps:           float = 4.0
    jpeg_quality:         int   = 50
    user_memory_path:     str   = ""
    audio:                AudioConfig      = field(default_factory=AudioConfig)
    gemini_live:          GeminiLiveConfig = field(default_factory=GeminiLiveConfig)


# ── Top-level v3 config ──────────────────────────────────────────────────────

@dataclass
class VisualClawConfig:
    """
    V3 nested configuration class used by the gateway and new modules.

    Use load_config() to create an instance with four-level priority merge:
      defaults.yaml < project config.yaml < MM_* env vars < cli_overrides
    """
    daemon:           DaemonConfig          = field(default_factory=DaemonConfig)
    gateway:          GatewayConfig         = field(default_factory=GatewayConfig)
    proxy:            ProxyConfig           = field(default_factory=ProxyConfig)
    agent_adapters:   AgentAdaptersConfig   = field(default_factory=AgentAdaptersConfig)
    skill:            SkillConfig           = field(default_factory=SkillConfig)
    memory:           MemoryConfig          = field(default_factory=MemoryConfig)
    rl:               RLConfig              = field(default_factory=RLConfig)
    multimodal:       MultimodalConfig      = field(default_factory=MultimodalConfig)
    vision_retrieval: VisionRetrievalConfig = field(default_factory=VisionRetrievalConfig)
    governance:       GovernanceConfig      = field(default_factory=GovernanceConfig)
    scheduler:        SchedulerConfig       = field(default_factory=SchedulerConfig)
    live:             LiveConfig            = field(default_factory=LiveConfig)

    @classmethod
    def from_dict(cls, d: dict) -> "VisualClawConfig":
        """Deserialize a nested dict into VisualClawConfig recursively."""
        return _build_dataclass(cls, d)

    def resolve_path(self, path_str: str) -> Path:
        """Expand ~ and resolve to absolute path."""
        return Path(path_str).expanduser().resolve()


# ── Config loading ───────────────────────────────────────────────────────────

_DEFAULTS_PATH = Path(__file__).parent / "config" / "defaults.yaml"
_ENV_PREFIX = "MM_"


def load_config(cli_overrides: dict[str, Any] | None = None) -> VisualClawConfig:
    """
    Four-level priority merge (lowest → highest):
      1. defaults.yaml  (bundled, always present)
      2. user config.yaml — first match wins among:
           a. ``MM_VISUALCLAW_CONFIG_DIR``/config.yaml  (env override)
           b. cwd/…/pyproject.toml sibling config.yaml  (project-level)
           c. ``~/.visualclaw/config.yaml``           (user-level fallback)
         Files in v2 flat schema are auto-migrated to v3 on read.
      3. MM_* environment variables
      4. cli_overrides  (highest priority)
    """
    from visualclaw.env import load_dotenv

    load_dotenv()

    base = _load_yaml(_DEFAULTS_PATH)
    user_cfg = _find_project_config()
    if user_cfg is not None:
        base = _deep_merge(base, _load_and_migrate(user_cfg))
    base = _apply_env_vars(base)
    if cli_overrides:
        base = _deep_merge(base, cli_overrides)
    return VisualClawConfig.from_dict(base)


def _load_and_migrate(path: Path) -> dict:
    """Load a yaml config file; if it's in the v2 flat schema, translate to v3
    before returning. Delegates the actual migration to
    :mod:`visualclaw.config_store` so the rule lives in one place."""
    data = _load_yaml(path)
    try:
        from .config_store import _looks_like_v2, _migrate_v2_to_v3
    except Exception:
        return data
    if _looks_like_v2(data):
        return _migrate_v2_to_v3(data)
    return data


def _find_project_config() -> Path | None:
    """Locate the user's config.yaml. First match wins:

    1. ``$MM_VISUALCLAW_CONFIG_DIR/config.yaml``  (explicit env override)
    2. cwd walk to ``<project_root>/config.yaml`` next to ``pyproject.toml``
    3. ``~/.visualclaw/config.yaml`` (what ``visualclaw setup`` writes)

    Returns ``None`` if none of the three exists.
    """
    env_dir = os.environ.get("MM_VISUALCLAW_CONFIG_DIR")
    if env_dir:
        candidate = Path(env_dir).expanduser() / "config.yaml"
        if candidate.exists():
            return candidate

    current = Path.cwd()
    for directory in [current, *current.parents]:
        if (directory / "pyproject.toml").exists():
            candidate = directory / "config.yaml"
            if candidate.exists():
                return candidate
            break  # found the project root but no config — fall through

    user_cfg = Path.home() / ".visualclaw" / "config.yaml"
    if user_cfg.exists():
        return user_cfg

    return None


def _apply_env_vars(cfg: dict) -> dict:
    """
    Translate MM_* environment variables into nested dict overrides.
    Examples:
      MM_GATEWAY_PORT=30100    → cfg["gateway"]["port"] = 30100
      MM_RL_ENABLED=true       → cfg["rl"]["enabled"] = True
      MM_SKILL_TOP_K=5         → cfg["skill"]["top_k"] = 5
    Rules: strip MM_, lowercase, first segment = top-level key, rest = path.
    Type inference: true/false→bool, integer→int, float→float, comma-sep→list.
    """
    result = {k: v for k, v in cfg.items()}
    for env_key, env_val in os.environ.items():
        if not env_key.startswith(_ENV_PREFIX):
            continue
        parts = env_key[len(_ENV_PREFIX):].lower().split("_")
        if not parts:
            continue
        coerced = _coerce_env_value(env_val)
        _set_nested(result, parts, coerced)
    return result


def _coerce_env_value(val: str) -> Any:
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    if "," in val:
        return [_coerce_env_value(v.strip()) for v in val.split(",")]
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _set_nested(d: dict, parts: list[str], value: Any) -> None:
    """Set d[parts[0]][parts[1]]...[parts[-1]] = value, creating dicts as needed."""
    for part in parts[:-1]:
        if part not in d or not isinstance(d[part], dict):
            d[part] = {}
        d = d[part]
    d[parts[-1]] = value


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursive merge; override wins. Lists are replaced, not appended."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _load_yaml(path: Path) -> dict:
    """Load a YAML file; return {} if the file does not exist.

    After loading, all string values are passed through
    :func:`expand_env_placeholders` so that ``${VAR}`` tokens are replaced
    with the corresponding environment variable.  Unknown variables are left
    as-is (the literal ``${VAR}`` string), which makes missing configuration
    easy to detect.
    """
    if not path.exists():
        return {}
    try:
        import yaml
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data = expand_env_placeholders(data)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _build_dataclass(cls, data: Any) -> Any:
    """Recursively construct a dataclass from a dict (or return the value as-is)."""
    import dataclasses as _dc
    import typing
    if not _dc.is_dataclass(cls) or not isinstance(data, dict):
        return data
    # Resolve all string annotations to actual types
    try:
        hints = typing.get_type_hints(cls)
    except Exception:
        hints = {f.name: f.type for f in _dc.fields(cls)}

    kwargs: dict[str, Any] = {}
    for f in _dc.fields(cls):
        if f.name not in data:
            continue
        val = data[f.name]
        field_type = hints.get(f.name, f.type)
        # Unwrap Optional[X] → X
        origin = getattr(field_type, "__origin__", None)
        if origin is typing.Union:
            args = [a for a in field_type.__args__ if a is not type(None)]
            field_type = args[0] if args else field_type
        if _dc.is_dataclass(field_type) and isinstance(val, dict):
            kwargs[f.name] = _build_dataclass(field_type, val)
        else:
            kwargs[f.name] = val
    return cls(**kwargs)
