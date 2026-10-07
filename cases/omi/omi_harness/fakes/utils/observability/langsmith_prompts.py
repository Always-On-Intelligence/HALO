"""Fake of backend/utils/observability/langsmith_prompts.py: LangSmith is not reachable, so the chat
system prompt is the inline fallback that upstream ships for that case (utils/llm/chat.py:676-895)."""


def get_agentic_system_prompt_template():
    raise RuntimeError('LangSmith prompt hub is not available in this run')


def render_prompt(template_text, variables):
    raise RuntimeError('LangSmith prompt hub is not available in this run')


def get_prompt_metadata():
    raise RuntimeError('LangSmith prompt hub is not available in this run')
