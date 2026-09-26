"""Typed data contracts shared across ingestion, retrieval, tools, and agent.

Citations are the backbone of this system, so they are modelled explicitly
rather than passed around as bare strings. A ``Provision.cite`` such as
``33.02(b-1)(2)(A)(i)`` is the unit of truth the verifier checks against.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# What kind of legal content a provision carries. Drives chunk metadata and
# lets the penalty tool find ladders without an LLM call.
ProvisionKind = Literal[
    "definition",  # 33.01, and section-scoped "In this section" definitions
    "offense",  # "A person commits an offense if ..."
    "penalty",  # "An offense under Subsection (a) is a ..."
    "defense",  # affirmative defenses / defenses to prosecution
    "procedure",  # venue, prosecution, AG assistance
    "other",
]


class Provision(BaseModel):
    """One addressable node of the statute tree."""

    cite: str  # "33.02(b-1)(2)(A)"
    section: str  # "33.02"
    # Marker path from the section root, e.g. ["b-1", "2", "A"].
    path: list[str] = Field(default_factory=list)
    marker: str = ""  # "b-1" -- this node's own marker
    depth: int = 0  # 0 = section body, 1 = (a), 2 = (1), 3 = (A), 4 = (i)
    text: str  # this node's own text, marker stripped
    kind: ProvisionKind = "other"
    children: list["Provision"] = Field(default_factory=list)

    def rendered(self, include_marker: bool = True) -> str:
        """Flatten this provision and its descendants back to statute text."""
        head = f"({self.marker})  {self.text}" if (include_marker and self.marker) else self.text
        parts = [head] if head.strip() else []
        parts.extend(c.rendered(include_marker=True) for c in self.children)
        return "\n".join(p for p in parts if p.strip())

    def walk(self):
        """Depth-first iteration over self and all descendants."""
        yield self
        for child in self.children:
            yield from child.walk()


class Section(BaseModel):
    """A single statute section, e.g. Sec. 33.02."""

    number: str  # "33.02"
    heading: str  # "BREACH OF COMPUTER SECURITY"
    url: str
    lead_in: str = ""  # text before the first marker ("In this chapter:")
    provisions: list[Provision] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)
    editorial_notes: list[str] = Field(default_factory=list)

    @property
    def cite(self) -> str:
        return self.number

    @property
    def label(self) -> str:
        return f"Sec. {self.number}. {self.heading}"

    def full_text(self) -> str:
        body = "\n".join(p.rendered() for p in self.provisions)
        return "\n".join(x for x in (self.lead_in, body) if x.strip())

    def find(self, cite: str) -> Provision | None:
        for p in self.provisions:
            for node in p.walk():
                if node.cite == cite:
                    return node
        return None


class Chapter(BaseModel):
    """The whole parsed corpus."""

    code: str = "Penal Code"
    title: str = "TITLE 7. OFFENSES AGAINST PROPERTY"
    chapter: str = "CHAPTER 33. COMPUTER CRIMES"
    sections: list[Section] = Field(default_factory=list)

    def section(self, number: str) -> Section | None:
        number = normalize_section(number)
        return next((s for s in self.sections if s.number == number), None)


class Chunk(BaseModel):
    """An embedding-ready unit of retrieval.

    One chunk == one top-level subsection (or one numbered definition), with
    its nested children rolled in and its section lead-in prepended for
    context. ``parent_section`` enables whole-section expansion after a hit.
    """

    id: str  # "33.01(10)" -- also the vector id
    cite: str  # citation shown to the user
    section: str  # "33.01"
    heading: str  # "DEFINITIONS"
    url: str
    kind: ProvisionKind
    text: str  # what gets embedded
    parent_section: str  # section number, for expansion
    # Term this chunk defines, when kind == "definition". Lets the retriever
    # and the definition tool share one artifact.
    defined_terms: list[str] = Field(default_factory=list)
    token_count: int = 0

    def as_metadata(self) -> dict:
        """Pinecone metadata must be flat scalars/lists of strings."""
        return {
            "cite": self.cite,
            "section": self.section,
            "heading": self.heading,
            "url": self.url,
            "kind": self.kind,
            "text": self.text,
            "parent_section": self.parent_section,
            "defined_terms": self.defined_terms,
            "token_count": self.token_count,
        }


class Retrieved(BaseModel):
    """A scored search hit."""

    cite: str
    section: str
    heading: str
    url: str
    kind: str
    text: str
    score: float

    def citation_line(self) -> str:
        return f"Tex. Penal Code § {self.cite} ({self.heading.title()})"


class Definition(BaseModel):
    """A statutory definition, resolved deterministically."""

    term: str
    cite: str
    text: str
    # "chapter" = applies to all of Ch. 33; otherwise the section it is
    # scoped to, e.g. "33.021". This distinction is legally load-bearing.
    scope: str
    url: str


class PenaltyRung(BaseModel):
    """One rung of an offense-grading ladder."""

    grade: str  # "state jail felony"
    cite: str  # "33.02(b-2)(4)"
    condition: str  # verbatim condition text
    min_amount: float | None = None  # aggregate-amount floor, if stated
    max_amount: float | None = None  # aggregate-amount ceiling, if stated


class PenaltyLadder(BaseModel):
    """All grading provisions for one section."""

    section: str
    heading: str
    url: str
    rungs: list[PenaltyRung] = Field(default_factory=list)
    # Grading text that names a grade without a parseable condition.
    notes: list[str] = Field(default_factory=list)


class ToolCallRecord(BaseModel):
    """One step of the agent's trajectory, kept for evals and the UI."""

    step: int
    name: str
    arguments: dict
    result_summary: str
    cites_surfaced: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    error: str | None = None


class CostRecord(BaseModel):
    """Token and dollar accounting for one agent run."""

    embed_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    embed_cost: float = 0.0
    input_cost: float = 0.0
    output_cost: float = 0.0
    db_cost: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def total_cost(self) -> float:
        return self.embed_cost + self.input_cost + self.output_cost + self.db_cost

    def merge(self, other: "CostRecord") -> "CostRecord":
        return CostRecord(
            embed_tokens=self.embed_tokens + other.embed_tokens,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            embed_cost=self.embed_cost + other.embed_cost,
            input_cost=self.input_cost + other.input_cost,
            output_cost=self.output_cost + other.output_cost,
            db_cost=self.db_cost + other.db_cost,
        )


VerdictStatus = Literal["grounded", "refused", "ungrounded"]


class AgentAnswer(BaseModel):
    """The agent's final, verified output."""

    question: str
    answer: str
    citations: list[str] = Field(default_factory=list)
    sources: list[Retrieved] = Field(default_factory=list)
    trajectory: list[ToolCallRecord] = Field(default_factory=list)
    status: VerdictStatus = "grounded"
    verifier_notes: list[str] = Field(default_factory=list)
    cost: CostRecord = Field(default_factory=CostRecord)
    steps_used: int = 0


def normalize_section(raw: str) -> str:
    """Coerce loose section references to canonical form.

    ``"Sec. 33.02"``, ``"§33.02"``, ``"33.2"`` and ``"33.02(b)"`` all become
    ``"33.02"``. Note 33.02 and 33.021 are *different* sections, so trailing
    zeros are never trimmed.
    """
    import re

    m = re.search(r"33\.\d+", raw or "")
    return m.group(0) if m else (raw or "").strip()


Provision.model_rebuild()
