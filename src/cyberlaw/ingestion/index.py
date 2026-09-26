"""The ingest pipeline: HTML -> tree -> chunks + registry -> vectors.

Parsing and chunking are free and deterministic, so they always run. The
embedding/upsert step costs money, so it is opt-in via ``push=True`` and
reports what it spent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..config import get_settings
from ..schemas import Chapter, Chunk
from .chunk import chunk_chapter, write_chunks
from .parse_html import parse_chapter
from .registry import Registry


@dataclass
class IngestReport:
    sections: int = 0
    chunks: int = 0
    definitions: int = 0
    penalty_rungs: int = 0
    total_chunk_tokens: int = 0
    max_chunk_tokens: int = 0
    embed_tokens: int = 0
    embed_cost: float = 0.0
    upsert_cost: float = 0.0
    write_units: int = 0
    pushed: bool = False
    namespace: str = ""
    artifacts: list[str] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return self.embed_cost + self.upsert_cost


def build_artifacts(html_path: str | Path | None = None) -> tuple[Chapter, list[Chunk], Registry]:
    """Parse and chunk the statute. No API calls, no cost."""
    settings = get_settings()
    chapter = parse_chapter(html_path or settings.raw_html)
    chunks = chunk_chapter(chapter)
    registry = Registry.from_chapter(chapter)
    return chapter, chunks, registry


def ingest(
    html_path: str | Path | None = None,
    *,
    push: bool = False,
    replace: bool = True,
    backend: str = "pinecone",
) -> IngestReport:
    """Run the full pipeline.

    Args:
        html_path: source HTML; defaults to ``data/raw/pe.33.htm``.
        push: embed the chunks and upsert them to the vector store.
        replace: clear the target namespace first, so removed provisions do
            not linger as stale vectors.
        backend: ``"pinecone"`` or ``"memory"``.
    """
    settings = get_settings()
    settings.ensure_dirs()

    chapter, chunks, registry = build_artifacts(html_path)

    # Persist the deterministic artifacts.
    Path(settings.chapter_json).write_text(
        json.dumps(chapter.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_chunks(chunks, settings.chunks_jsonl)
    registry.save(settings.registry_json)

    tokens = [c.token_count for c in chunks]
    report = IngestReport(
        sections=len(chapter.sections),
        chunks=len(chunks),
        definitions=len(registry.definitions),
        penalty_rungs=sum(len(p.rungs) for p in registry.penalties),
        total_chunk_tokens=sum(tokens),
        max_chunk_tokens=max(tokens) if tokens else 0,
        namespace=settings.pinecone_namespace,
        artifacts=[
            str(settings.chapter_json),
            str(settings.chunks_jsonl),
            str(settings.registry_json),
        ],
    )

    if not push:
        return report

    from ..retrieval.embeddings import embed_texts

    if backend == "pinecone":
        from ..retrieval.pinecone_store import PineconeStore

        store = PineconeStore()
        if replace:
            store.delete_namespace()
    else:
        from ..retrieval.store import InMemoryStore

        store = InMemoryStore()

    vectors, cost = embed_texts([c.text for c in chunks])
    upsert_cost, write_units = store.upsert(chunks, vectors)

    report.embed_tokens = cost.embed_tokens
    report.embed_cost = cost.embed_cost
    report.upsert_cost = upsert_cost
    report.write_units = write_units
    report.pushed = True
    return report
