"""The agent's five tools.

Only ``search_statute`` is a semantic search. The other four are exact
lookups over the parsed corpus, because the questions they answer have exact
answers:

* ``look_up_definition`` -- Chapter 33 has a closed list of defined terms.
* ``penalty_lookup``     -- each offence states its own grading ladder.
* ``get_section``        -- verbatim text of a numbered section.
* ``list_sections``      -- the chapter map.

Routing deterministic questions away from the embeddings is what stops the
near-miss failure this project was rebuilt to fix: a whole-section index
answered "what is the legal definition of 'Access'?" with § 33.02(a).
"""

from __future__ import annotations

from ..corpus import Corpus, get_corpus
from ..retrieval.retriever import Retriever
from ..schemas import normalize_section
from .base import Tool, ToolResult

DISCLAIMER_HINT = (
    "Statutory text only. Grading depends on facts a court decides."
)


# --------------------------------------------------------------------------
# 1. Semantic search
# --------------------------------------------------------------------------
def make_search_statute(retriever: Retriever) -> Tool:
    def search_statute(
        query: str,
        top_k: int = 6,
        kind: str | None = None,
        expand_section: bool = False,
    ) -> ToolResult:
        hits, cost = retriever.search(
            query, top_k=top_k, kind=kind, expand_section=expand_section
        )
        if not hits:
            return ToolResult(
                content="No provisions in Chapter 33 matched that query.",
                summary="no matches",
                cost=cost,
            )
        blocks = [
            f"[§ {h.cite}] ({h.kind}, score={h.score:.3f})\n{h.text}" for h in hits
        ]
        return ToolResult(
            content="\n\n---\n\n".join(blocks),
            cites=[h.cite for h in hits],
            sources=hits,
            cost=cost,
            summary=f"{len(hits)} hits: " + ", ".join(h.cite for h in hits),
        )

    return Tool(
        name="search_statute",
        description=(
            "Semantic search over Texas Penal Code Chapter 33 (Computer Crimes). "
            "Use for open-ended or scenario questions where the relevant provision "
            "is not known in advance. Do NOT use it to look up a defined term or a "
            "penalty grade -- use look_up_definition or penalty_lookup, which are exact."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Conduct or concept to search for, in plain language.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of provisions to return (default 6).",
                    "minimum": 1,
                    "maximum": 15,
                },
                "kind": {
                    "type": "string",
                    "enum": ["offense", "penalty", "definition", "defense", "procedure"],
                    "description": "Optional filter on provision type.",
                },
                "expand_section": {
                    "type": "boolean",
                    "description": (
                        "Return each hit's entire section instead of the matched "
                        "subsection. Use when you need surrounding context."
                    ),
                },
            },
            "required": ["query"],
        },
        fn=search_statute,
    )


# --------------------------------------------------------------------------
# 2. Definitions (deterministic)
# --------------------------------------------------------------------------
def make_look_up_definition(corpus: Corpus) -> Tool:
    def look_up_definition(term: str) -> ToolResult:
        hits = corpus.registry.lookup_definition(term)
        if not hits:
            available = ", ".join(corpus.registry.terms())
            return ToolResult(
                content=(
                    f'Chapter 33 does not define "{term}".\n'
                    f"Terms it does define: {available}"
                ),
                summary=f"no definition for {term!r}",
            )

        blocks = []
        for d in hits:
            scope = (
                "applies throughout Chapter 33"
                if d.scope == "chapter"
                else f"applies only within § {d.scope}"
            )
            blocks.append(f'[§ {d.cite}] "{d.term}" ({scope})\n{d.text}')
        return ToolResult(
            content="\n\n".join(blocks),
            cites=[d.cite for d in hits],
            summary=f"{term!r} -> " + ", ".join(f"{d.term}@{d.cite}" for d in hits),
        )

    return Tool(
        name="look_up_definition",
        description=(
            "Exact lookup of a term defined in Chapter 33 (e.g. 'owner', 'effective "
            "consent', 'property', 'access', 'ransomware'). Returns the verbatim "
            "definition, its citation, and whether it applies chapter-wide or only "
            "within one section. Always prefer this over search_statute for terms. "
            "If the term is not defined, it says so and lists the terms that are."
        ),
        parameters={
            "type": "object",
            "properties": {
                "term": {
                    "type": "string",
                    "description": "The term to define, without quotes.",
                }
            },
            "required": ["term"],
        },
        fn=look_up_definition,
    )


