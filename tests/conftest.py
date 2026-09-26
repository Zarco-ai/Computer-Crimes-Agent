"""Shared fixtures.

Every test here runs offline: parsing, chunking, the registry, the verifier,
and the deterministic tools need no API key and no network. That is the point
of keeping the embedding call behind a seam.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "data" / "raw" / "pe.33.htm"


@pytest.fixture(scope="session")
def chapter():
    from cyberlaw.ingestion.parse_html import parse_chapter

    if not HTML.exists():
        pytest.skip(f"source HTML missing: {HTML}")
    return parse_chapter(HTML)


@pytest.fixture(scope="session")
def chunks(chapter):
    from cyberlaw.ingestion.chunk import chunk_chapter

    return chunk_chapter(chapter)


@pytest.fixture(scope="session")
def registry(chapter):
    from cyberlaw.ingestion.registry import Registry

    return Registry.from_chapter(chapter)


@pytest.fixture(scope="session")
def corpus(chapter, chunks, registry):
    from cyberlaw.corpus import Corpus

    return Corpus(chapter=chapter, chunks=chunks, registry=registry)
