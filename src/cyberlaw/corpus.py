"""In-process access to the ingested artifacts.

Loads the three files produced by ``cyberlaw ingest`` once per process:

* ``chapter33.json`` -- the parsed provision tree (for verbatim section text)
* ``chunks.jsonl``   -- the embedded units (for offline/local search)
* ``registry.json``  -- definition and penalty tables (for exact lookups)

Keeping these behind one object means the tools never touch the filesystem
directly and can be unit-tested against a hand-built corpus.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .config import get_settings
from .ingestion.chunk import read_chunks
from .ingestion.registry import Registry
from .schemas import Chapter, Chunk, Section, normalize_section


class CorpusNotBuilt(RuntimeError):
    """Raised when the processed artifacts are missing."""


class Corpus:
    def __init__(self, chapter: Chapter, chunks: list[Chunk], registry: Registry):
        self.chapter = chapter
        self.chunks = chunks
        self.registry = registry
        self._by_cite = {c.cite: c for c in chunks}

    # --- accessors -------------------------------------------------------
    def section(self, number: str) -> Section | None:
        return self.chapter.section(number)

    def chunk(self, cite: str) -> Chunk | None:
        return self._by_cite.get(cite)

    def section_numbers(self) -> list[str]:
        return [s.number for s in self.chapter.sections]

    def toc(self) -> list[dict]:
        """Chapter map: cheap grounding that prevents section mix-ups."""
        out = []
        for s in self.chapter.sections:
            ladder = self.registry.ladder(s.number)
            out.append(
                {
                    "section": s.number,
                    "heading": s.heading,
                    "url": s.url,
                    "subsections": [p.marker for p in s.provisions],
                    "has_penalty_ladder": bool(ladder and ladder.rungs),
                    # Compare the bare section number, not a string prefix:
                    # "33.021(a)(1)".startswith("33.02") is true, which would
                    # credit § 33.02 with § 33.021's definitions.
                    "defines_terms": sorted(
                        {
                            d.term
                            for d in self.registry.definitions
                            if d.cite.split("(")[0] == s.number
                        }
                    ),
                }
            )
        return out

    def cross_references(self) -> set[str]:
        """Non-Chapter-33 sections that Chapter 33's own text cites.

        Chapter 33 borrows definitions from elsewhere (§ 31.01 deception,
        § 32.51 identifying information, § 15.01 criminal attempt, ...). The
        verifier allows these to be quoted, because they appear verbatim in
        retrieved text, while still rejecting citations to chapters the agent
        cannot have read.
        """
        import re

        refs: set[str] = set()
        blob = "\n".join(
            [s.full_text() for s in self.chapter.sections]
            + [n for s in self.chapter.sections for n in s.editorial_notes]
        )
        for m in re.finditer(r"(?:§+\s*|Sec\.\s*|Section\s+)(\d+\.\d+)", blob):
            if not m.group(1).startswith("33."):
                refs.add(m.group(1))
        return refs

    # --- loading ---------------------------------------------------------
    @classmethod
    def load(cls) -> "Corpus":
        settings = get_settings()
        missing = [
            p
            for p in (settings.chapter_json, settings.chunks_jsonl, settings.registry_json)
            if not Path(p).exists()
        ]
        if missing:
            names = ", ".join(Path(p).name for p in missing)
            raise CorpusNotBuilt(
                f"Missing processed artifacts: {names}. Run `cyberlaw ingest` first."
            )
        chapter = Chapter.model_validate(
            json.loads(Path(settings.chapter_json).read_text(encoding="utf-8"))
        )
        return cls(
            chapter=chapter,
            chunks=read_chunks(settings.chunks_jsonl),
            registry=Registry.load(settings.registry_json),
        )


@lru_cache(maxsize=1)
def get_corpus() -> Corpus:
    """Cached corpus for the life of the process."""
    return Corpus.load()


def section_text(corpus: Corpus, number: str) -> str | None:
    """Verbatim full text of a section, or None if it does not exist."""
    sec = corpus.section(normalize_section(number))
    if sec is None:
        return None
    return f"{sec.label}\n{sec.full_text()}"
