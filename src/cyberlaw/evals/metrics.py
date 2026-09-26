"""Metrics that answer "is this system actually trustworthy?"

Ragas faithfulness and answer-correctness measure whether the prose matches
the retrieved context. For a legal assistant, three further things matter
more, and none of them are captured by a generic RAG metric:

* **citation precision** -- did every cited provision actually get retrieved?
  An answer that is fluent, correct-sounding, and cites § 33.05 for a data
  deletion case is worse than useless.
* **section recall** -- did it find the provision that governs?
* **refusal correctness** -- did it decline when the answer is outside
  Chapter 33? A legal tool that always produces an answer is a liability;
  correctly saying "that's Chapter 12, which I can't see" is the product.

False-refusal rate on the golden set is tracked alongside refusal rate on the
out-of-scope set, because it is trivial to score 100% on one by destroying
the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..agent.verifier import extract_citations
from ..schemas import AgentAnswer


def _sections_of(cites: list[str]) -> set[str]:
    return {c.split("(")[0] for c in cites}


def citation_precision(result: AgentAnswer) -> float | None:
    """Share of cited provisions that a tool actually surfaced.

    ``None`` when the answer cites nothing (a refusal), so refusals do not
    silently count as perfect precision.
    """
    cites = extract_citations(result.answer)
    if not cites:
        return None
    surfaced: set[str] = set()
    for step in result.trajectory:
        surfaced.update(step.cites_surfaced)

    def supported(cite: str) -> bool:
        return any(
            cite == s or s.startswith(cite + "(") or cite.startswith(s + "(")
            for s in surfaced
        )

    return sum(supported(c) for c in cites) / len(cites)


def section_recall(result: AgentAnswer, expected_sections: list[str]) -> float | None:
    """Share of expected sections the answer cites."""
    if not expected_sections:
        return None
    cited = _sections_of(extract_citations(result.answer))
    return sum(s in cited for s in expected_sections) / len(expected_sections)


def cite_hit(result: AgentAnswer, expected_cites: list[str]) -> float | None:
    """Share of expected provisions cited, allowing a broader citation.

    Citing ``§ 33.02(b-2)`` when ``§ 33.02(b-2)(5)`` was expected counts as a
    hit: the agent found the right ladder. Citing only ``§ 33.02`` does not.
    """
    if not expected_cites:
        return None
    cited = extract_citations(result.answer)

    def found(expected: str) -> bool:
        return any(
            c == expected or expected.startswith(c + "(") or c.startswith(expected + "(")
            for c in cited
        )

    return sum(found(e) for e in expected_cites) / len(expected_cites)


def tool_choice_hit(result: AgentAnswer, expected_tools: list[str]) -> float | None:
    """1.0 if the agent used at least one acceptable tool for the job.

    Several tools can be reasonable for one question, so this rewards using
    any of the expected ones rather than demanding an exact trajectory.
    """
    if not expected_tools:
        return None
    used = {step.name for step in result.trajectory}
    return 1.0 if used & set(expected_tools) else 0.0


def used_any_tool(result: AgentAnswer) -> float:
    return 1.0 if result.trajectory else 0.0


def acknowledges_scope_limit(result: AgentAnswer) -> bool:
    """Did the answer explicitly say the asked-about thing is outside Ch. 33?

    This is the correct bar for an out-of-scope question. It is satisfied by a
    flat refusal *and* by a scoped answer that declines the question asked and
    then offers Chapter 33 material as contrast ("California law is outside
    this corpus; for comparison, Texas § 33.02 covers unauthorised access").
    Both are honest; only silently answering as if the question were in scope
    is a failure.
    """
    from ..agent.verifier import looks_like_refusal

    return result.status in ("refused", "ungrounded") or looks_like_refusal(result.answer)


def failed_to_answer(result: AgentAnswer) -> bool:
    """Did the run decline without asserting any cited law?

    This is the correct bar for an in-scope question, and it is deliberately
    *not* wording-based. A correct grounded answer often contains limiting
    language -- "Chapter 33 does not provide a general defence for X, however
    § 33.021(e) provides ..." -- and scoring that as a refusal understates the
    system badly. Citations are the reliable signal: an answer that cites
    provisions asserted law, however it is phrased.
    """
    from ..agent.verifier import looks_like_refusal

    if result.status == "ungrounded":
        return True
    if result.citations:
        return False
    return result.status == "refused" or looks_like_refusal(result.answer)


def mentions_punishment_range(result: AgentAnswer) -> bool:
    """Detect leakage of Chapter 12 material the corpus cannot support.

    Grades are fine ("state jail felony"); concrete confinement periods and
    fine amounts are not, because nothing in Chapter 33 states them.
    """
    import re

    text = result.answer
    patterns = [
        r"\b\d+\s*(?:to|–|-)\s*\d+\s*years?\b",
        r"\b(?:up to|maximum of|no more than)\s+\d+\s*(?:years?|days?|months?)\b",
        r"\bfine of (?:up to )?\$[\d,]+",
        r"\b\d+\s*days?\s+(?:in|of)\s+(?:jail|confinement)\b",
        r"\bpunishable by\b",
    ]
    return any(re.search(p, text, re.I) for p in patterns)


@dataclass
class CaseScore:
    id: str
    question: str
    status: str
    answer: str
    citations: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    steps: int = 0
    citation_precision: float | None = None
    section_recall: float | None = None
    cite_hit: float | None = None
    tool_choice_hit: float | None = None
    # Two distinct behaviours, scored against different bars per case type.
    acknowledged_scope_limit: bool = False
    failed_to_answer: bool = False
    expected_refusal: bool = False
    leaked_punishment: bool = False
    tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    notes: str = ""

    @property
    def correct_refusal_behaviour(self) -> bool:
        """Out-of-scope cases must acknowledge the limit; in-scope cases must
        actually answer."""
        if self.expected_refusal:
            return self.acknowledged_scope_limit
        return not self.failed_to_answer

    def as_row(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "status": self.status,
            "acknowledged_scope_limit": self.acknowledged_scope_limit,
            "failed_to_answer": self.failed_to_answer,
            "expected_refusal": self.expected_refusal,
            "refusal_ok": self.correct_refusal_behaviour,
            "citation_precision": self.citation_precision,
            "section_recall": self.section_recall,
            "cite_hit": self.cite_hit,
            "tool_choice_hit": self.tool_choice_hit,
            "leaked_punishment": self.leaked_punishment,
            "citations": " ".join(self.citations),
            "tools_used": " ".join(self.tools_used),
            "steps": self.steps,
            "tokens": self.tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "answer": self.answer,
            "notes": self.notes,
        }


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def summarise(scores: list[CaseScore]) -> dict:
    """Aggregate a run into the numbers worth putting in a README."""
    golden = [s for s in scores if not s.expected_refusal]
    oos = [s for s in scores if s.expected_refusal]

    summary = {
        "cases": len(scores),
        "citation_precision": _mean([s.citation_precision for s in scores]),
        "section_recall": _mean([s.section_recall for s in golden]),
        "cite_hit": _mean([s.cite_hit for s in golden]),
        "tool_choice_hit": _mean([s.tool_choice_hit for s in golden]),
        "punishment_leak_rate": (
            sum(s.leaked_punishment for s in scores) / len(scores) if scores else None
        ),
        "total_cost_usd": sum(s.cost_usd for s in scores),
        "total_tokens": sum(s.tokens for s in scores),
        "avg_steps": _mean([float(s.steps) for s in scores]),
    }
    if golden:
        summary["false_refusal_rate"] = sum(s.failed_to_answer for s in golden) / len(golden)
    if oos:
        summary["scope_acknowledged_out_of_scope"] = sum(
            s.acknowledged_scope_limit for s in oos
        ) / len(oos)
    return summary
