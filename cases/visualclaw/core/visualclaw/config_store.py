"""
User-facing configuration store for VisualClaw.

Reads/writes ~/.visualclaw/config.yaml in v3 nested schema, matching what
load_config() (in config.py) expects. Files written by older versions use a
v2 flat schema (``llm:`` / ``skills:`` / ``proxy.port`` top-level); on load
we migrate them to v3 shape in memory so the rest of the code only ever
sees v3. Callers who re-save will then persist the v3 form.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _resolve_config_dir() -> Path:
    """Resolve the directory used for ``config.yaml``, ``skills/``, log/pid files.

    Honours ``MM_VISUALCLAW_CONFIG_DIR`` so that ``visualclaw setup`` writes to
    the same location that ``visualclaw start`` reads from. Falls back to
    ``~/.visualclaw`` when the env var is unset.
    """
    env = os.environ.get("MM_VISUALCLAW_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".visualclaw"


CONFIG_DIR  = _resolve_config_dir()
CONFIG_FILE = CONFIG_DIR / "config.yaml"

# Provider slot mapping: which v3 `proxy.providers.<slot>` entry do we populate
# when the user picks a logical provider name in the wizard? Most third-party
# providers speak the OpenAI-compatible protocol, so they share the `openai`
# slot with just a different api_base; only providers with native protocols
# get their own slot.
_PROVIDER_SLOT = {
    "openai":     "openai",
    "kimi":       "openai",
    "qwen":       "openai",
    "minimax":    "openai",
    "novita":     "openai",
    "custom":     "openai",
    "anthropic":  "anthropic",
    "openrouter": "openrouter",
    "bedrock":    "bedrock",
}


_DEFAULTS: dict = {
    "gateway": {
        "host": "0.0.0.0",
        "port": 30100,
    },
    "proxy": {
        "streaming": True,
        "providers": {
            "openai":     {"api_base": "", "api_key": ""},
            "anthropic":  {"api_base": "", "api_key": ""},
            "openrouter": {
                "api_base":        "https://openrouter.ai/api/v1",
                "api_key":         "",
                "route":           "",
                "fallback_models": [],
                "data_policy":     "",
                "app_name":        "VisualClaw",
                "app_url":         "",
            },
            "bedrock": {"region": "us-east-1", "access_key": "", "secret_key": ""},
        },
    },
    "skill": {
        "skills_dir":          str(CONFIG_DIR / "skills"),
        "retrieval_mode":      "template",
        "top_k":               6,
        "task_specific_top_k": 10,
        "evolution": {
            "enabled":                True,
            "success_rate_threshold": 0.4,
            "llm_model":              "gpt-5.2",
            "max_new_skills_per_run": 5,
        },
    },
    "rl": {
        "enabled":    False,
        "backend":    "tinker",
        "batch_size": 4,
        "prm": {
            "enabled":  False,
            "provider": "openai",
            "model":    "gpt-5.2",
            "api_base": "https://api.openai.com/v1",
            "api_key":  "",
        },
    },
    "scheduler": {
        "enabled":                False,
        "mode":                   "idle",
        "idle_threshold_minutes": 30,
        "sleep_start":            "23:00",
        "sleep_end":              "07:00",
        "min_window_minutes":     15,
        "calendar": {
            "enabled":          False,
            "credentials_path": "",
            "token_path":       str(CONFIG_DIR / "calendar_token.json"),
        },
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _coerce(value: Any) -> Any:
    """Auto-coerce string values to bool/int/float where obvious."""
    if not isinstance(value, str):
        return value
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


# ── v2 → v3 migration ─────────────────────────────────────────────────────────


def _looks_like_v2(data: dict) -> bool:
    """Heuristic: v2 files have top-level ``llm`` / ``mode`` / ``claw_type`` or
    a flat ``proxy.port``/``proxy.host``. v3 uses ``proxy.providers`` nested."""
    if not isinstance(data, dict):
        return False
    if "llm" in data or "mode" in data or "claw_type" in data:
        return True
    proxy = data.get("proxy") or {}
    if isinstance(proxy, dict) and ("port" in proxy or "host" in proxy):
        # v3 moves port/host to `gateway.*`; their presence on `proxy` is a v2 tell.
        return True
    if "skills" in data and "skill" not in data:
        return True
    return False


def _migrate_v2_to_v3(v2: dict) -> dict:
    """Translate a v2 flat-schema dict into v3 nested-schema dict.

    Preserves as many fields as possible. Fields with no v3 equivalent
    (``claw_type``, ``mode``, ``agent_backend``) are dropped — their effect
    is baked into v3 flag flips (e.g. ``mode: rl`` → ``rl.enabled: true``).
    """
    v3: dict = {}

    # --- gateway.{host,port} (from proxy.*) ---
    proxy_v2 = v2.get("proxy") or {}
    gateway: dict = {}
    if isinstance(proxy_v2, dict):
        if "port" in proxy_v2:
            gateway["port"] = proxy_v2["port"]
        if "host" in proxy_v2:
            gateway["host"] = proxy_v2["host"]
    if gateway:
        v3["gateway"] = gateway

    # --- proxy.providers.<slot> (from llm.*) ---
    llm = v2.get("llm") or {}
    providers: dict = {}
    if isinstance(llm, dict) and llm:
        provider_name = str(llm.get("provider") or "openai").lower()
        slot = _PROVIDER_SLOT.get(provider_name, "openai")
        entry: dict = {}
        if llm.get("api_base"):
            entry["api_base"] = llm["api_base"]
        if llm.get("api_key"):
            entry["api_key"] = llm["api_key"]
        if entry:
            providers[slot] = entry
        if slot == "bedrock":
            region = llm.get("bedrock_region") or v2.get("bedrock_region")
            if region:
                providers.setdefault("bedrock", {})["region"] = region
    orouter = v2.get("openrouter") or {}
    if isinstance(orouter, dict) and orouter:
        or_entry = providers.setdefault("openrouter", {})
        for k in ("app_name", "app_url", "route", "data_policy"):
            if orouter.get(k) is not None:
                or_entry[k] = orouter[k]
        if orouter.get("fallback_models"):
            fm = orouter["fallback_models"]
            if isinstance(fm, str):
                fm = [s.strip() for s in fm.split(",") if s.strip()]
            or_entry["fallback_models"] = fm
    proxy_v3: dict = {}
    if providers:
        proxy_v3["providers"] = providers
    # v2 proxy.api_key was an inbound bearer check — keep it if present.
    if isinstance(proxy_v2, dict) and proxy_v2.get("api_key"):
        proxy_v3["proxy_api_key"] = proxy_v2["api_key"]
    if proxy_v3:
        v3["proxy"] = _deep_merge(v3.get("proxy", {}), proxy_v3)

    # --- skill.* (from skills.*) ---
    skills = v2.get("skills") or {}
    if isinstance(skills, dict) and skills:
        sk: dict = {}
        if skills.get("dir"):
            sk["skills_dir"] = skills["dir"]
        for k in ("retrieval_mode", "top_k", "task_specific_top_k"):
            if skills.get(k) is not None:
                sk[k] = skills[k]
        if "auto_evolve" in skills:
            sk["evolution"] = {"enabled": bool(skills["auto_evolve"])}
        if sk:
            v3["skill"] = sk

    # --- rl.* (with nested prm) ---
    rl = v2.get("rl") or {}
    mode = str(v2.get("mode") or "").lower()
    rl_enabled = bool(rl.get("enabled")) or mode in ("rl", "madmax")
    if rl or rl_enabled:
        rl_v3: dict = {"enabled": rl_enabled}
        if rl.get("backend"):
            rl_v3["backend"] = rl["backend"]
        if rl.get("batch_size") is not None:
            rl_v3["batch_size"] = rl["batch_size"]
        prm: dict = {}
        if rl.get("prm_url") or rl.get("prm_api_key") or rl.get("prm_model"):
            prm["enabled"] = True
            if rl.get("prm_provider"):
                prm["provider"] = rl["prm_provider"]
            if rl.get("prm_url"):
                prm["api_base"] = rl["prm_url"]
            if rl.get("prm_model"):
                prm["model"] = rl["prm_model"]
            if rl.get("prm_api_key"):
                prm["api_key"] = rl["prm_api_key"]
        if prm:
            rl_v3["prm"] = prm
        v3["rl"] = rl_v3

    # --- scheduler.* (mostly pass-through; madmax mode forces it on) ---
    sched = v2.get("scheduler") or {}
    if isinstance(sched, dict) and (sched or mode == "madmax"):
        sched_v3 = {k: v for k, v in sched.items() if k != "enabled"}
        sched_v3["enabled"] = bool(sched.get("enabled")) or mode == "madmax"
        v3["scheduler"] = sched_v3

    return v3


# ── ConfigStore ───────────────────────────────────────────────────────────────


class ConfigStore:
    """Read/write ~/.visualclaw/config.yaml in v3 nested schema.

    Files written by older versions (v2 flat schema) are auto-migrated on load.
    The next ``save()`` commits the v3 form back to disk.
    """

    def __init__(self, config_file: Path = CONFIG_FILE):
        self.config_file = config_file

    def exists(self) -> bool:
        return self.config_file.exists()

    def load(self) -> dict:
        if not self.config_file.exists():
            return _deep_merge({}, _DEFAULTS)
        try:
            import yaml
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            return _deep_merge({}, _DEFAULTS)
        if _looks_like_v2(data):
            data = _migrate_v2_to_v3(data)
        return _deep_merge(_DEFAULTS, data)

    def save(self, data: dict):
        import yaml
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    def get(self, dotpath: str) -> Any:
        data = self.load()
        for k in dotpath.split("."):
            if not isinstance(data, dict):
                return None
            data = data.get(k)
        return data

    def set(self, dotpath: str, value: Any):
        data = self.load()
        keys = dotpath.split(".")
        d = data
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = _coerce(value)
        self.save(data)

    def describe(self) -> str:
        """Return a human-readable summary of the current (v3) config."""
        data = self.load()
        gw = data.get("gateway", {})
        providers = (data.get("proxy") or {}).get("providers", {})
        skill = data.get("skill", {})
        rl = data.get("rl", {})
        prm = rl.get("prm", {})
        sched = data.get("scheduler", {})

        lines = [
            f"gateway.host:              {gw.get('host', '0.0.0.0')}",
            f"gateway.port:              {gw.get('port', 30100)}",
        ]
        for slot in ("openai", "anthropic", "openrouter", "bedrock"):
            entry = providers.get(slot) or {}
            if not entry:
                continue
            if slot == "bedrock":
                region = entry.get("region") or "(unset)"
                lines.append(f"proxy.providers.bedrock.region:  {region}")
            else:
                base = entry.get("api_base") or "(unset)"
                has_key = bool(entry.get("api_key"))
                lines.append(
                    f"proxy.providers.{slot}.api_base: {base}"
                )
                lines.append(
                    f"proxy.providers.{slot}.api_key:  {'***set***' if has_key else '(unset)'}"
                )
        lines += [
            f"skill.skills_dir:          {skill.get('skills_dir', '?')}",
            f"skill.retrieval_mode:      {skill.get('retrieval_mode', 'template')}",
            f"skill.top_k:               {skill.get('top_k', 6)}",
            f"skill.evolution.enabled:   {(skill.get('evolution') or {}).get('enabled', True)}",
            f"rl.enabled:                {rl.get('enabled', False)}",
        ]
        if rl.get("enabled"):
            lines += [
                f"rl.backend:                {rl.get('backend', 'tinker')}",
                f"rl.batch_size:             {rl.get('batch_size', 4)}",
                f"rl.prm.enabled:            {prm.get('enabled', False)}",
                f"rl.prm.model:              {prm.get('model', '?')}",
                f"rl.prm.api_base:           {prm.get('api_base', '?')}",
            ]
        if sched.get("enabled"):
            lines += [
                f"scheduler.sleep_start:     {sched.get('sleep_start', '23:00')}",
                f"scheduler.sleep_end:       {sched.get('sleep_end', '07:00')}",
                f"scheduler.idle_threshold:  {sched.get('idle_threshold_minutes', 30)}",
            ]
        return "\n".join(lines)
