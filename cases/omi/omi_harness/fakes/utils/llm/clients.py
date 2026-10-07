"""Fake of backend/utils/llm/clients.py: every model client is the HALO backbone.

get_llm(feature, ...) returns a BackboneChatModel for that feature (the feature name only labels the
call in the cache tag). Embeddings are all-MiniLM-L6-v2 on CPU. Token counting uses a 4-characters
per token estimate because tiktoken would download its encoding at first use.
"""
from typing import Any, List, Optional

from langchain_core.output_parsers import PydanticOutputParser

from models.structured_extraction import StructuredExtraction
from omi_harness.llm_bridge import BackboneChatModel, EMBEDDINGS

ANTHROPIC_AGENT_MODEL = 'halo-backbone'
ANTHROPIC_AGENT_COMPLEX_MODEL = 'halo-backbone'
anthropic_client = None
embeddings = EMBEDDINGS
parser = PydanticOutputParser(pydantic_object=StructuredExtraction)


def get_llm(feature: str, streaming: bool = False, cache_key: Optional[str] = None,
            prompt_cache_options: Optional[dict] = None, request_timeout: Optional[float] = None,
            max_retries: Optional[int] = None):
    return BackboneChatModel(feature=feature)


def get_llm_gateway_chat_structured(streaming: bool = False, cache_key: Optional[str] = None,
                                    request_timeout: Optional[float] = None):
    return BackboneChatModel(feature='chat_extraction')


def get_model(feature: str) -> str:
    return 'halo-backbone'


def num_tokens_from_string(string: str) -> int:
    return max(1, len(string or '') // 4)


def generate_embedding(content: str) -> List[float]:
    # upstream: embeddings.embed_documents([content])[0]; a query-side long text keeps its windows
    return embeddings.embed_query(content)


def gemini_embed_query(text: str) -> List[float]:
    return embeddings.embed_query(text)


llm_mini = BackboneChatModel(feature='learnings')
