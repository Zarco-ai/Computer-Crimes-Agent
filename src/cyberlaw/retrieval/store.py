"""The vector-store seam.

Everything downstream depends on this Protocol rather than on Pinecone, so
swapping to a local store is a config change and tests can run without a
network or an API key.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..schemas import Chunk, Retrieved


@runtime_checkable
class VectorStore(Protocol):
    """Minimal surface this project needs from a vector database."""

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> tuple[float, int]:
        """Store chunk vectors. Returns (usd_cost, write_units)."""
        ...

    def query(
        self,
        vector: list[float],
        top_k: int,
        *,
        kind: str | None = None,
        section: str | None = None,
    ) -> tuple[list[Retrieved], int]:
        """Nearest neighbours. Returns (hits, read_units)."""
        ...

    def stats(self) -> dict:
        """Describe the index/namespace, for `cyberlaw inspect`."""
        ...


class InMemoryStore:
    """Exact brute-force store used by tests and offline runs.

    Cosine similarity over 71 chunks is instant, so this doubles as a
    zero-cost local backend and as the parity reference for the Pinecone
    implementation.
    """

    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._vectors: list[list[float]] = []

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> tuple[float, int]:
        by_cite = {c.cite: i for i, c in enumerate(self._chunks)}
        for chunk, vec in zip(chunks, vectors):
            if chunk.cite in by_cite:
                idx = by_cite[chunk.cite]
                self._chunks[idx], self._vectors[idx] = chunk, vec
            else:
                by_cite[chunk.cite] = len(self._chunks)
                self._chunks.append(chunk)
                self._vectors.append(vec)
        return 0.0, 0

    def query(
        self,
        vector: list[float],
        top_k: int,
        *,
        kind: str | None = None,
        section: str | None = None,
    ) -> tuple[list[Retrieved], int]:
        import math

        def cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a)) or 1.0
            nb = math.sqrt(sum(y * y for y in b)) or 1.0
            return dot / (na * nb)

        scored = []
        for chunk, vec in zip(self._chunks, self._vectors):
            if kind and chunk.kind != kind:
                continue
            if section and chunk.section != section:
                continue
            scored.append((cosine(vector, vec), chunk))
        scored.sort(key=lambda x: -x[0])

        hits = [
            Retrieved(
                cite=c.cite,
                section=c.section,
                heading=c.heading,
                url=c.url,
                kind=c.kind,
                text=c.text,
                score=score,
            )
            for score, c in scored[:top_k]
        ]
        return hits, 0

    def stats(self) -> dict:
        return {"backend": "memory", "vectors": len(self._chunks)}
