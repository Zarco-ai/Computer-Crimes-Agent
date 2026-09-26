"""Embedding calls with honest token accounting."""

from __future__ import annotations

from functools import lru_cache
from typing import Sequence

from openai import OpenAI

from ..config import get_settings
from ..observability.costs import embed_cost
from ..schemas import CostRecord


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set (see .env.example).")
    return OpenAI(api_key=settings.openai_api_key)


def embed_texts(texts: Sequence[str]) -> tuple[list[list[float]], CostRecord]:
    """Embed a batch of documents."""
    settings = get_settings()
    texts = list(texts)
    if not texts:
        return [], CostRecord()
    usd, tokens = embed_cost(texts)
    response = _client().embeddings.create(input=texts, model=settings.embed_model)
    vectors = [item.embedding for item in response.data]
    return vectors, CostRecord(embed_tokens=tokens, embed_cost=usd)


def embed_query(text: str) -> tuple[list[float], CostRecord]:
    """Embed a single query string."""
    vectors, cost = embed_texts([text])
    return vectors[0], cost
