"""Token counting and USD cost accounting.

Note on a bug this module exists to prevent: ``sum(len(enc.encode(t)) for t
in text)`` iterates the *characters* of a string when ``text`` is a string
rather than a list, which silently inflates token counts. Every counter here
takes an explicit scalar-or-sequence and normalises first.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Iterable, Sequence

import tiktoken

from ..config import get_settings
from ..schemas import CostRecord


@lru_cache(maxsize=8)
def _encoding(model: str):
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        # Unknown/new model names fall back to the current OpenAI BPE.
        return tiktoken.get_encoding("o200k_base")


def _as_texts(text: str | Sequence[str] | None) -> list[str]:
    if text is None:
        return []
    if isinstance(text, str):
        return [text]
    return [t for t in text if t]


def count_tokens(text: str | Sequence[str] | None, model: str | None = None) -> int:
    """Count tokens in a string or a sequence of strings."""
    settings = get_settings()
    enc = _encoding(model or settings.chat_model)
    return sum(len(enc.encode(t)) for t in _as_texts(text))


def count_message_tokens(messages: Iterable[dict], model: str | None = None) -> int:
    """Approximate prompt tokens for a chat payload.

    Adds a small per-message overhead for role/delimiter tokens. This is an
    estimate for budgeting; the API's ``usage`` field is authoritative and is
    what :func:`cost_from_usage` uses when available.
    """
    settings = get_settings()
    enc = _encoding(model or settings.chat_model)
    total = 0
    for m in messages:
        total += 4  # role + delimiters
        for key, value in m.items():
            if isinstance(value, str):
                total += len(enc.encode(value))
            elif value is not None:
                total += len(enc.encode(json.dumps(value, default=str)))
    return total + 2


def embed_cost(text: str | Sequence[str]) -> tuple[float, int]:
    """Return (usd, tokens) for embedding the given text(s)."""
    settings = get_settings()
    tokens = count_tokens(text, model=settings.embed_model)
    return tokens / 1_000_000 * settings.price_embed_per_1m, tokens


def cost_from_usage(usage, *, read_units: int = 0) -> CostRecord:
    """Build a :class:`CostRecord` from an OpenAI ``usage`` object."""
    settings = get_settings()
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    return CostRecord(
        input_tokens=prompt,
        output_tokens=completion,
        input_cost=prompt / 1_000_000 * settings.price_input_per_1m,
        output_cost=completion / 1_000_000 * settings.price_output_per_1m,
        db_cost=read_units / 1_000_000 * settings.price_pinecone_read_per_1m_ru,
    )


def write_unit_cost(payload_bytes: int) -> tuple[float, int]:
    """Pinecone upsert cost. 1 KB == 1 write unit, with a 5 WU floor."""
    import math

    settings = get_settings()
    wu = max(5, math.ceil(payload_bytes / 1024))
    return wu / 1_000_000 * settings.price_pinecone_write_per_1m_wu, wu


def log_run(
    question: str,
    cost: CostRecord,
    *,
    status: str,
    steps: int,
    tools_used: Sequence[str] = (),
    prompt_version: str = "v2.0",
) -> None:
    """Append one JSONL record per agent run for later cost analysis."""
    settings = get_settings()
    settings.ensure_dirs()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt_version": prompt_version,
        "question": question,
        "status": status,
        "steps": steps,
        "tools_used": list(tools_used),
        "embed_tokens": cost.embed_tokens,
        "input_tokens": cost.input_tokens,
        "output_tokens": cost.output_tokens,
        "total_tokens": cost.total_tokens,
        "embed_cost": cost.embed_cost,
        "input_cost": cost.input_cost,
        "output_cost": cost.output_cost,
        "db_cost": cost.db_cost,
        "total_cost_usd": cost.total_cost,
    }
    with settings.query_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
