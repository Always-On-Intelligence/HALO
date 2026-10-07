"""LangChain-compatible chat model and embeddings that route Omi's model calls to the HALO backbone.

Omi builds every model call through ``utils.llm.clients.get_llm(feature)`` and then uses it as a
LangChain runnable: ``prompt | llm | parser``, ``llm.with_structured_output(Model).invoke(...)``,
``llm.invoke(messages)``, or, for the chat agent, ``llm.bind(tools=..., tool_choice='auto')``
followed by ``astream``. ``BackboneChatModel`` supports those uses. It renders the LangChain
messages as one (system, user) pair for ``halo.run.llm.LLM`` and turns the reply back into an
AIMessage. Three things are ported, because the CLI backbone is text in, text out:

* structured output (OpenAI json_schema mode upstream): the JSON schema of the pydantic model is
  appended to the prompt and the reply is validated against the model;
* native tool calling (OpenAI function calling upstream): the tool schemas are appended to the
  prompt and a reply of the form {"tool_calls": [...]} becomes AIMessage.tool_calls;
* embeddings (OpenAI text-embedding-3-large upstream): sentence-transformers/all-MiniLM-L6-v2.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool


class Bridge:
    """Process-wide routing state. The adapter sets llm/base/stage for each run."""

    def __init__(self):
        self.llm = None
        self.base = ''
        self.stage = ''
        self.calls = []
        self.lock = threading.Lock()

    def tag(self, feature: str) -> str:
        return f'{self.base}|{self.stage}|{feature}'

    def call(self, system: str, user: str, feature: str) -> str:
        if self.llm is None:
            raise RuntimeError('backbone not configured')
        tag = self.tag(feature)
        text = self.llm(system, user, tag=tag)
        with self.lock:
            self.calls.append({'stage': self.stage, 'feature': feature, 'chars_in': len(system) + len(user)})
        return text


BRIDGE = Bridge()


# ---------------------------------------------------------------------------------------------
# message rendering
# ---------------------------------------------------------------------------------------------
def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get('type') in (None, 'text') and isinstance(part.get('text'), str):
                    parts.append(part['text'])
                elif part.get('type') == 'image_url':
                    parts.append('[image omitted]')
            elif isinstance(part, str):
                parts.append(part)
        return '\n'.join(parts)
    return str(content)


def render(messages: List[BaseMessage]) -> tuple[str, str]:
    system = '\n\n'.join(_text(m.content) for m in messages if isinstance(m, SystemMessage))
    rest = [m for m in messages if not isinstance(m, SystemMessage)]
    if len(rest) == 1 and isinstance(rest[0], HumanMessage):
        return system, _text(rest[0].content)
    lines = []
    for m in rest:
        if isinstance(m, HumanMessage):
            lines.append('[User]\n' + _text(m.content))
        elif isinstance(m, AIMessage):
            block = '[Assistant]\n' + _text(m.content)
            if m.tool_calls:
                block += '\n(tool calls: ' + json.dumps(
                    [{'id': c.get('id'), 'name': c['name'], 'arguments': c.get('args', {})} for c in m.tool_calls],
                    ensure_ascii=False) + ')'
            lines.append(block)
        elif isinstance(m, ToolMessage):
            lines.append(f'[Tool result for call {m.tool_call_id}]\n' + _text(m.content))
        else:
            lines.append(f'[{m.type}]\n' + _text(m.content))
    return system, '\n\n'.join(lines)


_JSON_BLOCK = re.compile(r'```(?:json)?\s*(.*?)```', re.S)


def extract_json(text: str) -> Any:
    text = text.strip()
    for candidate in [text] + _JSON_BLOCK.findall(text):
        try:
            return json.loads(candidate)
        except Exception:
            pass
    starts = [i for i in (text.find('{'), text.find('[')) if i >= 0]
    if starts:
        start = min(starts)
        closer = '}' if text[start] == '{' else ']'
        end = text.rfind(closer)
        if end > start:
            return json.loads(text[start:end + 1])
    raise ValueError('no JSON object in reply')


def _tool_prompt(tools: list, tool_choice: Any) -> str:
    specs = []
    for t in tools:
        fn = t.get('function', t) if isinstance(t, dict) else convert_to_openai_tool(t)['function']
        specs.append({'name': fn.get('name'), 'description': fn.get('description', ''),
                      'parameters': fn.get('parameters', {})})
    forced = ''
    if isinstance(tool_choice, dict) and tool_choice.get('function'):
        forced = f'\nYou must call the tool "{tool_choice["function"]["name"]}".'
    elif tool_choice in ('required', 'any'):
        forced = '\nYou must call at least one tool.'
    return (
        '\n\n[Tools]\nYou can call these tools (JSON schema of each tool):\n'
        + json.dumps(specs, ensure_ascii=False)
        + '\n\nTo call one or more tools, reply with only a JSON object of the form '
        '{"tool_calls": [{"name": "<tool name>", "arguments": {...}}]} and nothing else. '
        'Independent calls may go in the same list. When you have what you need, reply to the user '
        'with plain text instead (no JSON).' + forced
    )


class BackboneChatModel(BaseChatModel):
    feature: str = 'default'

    @property
    def _llm_type(self) -> str:
        return 'halo-backbone'

    def bind_tools(self, tools, tool_choice=None, **kwargs):
        formatted = [t if isinstance(t, dict) else convert_to_openai_tool(t) for t in tools]
        return self.bind(tools=formatted, tool_choice=tool_choice, **kwargs)

    def with_structured_output(self, schema, *, include_raw: bool = False, **kwargs):
        return StructuredOutput(self, schema)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        tools = kwargs.get('tools')
        system, user = render(messages)
        if tools:
            user += _tool_prompt(tools, kwargs.get('tool_choice'))
        reply = BRIDGE.call(system, user, self.feature)
        message = AIMessage(content=reply)
        if tools:
            calls = None
            try:
                obj = extract_json(reply) if '"tool_calls"' in reply else None
                if isinstance(obj, dict) and isinstance(obj.get('tool_calls'), list):
                    calls = obj['tool_calls']
            except Exception:
                calls = None
            if calls:
                tool_calls = []
                for i, c in enumerate(calls):
                    args = c.get('arguments', c.get('args', {}))
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    tool_calls.append({'name': c.get('name'), 'args': args if isinstance(args, dict) else {},
                                       'id': f'call_{len(messages)}_{i}', 'type': 'tool_call'})
                message = AIMessage(content='', tool_calls=tool_calls)
        return ChatResult(generations=[ChatGeneration(message=message)])


class StructuredOutput(Runnable):
    """``llm.with_structured_output(Model)``: JSON schema in the prompt, pydantic validation out."""

    def __init__(self, model: BackboneChatModel, schema):
        self.model, self.schema = model, schema

    def bind(self, **kwargs):          # prompt-cache options are provider fields; nothing to bind
        return self

    def _messages(self, value) -> List[BaseMessage]:
        if isinstance(value, str):
            return [HumanMessage(content=value)]
        if hasattr(value, 'to_messages'):
            return value.to_messages()
        from langchain_core.messages import convert_to_messages
        return convert_to_messages(value)

    def invoke(self, input, config=None, **kwargs):
        system, user = render(self._messages(input))
        schema_json = json.dumps(self.schema.model_json_schema(), ensure_ascii=False)
        user += ('\n\nRespond with only a JSON object that conforms to this JSON schema (no prose, no code fence):\n'
                 + schema_json)
        reply = BRIDGE.call(system, user, self.model.feature)
        try:
            return self.schema.model_validate(extract_json(reply))
        except Exception as error:   # one repair turn, as a strict JSON mode would never return invalid JSON
            fix = BRIDGE.call(system, user + '\n\nYour previous reply was not valid for the schema ('
                              + str(error)[:300] + '). Reply again with only the JSON object.', self.model.feature)
            return self.schema.model_validate(extract_json(fix))

    async def ainvoke(self, input, config=None, **kwargs):
        return await asyncio.get_running_loop().run_in_executor(None, lambda: self.invoke(input, config, **kwargs))


# ---------------------------------------------------------------------------------------------
# embeddings
# ---------------------------------------------------------------------------------------------
class WindowedQuery(list):
    """A query vector that also carries one vector per sentence window of a long query.

    text-embedding-3-large reads up to 8k tokens; all-MiniLM-L6-v2 truncates at 256 word pieces.
    Omi embeds whole transcripts as queries (find_similar_action_items, the mentor's past-conversation
    search). To keep such a query meaningful, a long query is also embedded per window of about 40
    words, and the fake Pinecone index scores a stored vector by its best-matching window. A short
    query is a plain vector and is scored by cosine as usual.
    """
    windows: List[List[float]] = []


_SENTENCE = re.compile(r'(?<=[.!?])\s+|\n+')


def _windows(text: str, max_words: int = 40) -> List[str]:
    out, cur = [], []
    for sentence in (s.strip() for s in _SENTENCE.split(text or '')):
        if not sentence:
            continue
        words = sentence.split()
        if cur and len(cur) + len(words) > max_words:
            out.append(' '.join(cur))
            cur = []
        cur.extend(words)
        while len(cur) > max_words:
            out.append(' '.join(cur[:max_words]))
            cur = cur[max_words:]
    if cur:
        out.append(' '.join(cur))
    return out


class MiniLMEmbeddings:
    """Stands in for OpenAIEmbeddings(model='text-embedding-3-large')."""

    _model = None
    _lock = threading.Lock()

    @classmethod
    def model(cls):
        with cls._lock:
            if cls._model is None:
                from sentence_transformers import SentenceTransformer
                cls._model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', device='cpu')
        return cls._model

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        vecs = self.model().encode(list(texts), normalize_embeddings=True)
        return [v.tolist() for v in vecs]

    def embed_query(self, text: str) -> List[float]:
        vec = self.embed_documents([text])[0]
        windows = _windows(text)
        if len(windows) <= 1:
            return vec
        q = WindowedQuery(vec)
        q.windows = self.embed_documents(windows)
        return q

    async def aembed_query(self, text: str) -> List[float]:
        return self.embed_query(text)

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.embed_documents(texts)


EMBEDDINGS = MiniLMEmbeddings()
