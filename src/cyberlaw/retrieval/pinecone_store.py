"""Pinecone implementation of :class:`~cyberlaw.retrieval.store.VectorStore`.

Writes to a dedicated namespace (default ``ch33-atomic-v2``) so the previous
whole-section vectors in ``__default__`` survive as a rollback and as an A/B
baseline for the eval harness.
"""

from __future__ import annotations

import json
from functools import lru_cache

from pinecone import Pinecone

from ..config import get_settings
from ..observability.costs import write_unit_cost
from ..schemas import Chunk, Retrieved


@lru_cache(maxsize=1)
def _index():
    settings = get_settings()
    if not settings.pinecone_api_key:
        raise RuntimeError("pinecone_apikey is not set (see .env.example).")
    pc = Pinecone(api_key=settings.pinecone_api_key, pool_threads=30)
    return pc.Index(settings.pinecone_index)


def _batched(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


class PineconeStore:
    def __init__(self, namespace: str | None = None):
        settings = get_settings()
        self.namespace = namespace or settings.pinecone_namespace
        self.index = _index()

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> tuple[float, int]:
        payload = [
            {"id": chunk.id, "values": vector, "metadata": chunk.as_metadata()}
            for chunk, vector in zip(chunks, vectors)
        ]
        total_cost = 0.0
        total_wu = 0
        for batch in _batched(payload, 100):
            cost, wu = write_unit_cost(len(json.dumps(batch).encode("utf-8")))
            total_cost += cost
            total_wu += wu
            self.index.upsert(vectors=batch, namespace=self.namespace)
        return total_cost, total_wu

    def query(
        self,
        vector: list[float],
        top_k: int,
        *,
        kind: str | None = None,
        section: str | None = None,
    ) -> tuple[list[Retrieved], int]:
        flt: dict = {}
        if kind:
            flt["kind"] = {"$eq": kind}
        if section:
            flt["section"] = {"$eq": section}

        response = self.index.query(
            vector=vector,
            top_k=top_k,
            namespace=self.namespace,
            include_metadata=True,
            filter=flt or None,
        )

        hits: list[Retrieved] = []
        for match in response.get("matches", []) or []:
            md = match.get("metadata") or {}
            hits.append(
                Retrieved(
                    cite=md.get("cite", match.get("id", "")),
                    section=md.get("section", ""),
                    heading=md.get("heading", ""),
                    url=md.get("url", ""),
                    kind=md.get("kind", "other"),
                    text=md.get("text", ""),
                    score=float(match.get("score", 0.0)),
                )
            )
        read_units = int((response.get("usage") or {}).get("read_units", 0) or 0)
        return hits, read_units

    def delete_namespace(self) -> None:
        """Clear the namespace before a fresh ingest."""
        try:
            self.index.delete(delete_all=True, namespace=self.namespace)
        except Exception:
            # A namespace that does not exist yet is not an error.
            pass

    def stats(self) -> dict:
        settings = get_settings()
        raw = self.index.describe_index_stats()
        namespaces = dict(raw.get("namespaces", {}) or {})
        mine = namespaces.get(self.namespace, {}) or {}
        return {
            "backend": "pinecone",
            "index": settings.pinecone_index,
            "namespace": self.namespace,
            "vectors_in_namespace": mine.get("vector_count", 0),
            "dimension": raw.get("dimension"),
            "all_namespaces": {k: v.get("vector_count", 0) for k, v in namespaces.items()},
        }
