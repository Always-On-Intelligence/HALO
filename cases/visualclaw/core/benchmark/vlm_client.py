"""
Unified VLM client for benchmarks — supports Gemini, OpenAI-compatible, and Bedrock.

All benchmark harnesses import from here to avoid duplicating VLM call logic.

Usage::

    client = create_vlm_client()  # auto-detects from env vars
    answer = await client.ask("What is happening?", image_paths=["frame.jpg"])
    answer = await client.ask_video_frames("What happened?", frames=[jpeg1, jpeg2])
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Optional

from visualclaw.env import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class VLMClient:
    """Unified async VLM client for benchmarks.

    Auto-detects provider from environment variables:
      - GEMINI_API_KEY → Google Generative AI
      - OPENAI_API_KEY → OpenAI-compatible
      - AWS_DEFAULT_REGION or USE_BEDROCK=1 → AWS Bedrock

    Parameters
    ----------
    provider: Force provider ("gemini", "openai", "bedrock"). Auto if None.
    model: Model name override. Uses sensible defaults per provider.
    temperature: Sampling temperature.
    max_tokens: Max response tokens.
    governance: Optional GovernanceLayer for cost tracking.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        governance=None,
    ):
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._provider = provider or self._detect_provider()
        self._model = model or self._default_model()
        self._client = None
        self._governance = governance
        # Cumulative usage stats
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_reasoning_tokens: int = 0
        self._total_cached_input_tokens: int = 0
        self._total_calls: int = 0
        self._call_tag: str = "vlm_call"  # overridable per-call tag
        self._init_client()

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    @property
    def usage_stats(self) -> dict:
        """Cumulative token usage across all VLM calls."""
        return {
            "total_calls": self._total_calls,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_reasoning_tokens": self._total_reasoning_tokens,
            "total_cached_input_tokens": self._total_cached_input_tokens,
            "total_tokens": self._total_input_tokens + self._total_output_tokens,
            "content_filter_fallbacks": getattr(self, "_content_filter_fallbacks", 0),
        }

    def set_call_tag(self, tag: str) -> None:
        """Set the cost attribution tag for subsequent calls.

        Use to distinguish call types, e.g. "vlm_keyframe_description"
        vs "vlm_qa_answer".
        """
        self._call_tag = tag

    def _record_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int = 0,
        cached_input_tokens: int = 0,
    ) -> None:
        """Record token usage from a VLM response.

        reasoning_tokens: hidden reasoning emitted by reasoning-class models
        (GPT-5.x). Tracked separately because some endpoints bill these at
        the visible-output rate but do not include them in completion_tokens.
        cached_input_tokens: subset of input_tokens served from the prompt
        cache (charged at a discounted rate on most providers).
        """
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self._total_reasoning_tokens += reasoning_tokens
        self._total_cached_input_tokens += cached_input_tokens
        self._total_calls += 1
        if self._governance is not None:
            self._governance.record_usage(
                model=self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens + reasoning_tokens,
                tool_name=self._call_tag,
            )

    def _detect_provider(self) -> str:
        if os.environ.get("GEMINI_API_KEY"):
            return "gemini"
        if os.environ.get("USE_BEDROCK") == "1":
            return "bedrock"
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
        # Default to bedrock on AWS instances
        try:
            import boto3
            boto3.client("sts").get_caller_identity()
            return "bedrock"
        except Exception:
            pass
        raise EnvironmentError(
            "No VLM credentials found. Set one of: "
            "GEMINI_API_KEY, OPENAI_API_KEY, or USE_BEDROCK=1"
        )

    def _default_model(self) -> str:
        defaults = {
            "gemini": "gemini-2.0-flash",
            "openai": "gpt-5.2",
            "bedrock": "us.anthropic.claude-sonnet-4-6",
        }
        return defaults.get(self._provider, "gpt-5.2")

    def _init_client(self) -> None:
        if self._provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=os.environ["GEMINI_API_KEY"])
            self._client = genai.GenerativeModel(self._model)
        elif self._provider == "openai":
            from openai import OpenAI
            self._client = OpenAI(
                api_key=os.environ.get("OPENAI_API_KEY", ""),
                base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            )
        elif self._provider == "bedrock":
            from visualclaw.bedrock_client import BedrockChatClient
            region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
            api_key = os.environ.get("BEDROCK_API_KEY")
            self._client = BedrockChatClient(
                model_id=self._model, region=region, api_key=api_key,
            )

    async def ask(
        self,
        question: str,
        image_paths: Optional[list[str]] = None,
        system_prompt: str = "",
        system_prompt_fallbacks: Optional[list[str]] = None,
    ) -> str:
        """Ask a question with optional image paths.

        Parameters
        ----------
        question: The text question.
        image_paths: Optional list of image file paths.
        system_prompt: Optional system prompt.
        system_prompt_fallbacks: Ordered list of degraded prompts to try on
            Azure content_filter / jailbreak 400s. Typically supplied by the
            caller as [drop-top-1, drop-top-2, ..., empty]. If None or empty,
            falls back to a single empty-prompt retry.
        """
        images_b64 = []
        if image_paths:
            for p in image_paths:
                with open(p, "rb") as f:
                    images_b64.append(base64.b64encode(f.read()).decode())
        return await self._call(question, images_b64, system_prompt, system_prompt_fallbacks)

    async def ask_with_frames(
        self,
        question: str,
        frames: list[bytes],
        system_prompt: str = "",
        system_prompt_fallbacks: Optional[list[str]] = None,
    ) -> str:
        """Ask a question with JPEG frame bytes."""
        images_b64 = [base64.b64encode(f).decode() for f in frames]
        return await self._call(question, images_b64, system_prompt, system_prompt_fallbacks)

    async def _call(
        self, question: str, images_b64: list[str], system_prompt: str,
        system_prompt_fallbacks: Optional[list[str]] = None,
    ) -> str:
        return await asyncio.to_thread(
            self._call_sync, question, images_b64, system_prompt, system_prompt_fallbacks,
        )

    def _call_sync(
        self, question: str, images_b64: list[str], system_prompt: str,
        system_prompt_fallbacks: Optional[list[str]] = None,
    ) -> str:
        if self._provider == "gemini":
            return self._call_gemini(question, images_b64, system_prompt)
        else:
            return self._call_openai_compat(
                question, images_b64, system_prompt, system_prompt_fallbacks,
            )

    def _call_gemini(
        self, question: str, images_b64: list[str], system_prompt: str,
    ) -> str:
        import google.generativeai as genai
        from PIL import Image
        import io
        import time

        parts = []
        if system_prompt:
            parts.append(f"[System: {system_prompt}]\n\n")
        parts.append(question)

        for b64 in images_b64:
            raw = base64.b64decode(b64)
            img = Image.open(io.BytesIO(raw))
            parts.append(img)

        # Mirror the OpenAI 429 retry ladder: 5 attempts with exponential
        # backoff. Gemini RESOURCE_EXHAUSTED (429-class) is common when
        # multiple jobs share an API key under free-tier rate limits.
        backoffs = [3, 6, 12, 24, 45]
        last_exc = None
        resp = None
        for attempt, delay in enumerate(backoffs):
            try:
                resp = self._client.generate_content(
                    parts,
                    generation_config=genai.types.GenerationConfig(
                        temperature=self.temperature,
                        max_output_tokens=self.max_tokens,
                    ),
                )
                last_exc = None
                break
            except Exception as e:
                last_exc = e
                msg = str(e)
                retryable = (
                    "429" in msg
                    or "RESOURCE_EXHAUSTED" in msg
                    or "rate" in msg.lower()
                    or "quota" in msg.lower()
                    or "503" in msg
                    or "502" in msg
                    or "timeout" in msg.lower()
                )
                if not retryable or attempt == len(backoffs) - 1:
                    break
                time.sleep(delay)

        if resp is None:
            raise last_exc

        # Record token usage
        try:
            meta = resp.usage_metadata
            self._record_usage(
                input_tokens=getattr(meta, "prompt_token_count", 0) or 0,
                output_tokens=getattr(meta, "candidates_token_count", 0) or 0,
            )
        except Exception:
            self._record_usage(0, 0)

        return resp.text

    def _call_openai_compat(
        self, question: str, images_b64: list[str], system_prompt: str,
        system_prompt_fallbacks: Optional[list[str]] = None,
    ) -> str:
        # Build user content once (shared across system-prompt fallbacks)
        user_content = [{"type": "text", "text": question}]
        for b64 in images_b64:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        user_msg = {"role": "user", "content": user_content}

        def _build_messages(sys_p: str) -> list[dict]:
            msgs: list[dict] = []
            if sys_p:
                msgs.append({"role": "system", "content": sys_p})
            msgs.append(user_msg)
            return msgs

        messages = _build_messages(system_prompt)

        # Retry loop for transient rate-limit / 5xx errors. The Cloudflare
        # Worker proxy for GPT-5.2 returns 429 aggressively under concurrency;
        # exponential backoff recovers cleanly.
        import time as _time
        resp = None
        last_exc = None
        for attempt in range(5):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=self.temperature,
                    max_completion_tokens=self.max_tokens,
                )
                break
            except Exception as e:
                msg = str(e)
                retryable = (
                    "429" in msg
                    or "rate_limit" in msg.lower()
                    or "too many requests" in msg.lower()
                    or "503" in msg
                    or "502" in msg
                    or "timeout" in msg.lower()
                )
                if not retryable or attempt == 4:
                    last_exc = e
                    break
                _time.sleep(min(2 ** attempt * 3, 45))  # 3, 6, 12, 24, 45 s caps
                last_exc = e
        # Graceful degradation on Azure content-filter / jailbreak blocks.
        # On 400 with content_filter/jailbreak, walk a ladder of degraded
        # system prompts (caller supplies them; SkillWire builds [drop-top-1,
        # drop-top-2, ..., empty]). Retrying the same prompt is futile
        # (Azure's classifier is deterministic on input), so we degrade
        # progressively until the call succeeds or we exhaust the ladder.
        def _is_filter_error(exc) -> bool:
            t = str(exc).lower()
            return ("content_filter" in t or "jailbreak" in t
                    or "responsibleaipolicyviolation" in t)

        if resp is None and last_exc is not None and _is_filter_error(last_exc):
            # Build fallback ladder. Default = single empty-prompt retry.
            ladder = list(system_prompt_fallbacks or [])
            if system_prompt and "" not in ladder:
                ladder.append("")  # ensure plain-prompt is the last resort
            for i, fb_prompt in enumerate(ladder):
                if fb_prompt == system_prompt:
                    continue  # skip prompts identical to the one that just failed
                logger.warning(
                    "[VLMClient] content-filter block; degrading to fallback "
                    "%d/%d (system_prompt len=%d → %d)",
                    i + 1, len(ladder), len(system_prompt), len(fb_prompt),
                )
                try:
                    resp = self._client.chat.completions.create(
                        model=self._model,
                        messages=_build_messages(fb_prompt),
                        temperature=self.temperature,
                        max_completion_tokens=self.max_tokens,
                    )
                    self._content_filter_fallbacks = (
                        getattr(self, "_content_filter_fallbacks", 0) + 1
                    )
                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    if not _is_filter_error(e):
                        break  # non-filter error — bail out

        if resp is None:
            raise last_exc  # surface the last error after retries exhausted

        # Record token usage
        try:
            usage = resp.usage
            ct_details = getattr(usage, "completion_tokens_details", None)
            reasoning = 0
            if ct_details is not None:
                reasoning = (
                    getattr(ct_details, "reasoning_tokens", 0)
                    if not isinstance(ct_details, dict)
                    else ct_details.get("reasoning_tokens", 0)
                ) or 0
            pt_details = getattr(usage, "prompt_tokens_details", None)
            cached = 0
            if pt_details is not None:
                cached = (
                    getattr(pt_details, "cached_tokens", 0)
                    if not isinstance(pt_details, dict)
                    else pt_details.get("cached_tokens", 0)
                ) or 0
            self._record_usage(
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                reasoning_tokens=reasoning,
                cached_input_tokens=cached,
            )
        except Exception:
            self._record_usage(0, 0)

        return resp.choices[0].message.content


class MockVLMClient(VLMClient):
    """Mock client for dry-run mode — returns a generic response."""

    def __init__(self, response_text: str = "I see a scene with activity."):
        self._provider = "mock"
        self._model = "mock"
        self._response = response_text

    async def ask(self, question: str, **kwargs) -> str:
        return self._response

    async def ask_with_frames(self, question: str, **kwargs) -> str:
        return self._response


def create_vlm_client(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    dry_run: bool = False,
    governance=None,
    max_tokens: int = 1024,
) -> VLMClient:
    """Factory function for benchmark VLM clients.

    max_tokens default 1024 matches VLMClient's own default for backward compat,
    but VisualClawArena rounds need ~4096+ to avoid mid-reasoning truncation before the
    answer line (`\\bbox{X}` / `### WRITE_FILE:`).
    """
    if dry_run:
        return MockVLMClient()
    return VLMClient(provider=provider, model=model, governance=governance,
                     max_tokens=max_tokens)
