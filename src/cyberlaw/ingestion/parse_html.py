"""Parse the Texas Penal Code Chapter 33 HTML into a citable provision tree.

The source pages from statutes.capitol.texas.gov are flat: every provision is
its own ``<p>``, and hierarchy is encoded only in the leading marker --
``(a)``, ``(b-1)``, ``(1)``, ``(10-a)``, ``(A)``, ``(i)``. This module turns
that flat stream into a tree so every provision gets a real citation like
``33.02(b-1)(2)(A)(i)``.

Marker ranks (Texas drafting convention):

    1  lowercase letter   (a) (b) (b-1)     "subsection"
    2  arabic numeral     (1) (2) (10-a)    "subdivision"
    3  uppercase letter   (A) (B)           "paragraph"
    4  lowercase roman    (i) (ii)          "subparagraph"

Rank 1 is absent in Sec. 33.01, whose top level is numerals -- so rank is
used as an absolute depth rather than a strict nesting requirement.
"""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from ..schemas import Chapter, Provision, ProvisionKind, Section

# A paragraph's leading marker, e.g. "(b-1)  A person commits...".
MARKER_RE = re.compile(r"^\(([0-9A-Za-z][0-9A-Za-z\-]*)\)\s+(.*)$", re.DOTALL)

# "Sec. 33.02.  BREACH OF COMPUTER SECURITY." -> number, heading
HEADER_RE = re.compile(r"^Sec\.\s*(33\.\d+)\.\s*(.*?)\.?\s*$", re.DOTALL)

HISTORY_PREFIXES = (
    "Added by Acts",
    "Amended by",
    "Acts ",
    "Reenacted",
    "Renumbered",
    "Repealed",
    "Transferred",
)

# Chapter/title banners at the top of the file, not statute text.
BANNER_TEXTS = {"PENAL CODE", "TITLE 7. OFFENSES AGAINST PROPERTY", "CHAPTER 33. COMPUTER CRIMES"}

ROMAN_CHARS = set("ivxlcdm")

RANK_LOWER_ALPHA = 1
RANK_NUMERAL = 2
RANK_UPPER_ALPHA = 3
RANK_ROMAN = 4


_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _roman_to_int(s: str) -> int | None:
    """Convert a lowercase roman numeral to an int, or None if malformed."""
    total = prev = 0
    for ch in reversed(s):
        val = _ROMAN_VALUES.get(ch)
        if val is None:
            return None
        total += -val if val < prev else val
        prev = max(prev, val)
    return total or None


def _marker_rank(marker: str, stack: list[tuple[int, Provision]]) -> int:
    """Classify a marker into a hierarchy rank.

    Single lowercase characters are genuinely ambiguous: ``(c)`` is subsection
    c, but ``(i)`` inside an ``(A)/(B)`` list is roman one. Letters like
    ``c``, ``d``, ``l`` and ``m`` are also valid roman characters, so a naive
    "is it a roman character" test wrongly nests subsection (c) under (B).

    A single lowercase marker is therefore read as roman only when it would
    *continue a well-formed roman sequence* inside an open uppercase list:
    either it is ``i`` starting a fresh list, or it is the successor of the
    previous roman sibling.
    """
    base = marker.split("-")[0]  # "b-1" -> "b", "10-a" -> "10"

    if base.isdigit():
        return RANK_NUMERAL
    if base.isupper():
        return RANK_UPPER_ALPHA

    # Multi-character lowercase markers made only of roman characters are
    # unambiguous: subsection letters are always a single character.
    if len(base) > 1:
        return RANK_ROMAN if set(base) <= ROMAN_CHARS else RANK_LOWER_ALPHA

    if base not in ROMAN_CHARS:
        return RANK_LOWER_ALPHA

    # Innermost open uppercase-letter provision, if any.
    upper = next((node for rank, node in reversed(stack) if rank == RANK_UPPER_ALPHA), None)
    if upper is None:
        return RANK_LOWER_ALPHA

    romans = [c.marker for c in upper.children if c.depth == RANK_ROMAN]
    if not romans:
        return RANK_ROMAN if base == "i" else RANK_LOWER_ALPHA

    prev, cur = _roman_to_int(romans[-1]), _roman_to_int(base)
    if prev is not None and cur == prev + 1:
        return RANK_ROMAN
    return RANK_LOWER_ALPHA


def _quoted_terms(text: str) -> list[str]:
    """Pull defined terms out of a definition provision.

    ``'"Decryption," "decrypt," or "decrypted" means ...'`` yields three
    terms. A defining verb is required, and only quotes before it count, so
    quoted phrases inside a definition body are not mistaken for terms.
    """
    head = re.split(r"\b(?:means|includes|has the meaning)\b", text, maxsplit=1)[0]
    if head == text:  # no defining verb -> not a definition
        return []
    terms = []
    for raw in re.findall(r'"([^"]+)"', head):
        term = raw.strip().strip(",;.").strip()
        if term:
            terms.append(term)
    return terms


