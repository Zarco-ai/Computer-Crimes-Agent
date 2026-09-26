"""Citation verifier -- the gate that makes grounding enforced, not requested.

A prompt that says "only cite what you retrieved" is a request. This module
checks it: every citation in the answer is extracted and matched against the
provisions the tools actually returned. An answer citing anything else is
rejected, the model is told precisely what went wrong, and it gets one retry
before the run falls back to an explicit refusal.

The check is deliberately generous about *specificity*: if a tool returned
``33.02(b-2)`` then citing ``33.02(b-2)(4)`` or ``33.02`` is fine, because
both are provably within what was read. Citing ``33.09`` -- a section that
does not exist -- or ``33.05`` when nothing surfaced it, is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# "§ 33.02(b-2)(4)", "Sec. 33.02", "Section 33.021(a)(1)", bare "33.02(b)".
CITE_RE = re.compile(
    r"(?:§+\s*|Sec\.\s*|Section\s+)?\b(33\.\d+)((?:\s*\([0-9A-Za-z\-]+\))*)",
    re.IGNORECASE,
)

# Any explicitly-marked statutory reference, used to catch citations to
# chapters outside this corpus.
ANY_CITE_RE = re.compile(r"(?:§+\s*|Sec\.\s*|Section\s+)(\d+\.\d+)")


def extract_citations(text: str) -> list[str]:
    """Pull normalised Chapter 33 citations out of an answer, in order."""
    out: list[str] = []
    for m in CITE_RE.finditer(text or ""):
        section, tail = m.group(1), m.group(2) or ""
        markers = re.findall(r"\(([0-9A-Za-z\-]+)\)", tail)
        cite = section + "".join(f"({x})" for x in markers)
        if cite not in out:
            out.append(cite)
    return out


def _is_prefix_of(candidate: str, supported: str) -> bool:
    """True if ``candidate`` is an ancestor-or-equal of ``supported``."""
    return supported == candidate or supported.startswith(candidate + "(")


@dataclass
class Verdict:
    ok: bool
    citations: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    foreign: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def verify(
    answer: str,
    supported: set[str],
    *,
    known_sections: set[str] | None = None,
    allowed_foreign: set[str] | None = None,
    require_citation: bool = True,
) -> Verdict:
    """Check an answer's citations against what the tools surfaced.

    Args:
        answer: the model's draft answer.
        supported: every cite returned by tool results this run.
        known_sections: sections that exist in the corpus; used to flag
            invented section numbers even when nothing was retrieved.
        allowed_foreign: non-Chapter-33 sections that Chapter 33 itself
            cross-references (§ 31.01, § 32.51, § 15.01, ...). Quoting these
            is legitimate because they appear in the statutory text; citing
            any *other* chapter is not, since the agent cannot have read it.
        require_citation: if True, a substantive answer with no citation at
            all fails. Refusals are exempt.
    """
    cites = extract_citations(answer)
    verdict = Verdict(ok=True, citations=cites)
    allowed_foreign = allowed_foreign or set()

    # Citations to chapters outside the corpus, excluding the cross-references
    # that Chapter 33's own text contains.
    for m in ANY_CITE_RE.finditer(answer or ""):
        ref = m.group(1)
        if ref.startswith("33."):
            continue
        if ref in allowed_foreign:
            continue
        verdict.foreign.append(ref)
    if verdict.foreign:
        verdict.ok = False
        verdict.notes.append(
            "Cited provisions outside Chapter 33: "
            + ", ".join(sorted(set(verdict.foreign)))
        )

    for cite in cites:
        # Supported if it equals, contains, or is contained by something read.
        if any(
            cite == s or _is_prefix_of(cite, s) or _is_prefix_of(s, cite)
            for s in supported
        ):
            continue
        section = cite.split("(")[0]
        if known_sections is not None and section not in known_sections:
            verdict.notes.append(f"§ {cite} is not a real Chapter 33 section.")
        verdict.unsupported.append(cite)

    if verdict.unsupported:
        verdict.ok = False
        verdict.notes.append(
            "Unsupported citations (no tool returned them): "
            + ", ".join(verdict.unsupported)
        )

    if require_citation and not cites:
        verdict.ok = False
        verdict.notes.append("Answer makes legal assertions with no citation.")

    return verdict


# "I cannot provide…", "I can't answer…", "Chapter 33 does not address…".
# Pattern-based rather than a list of exact phrases, because the model
# paraphrases its refusals and an exact-match list silently misses them --
# which then trips the require-citation rule and reports a clean refusal as a
# citation failure.
_INABILITY_RE = re.compile(
    r"\b(?:can(?:no|')?t|cannot|unable to|won'?t|will not|does not|do not|don'?t)\s+"
    r"(?:\w+\s+){0,3}"
    r"(?:answer|provide|access|tell|determine|state|say|confirm|address|cover|see|read|speak to)\b",
    re.IGNORECASE,
)

_SCOPE_RE = re.compile(
    r"(?:outside|beyond|not (?:in|within|part of|covered by|addressed by|available in))"
    r"[^.]{0,60}?(?:chapter 33|this corpus|my (?:corpus|source)|the scope)"
    r"|no provision in chapter 33"
    r"|not (?:a )?(?:part of|in) (?:texas penal code )?chapter 33",
    re.IGNORECASE,
)


def looks_like_refusal(text: str) -> bool:
    """Is the model declining to answer rather than asserting law?

    Used to exempt refusals from the "must cite something" rule. A false
    negative here is costly: a correct refusal gets rejected for having no
    citations and the run is reported as ungrounded.
    """
    text = text or ""
    return bool(_INABILITY_RE.search(text) or _SCOPE_RE.search(text))
