"""Deterministic lookup tables built once at ingest time.

Two of the agent's three core questions are not semantic questions at all:

* "What does 'owner' mean?"  -- Chapter 33 has a closed list of definitions.
* "What is the penalty for X?" -- each offence states its own grading ladder.

Both are exact lookups over a small, fully enumerable structure. Answering
them with vector search invites a near-miss; answering them from a parsed
table cannot hallucinate and costs nothing. Only genuinely fuzzy questions
("does this scenario count as tampering?") go to the embeddings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..schemas import Chapter, Definition, PenaltyLadder, PenaltyRung

# Texas drafting uses both "felony of the third degree" and the older
# "third degree felony"; Chapter 33 contains examples of each.
GRADE_RE = re.compile(
    r"(Class\s+[ABC]\s+misdemeanor"
    r"|state jail felony"
    r"|felony of the (?:first|second|third) degree"
    r"|(?:first|second|third)[\s-]degree felony"
    r"|capital felony)",
    re.IGNORECASE,
)

_MONEY = r"\$([\d,]+(?:\.\d+)?)"


def _money(raw: str) -> float:
    return float(raw.replace(",", ""))


def parse_amount_range(text: str) -> tuple[float | None, float | None]:
    """Extract an aggregate-amount window from a grading condition.

    ``"$2,500 or more but less than $30,000"`` -> ``(2500.0, 30000.0)``
    ``"less than $100"``                       -> ``(None, 100.0)``
    ``"$300,000 or more"``                     -> ``(300000.0, None)``
    """
    m = re.search(rf"{_MONEY}\s+or more but less than\s+{_MONEY}", text, re.I)
    if m:
        return _money(m.group(1)), _money(m.group(2))
    m = re.search(rf"less than\s+{_MONEY}", text, re.I)
    if m:
        return None, _money(m.group(1))
    m = re.search(rf"{_MONEY}\s+or more", text, re.I)
    if m:
        return _money(m.group(1)), None
    return None, None


def _collapse(text: str) -> str:
    """Collapse runs of whitespace, preserving newlines between provisions."""
    return "\n".join(
        re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines() if line.strip()
    ).strip()


def _ladder_condition(child) -> str:
    """Condition clause for one rung of an enumerated ladder.

    ``"a state jail felony if the aggregate amount ... is $2,500 or more"``
    becomes ``"if the aggregate amount ... is $2,500 or more"``. Nested
    subparagraphs are appended so conditions spread over (A)/(B) survive.
    """
    body = child.text
    if child.children:
        body = body + "\n" + "\n".join(c.rendered() for c in child.children)
    body = GRADE_RE.sub("", body, count=1)
    body = re.sub(r"^\s*(?:a|an)\s+", "", body, flags=re.I)
    return _collapse(body).strip(" ;,") or _collapse(child.rendered())


def _inline_rungs(node) -> tuple[list[PenaltyRung], list[str]]:
    """Parse grading stated in prose rather than as an enumerated ladder.

    Handles two shapes that both appear in Chapter 33:

    * several grades in one provision, one per sentence --
      ``"An offense under Subsection (a) is a felony of the third degree.
      An offense under Subsection (b) is a Class A misdemeanor, ..."``
    * a baseline grade with an ``except that ... if:`` escalation whose
      conditions live in the provision's children.

    Conditions are kept verbatim here: the statutory sentence *is* the
    condition, and paraphrasing it would be the one thing this system exists
    to avoid.
    """
    rungs: list[PenaltyRung] = []
    notes: list[str] = []
    matched_any = False

    for sentence in re.split(r"(?<=\.)\s+", node.text):
        if not sentence.strip():
            continue
        clauses = re.split(r"\bexcept that\b", sentence, flags=re.I)
        for idx, clause in enumerate(clauses):
            grades = list(GRADE_RE.finditer(clause))
            if not grades:
                continue
            matched_any = True
            condition = _collapse(clause)
            # An escalation clause ending in ":" is completed by the children.
            if idx > 0 and node.children and clause.rstrip().endswith(":"):
                child_text = "\n".join(c.rendered() for c in node.children)
                condition = f"{condition}\n{child_text}".strip()
            lo, hi = parse_amount_range(condition)
            for gm in grades:
                rungs.append(
                    PenaltyRung(
                        grade=_normalize_grade(gm.group(1)),
                        cite=node.cite,
                        condition=condition,
                        min_amount=lo,
                        max_amount=hi,
                    )
                )

    if not matched_any and node.text.strip():
        notes.append(_collapse(node.text))
    return rungs, notes


def build_definitions(chapter: Chapter) -> list[Definition]:
    """Collect every statutory definition, at any nesting depth."""
    from .parse_html import _quoted_terms

    out: list[Definition] = []
    for section in chapter.sections:
        for root in section.provisions:
            for node in root.walk():
                if node.kind != "definition":
                    continue
                terms = _quoted_terms(node.text)
                if not terms:
                    continue
                scope = "chapter" if section.number == "33.01" else section.number
                for term in terms:
                    out.append(
                        Definition(
                            term=term,
                            cite=node.cite,
                            text=node.rendered(),
                            scope=scope,
                            url=section.url,
                        )
                    )
    return out


def build_penalties(chapter: Chapter) -> list[PenaltyLadder]:
    """Extract each section's offence-grading ladder."""
    ladders: list[PenaltyLadder] = []

    for section in chapter.sections:
        rungs: list[PenaltyRung] = []
        notes: list[str] = []

        nodes = [n for root in section.provisions for n in root.walk()]
        if not nodes and GRADE_RE.search(section.lead_in):
            notes.append(_collapse(section.lead_in))

        # Children consumed as rungs of an enumerated ladder, so the walk
        # does not emit them a second time on its own.
        consumed: set[str] = set()

        for node in nodes:
            if node.cite in consumed:
                continue
            graded_children = [c for c in node.children if GRADE_RE.search(c.text)]
            if (
                node.kind != "penalty"
                and not GRADE_RE.search(node.text)
                and not graded_children
            ):
                continue

            if graded_children:
                # Ladder form: "(b-2) An offense under Subsection (b-1) is:"
                # followed by one graded rung per subdivision.
                for child in graded_children:
                    grade_match = GRADE_RE.search(child.text)
                    condition = _ladder_condition(child)
                    lo, hi = parse_amount_range(condition)
                    rungs.append(
                        PenaltyRung(
                            grade=_normalize_grade(grade_match.group(1)),
                            cite=child.cite,
                            condition=condition,
                            min_amount=lo,
                            max_amount=hi,
                        )
                    )
                    consumed.update(n.cite for n in child.walk())
                # The lead-in ("An offense under Subsection (b-1) is:") may
                # itself state a baseline grade before the ladder.
                lead = GRADE_RE.sub("", node.text)
                if GRADE_RE.search(node.text) and not lead.strip().endswith(":"):
                    extra, extra_notes = _inline_rungs(node)
                    rungs.extend(extra)
                    notes.extend(extra_notes)
                continue

            node_rungs, node_notes = _inline_rungs(node)
            rungs.extend(node_rungs)
            notes.extend(node_notes)

        if rungs or notes:
            ladders.append(
                PenaltyLadder(
                    section=section.number,
                    heading=section.heading,
                    url=section.url,
                    rungs=rungs,
                    notes=notes,
                )
            )
    return ladders