# --------------------------------------------------------------------------
# 3. Penalties (deterministic)
# --------------------------------------------------------------------------
def make_penalty_lookup(corpus: Corpus) -> Tool:
    def penalty_lookup(section: str, aggregate_amount: float | None = None) -> ToolResult:
        number = normalize_section(section)
        sec = corpus.section(number)
        if sec is None:
            return ToolResult(
                content=(
                    f"Chapter 33 has no section {section!r}. Sections are: "
                    + ", ".join(corpus.section_numbers())
                ),
                summary=f"no such section {section!r}",
            )

        ladder = corpus.registry.ladder(number)
        if ladder is None or not (ladder.rungs or ladder.notes):
            return ToolResult(
                content=(
                    f"§ {number} ({sec.heading}) states no offence grade. It is not "
                    "a penalty-bearing section."
                ),
                cites=[number],
                summary=f"{number} has no grading",
            )

        lines = [f"Offence grades stated in § {number} ({sec.heading}):"]
        for rung in ladder.rungs:
            if aggregate_amount is not None and not _amount_matches(rung, aggregate_amount):
                continue
            # Flag rungs the amount cannot speak to, so a filtered list is not
            # mistaken for "these all apply at this dollar figure".
            unpriced = (
                " [not graded by dollar amount]"
                if aggregate_amount is not None
                and rung.min_amount is None
                and rung.max_amount is None
                else ""
            )
            lines.append(
                f"\n- {rung.grade.upper()} — § {rung.cite}{unpriced}\n  {rung.condition}"
            )
        for note in ladder.notes:
            lines.append(f"\n- (related) {note}")

        if aggregate_amount is not None:
            matched = [r for r in ladder.rungs if _amount_matches(r, aggregate_amount)]
            lines.insert(
                1,
                f"\nFiltered to rungs whose stated amount window contains "
                f"${aggregate_amount:,.2f} ({len(matched)} of {len(ladder.rungs)}).",
            )

        # Punishment ranges (jail time, fines) are set by Penal Code Chapter
        # 12, which is outside this corpus. Saying so is the honest answer;
        # inventing "180 days to 2 years" would be exactly the failure this
        # system is built to prevent.
        lines.append(
            "\nNOTE: Chapter 33 assigns the offence *grade* only. The confinement "
            "and fine ranges for each grade are set by Penal Code Chapter 12, "
            "which is NOT in this corpus — do not state specific jail terms or "
            "fine amounts."
        )
        return ToolResult(
            content="\n".join(lines),
            cites=[r.cite for r in ladder.rungs] + [number],
            summary=f"{number}: {len(ladder.rungs)} rungs",
        )

    return Tool(
        name="penalty_lookup",
        description=(
            "Exact lookup of the offence grades (Class C/B/A misdemeanour, state "
            "jail felony, felony of the first/second/third degree) stated by a "
            "Chapter 33 section, with the condition and citation for each rung. "
            "Optionally filter by an aggregate dollar amount. Returns the grade "
            "only -- confinement and fine ranges live in Penal Code Chapter 12, "
            "which is not in this corpus."
        ),
        parameters={
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Section number, e.g. '33.02' or '33.023'.",
                },
                "aggregate_amount": {
                    "type": "number",
                    "description": (
                        "Optional loss amount in USD; filters to rungs whose "
                        "stated window contains it."
                    ),
                },
            },
            "required": ["section"],
        },
        fn=penalty_lookup,
    )


def _amount_matches(rung, amount: float) -> bool:
    """True if a rung's stated amount window contains ``amount``.

    Rungs with no stated window (conditions that do not turn on money) always
    match, because the amount cannot rule them out.
    """
    if rung.min_amount is None and rung.max_amount is None:
        return True
    if rung.min_amount is not None and amount < rung.min_amount:
        return False
    if rung.max_amount is not None and amount >= rung.max_amount:
        return False
    return True


# --------------------------------------------------------------------------
# 4. Verbatim section text (deterministic)
# --------------------------------------------------------------------------
def make_get_section(corpus: Corpus) -> Tool:
    def get_section(section: str) -> ToolResult:
        number = normalize_section(section)
        sec = corpus.section(number)
        if sec is None:
            return ToolResult(
                content=(
                    f"Chapter 33 has no section {section!r}. Sections are: "
                    + ", ".join(corpus.section_numbers())
                ),
                summary=f"no such section {section!r}",
            )
        body = [f"{sec.label}\n{sec.full_text()}"]
        if sec.editorial_notes:
            body.append("Editorial notes: " + " ".join(sec.editorial_notes))
        return ToolResult(
            content="\n\n".join(body),
            cites=[sec.number],
            summary=f"full text of {sec.number}",
        )

    return Tool(
        name="get_section",
        description=(
            "Return the complete verbatim text of one Chapter 33 section by number "
            "(e.g. '33.02'). Use when you know the section and need its exact "
            "wording, elements, or defences."
        ),
        parameters={
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Section number, e.g. '33.02'.",
                }
            },
            "required": ["section"],
        },
        fn=get_section,
    )


# --------------------------------------------------------------------------
# 5. Chapter map (deterministic)
# --------------------------------------------------------------------------
def make_list_sections(corpus: Corpus) -> Tool:
    def list_sections() -> ToolResult:
        lines = ["Texas Penal Code, Title 7, Chapter 33 — COMPUTER CRIMES:"]
        for entry in corpus.toc():
            flags = []
            if entry["has_penalty_ladder"]:
                flags.append("has offence grades")
            if entry["defines_terms"]:
                flags.append(f"defines {len(entry['defines_terms'])} term(s)")
            suffix = f" [{'; '.join(flags)}]" if flags else ""
            subs = ", ".join(f"({m})" for m in entry["subsections"]) or "no subsections"
            lines.append(f"- § {entry['section']} {entry['heading']}{suffix}\n    {subs}")
        return ToolResult(
            content="\n".join(lines),
            cites=[e["section"] for e in corpus.toc()],
            summary=f"{len(corpus.section_numbers())} sections",
        )

    return Tool(
        name="list_sections",
        description=(
            "List every section of Chapter 33 with its heading, subsections, and "
            "whether it carries offence grades or definitions. Cheap and exact -- "
            "use it first to orient yourself, and to confirm a section number "
            "before citing it."
        ),
        parameters={"type": "object", "properties": {}},
        fn=list_sections,
    )


# --------------------------------------------------------------------------
def build_tools(retriever: Retriever | None = None, corpus: Corpus | None = None):
    """Assemble the registry the agent is given."""
    from .base import ToolRegistry

    corpus = corpus or get_corpus()
    if retriever is None:
        from ..retrieval.retriever import build_store

        retriever = Retriever(build_store(), corpus)

    return ToolRegistry(
        [
            make_search_statute(retriever),
            make_look_up_definition(corpus),
            make_penalty_lookup(corpus),
            make_get_section(corpus),
            make_list_sections(corpus),
        ]
    )
