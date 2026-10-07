"""
Shared data types for the VisualClaw gateway pipeline.

All modules may import from this file; no other cross-module imports are allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImageMeta:
    """
    Unified image representation shared across the entire pipeline.

    Fill timing:
      url         — extracted from the raw request by Proxy / Plugin adapter
      raw_bytes   — decoded by the Multimodal Image module (Proxy mode);
                    None in Plugin-direct mode (RL formatter reads from url)
      description — filled by ImageDescriber (optional)
      embedding   — filled by vision_retrieval component when enabled
      sha256      — filled by ImageExtractor, used as cache key
    """
    url:         str | None = None
    media_type:  str = "image/jpeg"
    raw_bytes:   bytes | None = None
    description: str | None = None
    embedding:   list[float] | None = None
    sha256:      str = ""


@dataclass
class ProviderConfig:
    api_base:      str
    api_key:       str
    provider_type: str    # openai | anthropic | bedrock


@dataclass
class Message:
    role:         str                      # user | assistant | system | tool
    content:      str | list[dict] | None  # str or content blocks
    tool_calls:   list[dict] | None = None
    tool_call_id: str | None = None
    name:         str | None = None


@dataclass
class Turn:
    role:         str
    content:      str | list[dict] | None
    tool_calls:   list[dict] | None = None
    tool_call_id: str | None = None
    images:       list[ImageMeta] | None = None
    timestamp:    str = ""


@dataclass
class PipelineContext:
    """Context passed between modules in the Pre pipeline (Proxy mode)."""
    session_id:      str
    turn_index:      int
    messages:        list[Message]
    model:           str
    provider:        ProviderConfig | None = None
    images:          list[ImageMeta] = field(default_factory=list)
    additional_ctx:  list[str] = field(default_factory=list)
    module_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trajectory:
    """Full trajectory passed through the Post pipeline."""
    session_id:   str
    turns:        list[Turn]
    model:        str
    provider:     str
    total_tokens: int = 0
    duration_ms:  int = 0
    success:      bool = True
    metadata:     dict[str, Any] = field(default_factory=dict)


# ── HTTP request / response base types ──────────────────────────────────────

@dataclass
class PreRequest:
    """Standard request body for all /v1/{module}/inject endpoints."""
    session_id: str
    messages:   list[dict]    # OpenAI-format Message dicts
    model:      str
    metadata:   dict[str, Any] = field(default_factory=dict)


@dataclass
class PreResponse:
    """Standard response body for all /v1/{module}/inject endpoints."""
    additional_context: str = ""
    messages:           list[dict] | None = None   # if the module modified messages
    model:              str | None = None           # if the module modified the model (RL)
    provider:           dict | None = None          # if the module modified the provider (RL)
    metadata:           dict[str, Any] = field(default_factory=dict)


@dataclass
class PostRequest:
    """Standard request body for all /v1/{module}/collect endpoints."""
    session_id: str
    trajectory: list[dict]    # Turn dicts
    metadata:   dict[str, Any] = field(default_factory=dict)


@dataclass
class PostResponse:
    """Standard response body for all /v1/{module}/collect endpoints."""
    status:     str            # accepted | skipped | error
    queued_for: list[str] = field(default_factory=list)
    metadata:   dict[str, Any] = field(default_factory=dict)