def _normalize_grade(raw: str) -> str:
    """Canonicalise grade spelling so identical grades group cleanly.

    Output matches the statute's own style: "Class B misdemeanor",
    "state jail felony", "felony of the first degree".
    """
    g = re.sub(r"\s+", " ", raw.strip()).lower()
    if g.startswith("class "):
        letter = g.split()[1].upper()
        return f"Class {letter} misdemeanor"
    return g


class Registry:
    """The serialised deterministic tables, with lookup helpers."""

    def __init__(self, definitions: list[Definition], penalties: list[PenaltyLadder]):
        self.definitions = definitions
        self.penalties = penalties
        self._by_term: dict[str, list[Definition]] = {}
        for d in definitions:
            self._by_term.setdefault(d.term.strip().lower(), []).append(d)

    # --- lookups ---------------------------------------------------------
    def lookup_definition(self, term: str) -> list[Definition]:
        """Exact match first, then containment, then token overlap.

        Returns every scope a term is defined in, because a term can be
        defined chapter-wide and again for a single section.
        """
        key = (term or "").strip().strip('"').lower()
        if not key:
            return []
        if key in self._by_term:
            return list(self._by_term[key])

        # Substring match in either direction: "virus" -> "computer virus",
        # "owner of property" -> "owner".
        hits = [
            d
            for k, ds in self._by_term.items()
            for d in ds
            if key in k or k in key
        ]
        if hits:
            return _dedupe_definitions(hits)

        # Fall back to word overlap so "consent" finds "effective consent".
        words = set(re.findall(r"\w+", key))
        scored = []
        for k, ds in self._by_term.items():
            overlap = words & set(re.findall(r"\w+", k))
            if overlap:
                scored.append((len(overlap), ds))
        scored.sort(key=lambda x: -x[0])
        return _dedupe_definitions([d for _, ds in scored[:3] for d in ds])

    def ladder(self, section: str) -> PenaltyLadder | None:
        return next((p for p in self.penalties if p.section == section), None)

    def terms(self) -> list[str]:
        return sorted({d.term for d in self.definitions})

    # --- persistence -----------------------------------------------------
    def to_json(self) -> dict:
        return {
            "definitions": [d.model_dump() for d in self.definitions],
            "penalties": [p.model_dump() for p in self.penalties],
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_json(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> "Registry":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            definitions=[Definition.model_validate(d) for d in raw["definitions"]],
            penalties=[PenaltyLadder.model_validate(p) for p in raw["penalties"]],
        )

    @classmethod
    def from_chapter(cls, chapter: Chapter) -> "Registry":
        return cls(build_definitions(chapter), build_penalties(chapter))


def _dedupe_definitions(defs: list[Definition]) -> list[Definition]:
    seen: set[tuple[str, str]] = set()
    out: list[Definition] = []
    for d in defs:
        key = (d.term.lower(), d.cite)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out
