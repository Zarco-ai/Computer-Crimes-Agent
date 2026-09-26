"""Query-time retrieval: embed, search, optionally expand to full section."""

from __future__ import annotations

from ..config import get_settings
from ..corpus import Corpus, get_corpus
from ..schemas import CostRecord, Retrieved
from .embeddings import embed_query
from .store import VectorStore


def build_store(backend: str | None = None) -> VectorStore:
    """Instantiate the configured backend.

    ``"memory"`` embeds the local chunks on first use -- handy for offline
    experiments and for parity-checking the Pinecone path.
    """
    backend = (backend or "pinecone").lower()
    if backend == "pinecone":
        from .pinecone_store import PineconeStore

        return PineconeStore()
    if backend == "memory":
        from .embeddings import embed_texts
        from .store import InMemoryStore

        store = InMemoryStore()
        corpus = get_corpus()
        vectors, _ = embed_texts([c.text for c in corpus.chunks])
        store.upsert(corpus.chunks, vectors)
        return store
    raise ValueError(f"Unknown store backend: {backend!r}")


class Retriever:
    """Vector search over Chapter 33 with parent-section expansion."""

    def __init__(self, store: VectorStore, corpus: Corpus | None = None):
        self.store = store
        self.corpus = corpus or get_corpus()

    def search(
        self,
        query: str,
        top_k: int | None = None,
        *,
        kind: str | None = None,
        section: str | None = None,
        expand_section: bool = False,
    ) -> tuple[list[Retrieved], CostRecord]:
        settings = get_settings()
        top_k = top_k or settings.top_k

        vector, cost = embed_query(query)
        hits, read_units = self.store.query(
            vector, top_k, kind=kind, section=section
        )
        cost = cost.merge(
            CostRecord(
                db_cost=read_units
                / 1_000_000
                * settings.price_pinecone_read_per_1m_ru
            )
        )

        if expand_section:
            hits = self._expand(hits)
        return hits, cost

    def _expand(self, hits: list[Retrieved]) -> list[Retrieved]:
        """Replace each hit with its full parent section, de-duplicated.

        Precision at search time, completeness at read time: the atomic chunk
        wins the match, then the agent reads the whole section around it.
        """
        seen: set[str] = set()
        out: list[Retrieved] = []
        for hit in hits:
            if hit.section in seen:
                continue
            seen.add(hit.section)
            sec = self.corpus.section(hit.section)
            if sec is None:
                out.append(hit)
                continue
            out.append(
                Retrieved(
                    cite=sec.number,
                    section=sec.number,
                    heading=sec.heading,
                    url=sec.url,
                    kind=hit.kind,
                    text=f"{sec.label}\n{sec.full_text()}",
                    score=hit.score,
                )
            )
        return out