def _classify(text: str, section_number: str, is_definition_scope: bool) -> ProvisionKind:
    """Label a provision so deterministic tools can find it without an LLM."""
    low = text.lower()

    # A provision that quotes a term and then defines it is a definition
    # wherever it appears -- Sec. 33.01's chapter-wide list, a section-scoped
    # "(a) In this section:" list, or inline as in 33.023(a) ("ransomware").
    # ``is_definition_scope`` is kept as a hint for list items whose parent
    # opened the scope.
    if _quoted_terms(text):
        return "definition"
    if is_definition_scope and re.match(r'^\s*"', text):
        return "definition"

    # Grading language. Checked before "offense" because penalty provisions
    # also contain the word "offense".
    grade = r"(?:class\s+[abc]\s+misdemeanor|state jail felony|felony of the|(?:first|second|third)[\s-]degree felony)"
    if re.search(rf"\bis\s+(?:a|an)\s+{grade}", low):
        return "penalty"
    # A bare ladder rung: "(4)  a state jail felony if the aggregate ...".
    if re.match(rf"^\s*(?:a|an)\s+{grade}", low):
        return "penalty"
    if re.search(r"^an offense under", low) or "is punishable" in low:
        return "penalty"
    if "commits an offense" in low:
        return "offense"
    if "defense to prosecution" in low or "affirmative defense" in low:
        return "defense"
    if any(k in low for k in ("venue", "attorney general", "may be prosecuted", "peace officer")):
        return "procedure"
    return "other"


class _SectionBuilder:
    """Accumulates paragraphs for one section into a provision tree."""

    def __init__(self, number: str, heading: str, url: str):
        self.number = number
        self.heading = heading
        self.url = url
        self.lead_in = ""
        self.roots: list[Provision] = []
        self.history: list[str] = []
        self.editorial_notes: list[str] = []
        # Stack of (rank, provision) for the currently open ancestors.
        self._stack: list[tuple[int, Provision]] = []
        # True once we've seen "In this section:" / "In this chapter:".
        self._definition_scope = False

    def set_lead_in(self, text: str) -> None:
        self.lead_in = text
        if re.search(r"in this (?:section|chapter|subchapter)\s*:", text, re.I):
            self._definition_scope = True

    def add_paragraph(self, text: str) -> None:
        m = MARKER_RE.match(text)
        if not m:
            # Unmarked continuation of whatever provision is open, or of the
            # section lead-in if nothing is open yet.
            if self._stack:
                node = self._stack[-1][1]
                node.text = f"{node.text}\n{text}".strip()
            else:
                self.lead_in = f"{self.lead_in}\n{text}".strip() if self.lead_in else text
            return

        marker, body = m.group(1), m.group(2).strip()
        rank = _marker_rank(marker, self._stack)

        # A new marker closes every open node at its rank or deeper.
        while self._stack and self._stack[-1][0] >= rank:
            self._stack.pop()

        parent = self._stack[-1][1] if self._stack else None
        path = (parent.path + [marker]) if parent else [marker]
        cite = self.number + "".join(f"({p})" for p in path)

        # A subsection that opens its own definition list ("(a) In this
        # section:") makes its children definitions.
        scope = self._definition_scope or bool(
            parent and re.search(r"in this (?:section|chapter)\s*:", parent.text, re.I)
        )

        node = Provision(
            cite=cite,
            section=self.number,
            path=path,
            marker=marker,
            depth=rank,
            text=body,
            kind=_classify(body, self.number, scope),
        )

        if parent is None:
            self.roots.append(node)
        else:
            parent.children.append(node)
        self._stack.append((rank, node))

    def build(self) -> Section:
        # A provision that only introduces a ladder ("(d-1) Subject to
        # Subsection (d-2), ... the offense is:") carries no grade language
        # itself, so promote it once its rungs are known. Without this the
        # penalty extractor skips the parent and mis-parses each rung alone.
        for root in self.roots:
            for node in root.walk():
                if node.kind in ("other", "offense") and any(
                    c.kind == "penalty" for c in node.children
                ):
                    node.kind = "penalty"

        return Section(
            number=self.number,
            heading=self.heading,
            url=self.url,
            lead_in=self.lead_in,
            provisions=self.roots,
            history=self.history,
            editorial_notes=self.editorial_notes,
        )


def parse_chapter(html_path: str | Path) -> Chapter:
    """Parse the chapter HTML into a :class:`Chapter`."""
    html_path = Path(html_path)
    with html_path.open("r", encoding="utf-8") as fh:
        soup = BeautifulSoup(fh, "html.parser")

    sections: list[Section] = []
    current: _SectionBuilder | None = None

    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if not text or text in BANNER_TEXTS:
            continue

        header_link = p.find(
            "a", style=lambda v: bool(v) and "font-weight:bold" in v
        )
        if header_link and header_link.get_text(strip=True).startswith("Sec."):
            if current is not None:
                sections.append(current.build())

            anchor_text = header_link.get_text(" ", strip=True)
            hm = HEADER_RE.match(anchor_text)
            if not hm:
                # Unrecognised header shape: skip rather than mis-attribute
                # the following provisions to the previous section.
                current = None
                continue
            number, heading = hm.group(1), hm.group(2).strip()

            href = header_link.get("href", "") or ""
            if href.startswith("http"):
                url = href
            else:
                url = f"https://statutes.capitol.texas.gov/Docs/PE/htm/{href.lstrip('/')}"

            current = _SectionBuilder(number=number, heading=heading, url=url)

            # The header paragraph usually continues into the body, e.g.
            # "Sec. 33.02.  BREACH... (a)  A person commits an offense if..."
            remainder = text.replace(anchor_text, "", 1).strip()
            if remainder:
                if MARKER_RE.match(remainder):
                    current.add_paragraph(remainder)
                else:
                    current.set_lead_in(remainder)
            continue

        if current is None:
            continue

        if text.startswith("For text of"):
            current.editorial_notes.append(text)
            continue
        if text.startswith(HISTORY_PREFIXES):
            current.history.append(text)
            continue
        # Once history has started, remaining unmarked lines belong to it.
        if current.history and not MARKER_RE.match(text):
            current.history.append(text)
            continue

        current.add_paragraph(text)

    if current is not None:
        sections.append(current.build())

    return Chapter(sections=sections)
