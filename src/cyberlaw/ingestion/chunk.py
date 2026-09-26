"""Chunking strategy: atomic subsection units with parent-section expansion.

One chunk == one top-level provision of a section:

* Sec. 33.01  -> one chunk per numbered definition, 23 chunks
                 (16 numbers plus the -a/-b/-c insertions, e.g. (10-a))
* Sec. 33.02  -> one chunk per subsection: (a) (b) (b-1) (b-2) (c) (d) (e) (f)
* Sec. 33.03  -> a single chunk, because the section has no markers at all

Nested children ((A), (i), ...) are rolled into their top-level parent rather
than split out. Splitting them would produce fragments like "the government;
or" whose embedding carries no usable signal, and whose citation would be
meaningless on its own.

Every chunk carries ``parent_section`` so the retriever can expand a hit to
the full section when the agent needs surrounding context -- precision at
search time, completeness at read time.

Why not a fixed-size recursive splitter: it cuts mid-provision, so a single
chunk can straddle two legal rules and its citation becomes ambiguous. For
statutory text the document's own hierarchy is a better boundary than any
token window.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..observability.costs import count_tokens
from ..schemas import Chapter, Chunk, Section
from .parse_html import _classify, _quoted_terms


def _context_header(section: Section, cite: str, kind: str, terms: list[str]) -> str:
    """Build the orienting first line that gets embedded with the provision.

    Retrieval quality on legal text depends heavily on this. A bare
    ``'"Access" means to approach...'`` does not obviously answer "what is the
    legal definition of access?", but a chunk that opens with
    ``Definition of "Access"`` does.
    """
    base = f"Tex. Penal Code § {cite} — {section.heading.title()}"
    if kind == "definition" and terms:
        quoted = ", ".join(f'"{t}"' for t in terms)
        return f"Statutory definition of {quoted}. {base}"
    if kind == "penalty":
        return f"Offense grade / punishment classification. {base}"
    if kind == "offense":
        return f"Elements of the offense. {base}"
    if kind == "defense":
        return f"Defense to prosecution. {base}"
    return base


def chunk_section(section: Section) -> list[Chunk]:
    """Produce atomic chunks for one section."""
    chunks: list[Chunk] = []

    # Sections such as 33.03 (DEFENSES) and 33.04 carry their whole body in
    # the header paragraph, so they have no marked provisions. Emit the
    # section itself as one chunk rather than dropping it.
    if not section.provisions:
        text = section.full_text()
        if not text.strip():
            return []
        kind = _classify(text, section.number, is_definition_scope=False)
        header = _context_header(section, section.number, kind, [])
        body = f"{header}\n\n{text}"
        chunks.append(
            Chunk(
                id=section.number,
                cite=section.number,
                section=section.number,
                heading=section.heading,
                url=section.url,
                kind=kind,
                text=body,
                parent_section=section.number,
                token_count=count_tokens(body),
            )
        )
        return chunks

    for prov in section.provisions:
        terms = _quoted_terms(prov.text) if prov.kind == "definition" else []
        header = _context_header(section, prov.cite, prov.kind, terms)

        # Keep the section lead-in ("In this chapter:") so a definition chunk
        # states the scope it applies to.
        parts = [header]
        if section.lead_in.strip():
            parts.append(section.lead_in.strip())
        parts.append(prov.rendered())
        body = "\n".join(parts)

        chunks.append(
            Chunk(
                id=prov.cite,
                cite=prov.cite,
                section=section.number,
                heading=section.heading,
                url=section.url,
                kind=prov.kind,
                text=body,
                parent_section=section.number,
                defined_terms=terms,
                token_count=count_tokens(body),
            )
        )
    return chunks


def chunk_chapter(chapter: Chapter) -> list[Chunk]:
    """Produce chunks for every section in the chapter."""
    out: list[Chunk] = []
    for section in chapter.sections:
        out.extend(chunk_section(section))
    return out


def write_chunks(chunks: list[Chunk], path: str | Path) -> None:
    """Persist chunks as JSONL -- the contract for everything downstream."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c.model_dump(), ensure_ascii=False) + "\n")


def read_chunks(path: str | Path) -> list[Chunk]:
    """Load chunks written by :func:`write_chunks`."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        return [Chunk.model_validate_json(line) for line in fh if line.strip()]
