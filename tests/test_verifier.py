"""Verifier tests -- the gate that turns 'please cite' into 'must cite'."""

from __future__ import annotations

from cyberlaw.agent.verifier import extract_citations, looks_like_refusal, verify


class TestExtraction:
    def test_recognises_every_citation_style(self):
        text = (
            "Under § 33.02(a) and Sec. 33.023, see Section 33.021(a)(1); "
            "compare 33.024(b-1)(4)."
        )
        assert extract_citations(text) == [
            "33.02(a)",
            "33.023",
            "33.021(a)(1)",
            "33.024(b-1)(4)",
        ]

    def test_deduplicates_preserving_order(self):
        assert extract_citations("§ 33.02(a) ... again § 33.02(a) ... § 33.01") == [
            "33.02(a)",
            "33.01",
        ]

    def test_no_citations(self):
        assert extract_citations("This is not legal advice.") == []
        assert extract_citations("") == []


class TestGrounding:
    def test_exact_match_passes(self):
        v = verify("See § 33.02(a).", {"33.02(a)"})
        assert v.ok and not v.unsupported

    def test_more_specific_than_retrieved_passes(self):
        """Retrieving the (b-2) ladder supports citing a rung inside it."""
        v = verify("See § 33.02(b-2)(4).", {"33.02(b-2)"})
        assert v.ok

    def test_less_specific_than_retrieved_passes(self):
        v = verify("See § 33.02.", {"33.02(b-2)(4)"})
        assert v.ok

    def test_unretrieved_section_fails(self):
        v = verify("This is governed by § 33.05(b).", {"33.02(a)"})
        assert not v.ok
        assert v.unsupported == ["33.05(b)"]

    def test_similar_section_numbers_do_not_cross_support(self):
        """33.02 and 33.021 are different sections; a prefix match would
        silently accept the wrong one."""
        v = verify("See § 33.021(a).", {"33.02(a)"})
        assert not v.ok
        assert "33.021(a)" in v.unsupported

    def test_invented_section_is_flagged_as_unreal(self):
        v = verify("See § 33.09(c).", {"33.02(a)"}, known_sections={"33.02", "33.01"})
        assert not v.ok
        assert any("not a real" in n for n in v.notes)

    def test_substantive_answer_without_citation_fails(self):
        v = verify("Yes, that is a felony.", {"33.02(a)"})
        assert not v.ok
        assert any("no citation" in n for n in v.notes)

    def test_refusal_without_citation_is_allowed(self):
        v = verify("I can't answer that from Chapter 33.", set(), require_citation=False)
        assert v.ok


class TestForeignChapters:
    def test_citing_chapter_12_is_rejected(self):
        v = verify(
            "A state jail felony is punishable under § 12.35.", {"33.02(b)"}
        )
        assert not v.ok
        assert "12.35" in v.foreign

    def test_cross_references_in_the_statute_are_allowed(self):
        """§ 33.01(12)(A) literally says 'as defined by Section 31.01', so
        quoting it must not be treated as citing outside the corpus."""
        v = verify(
            "Consent induced by deception (as defined by Section 31.01) is not "
            "effective consent under § 33.01(12).",
            {"33.01(12)"},
            allowed_foreign={"31.01"},
        )
        assert v.ok, v.notes

    def test_unreferenced_chapter_still_rejected_when_allowlist_present(self):
        v = verify(
            "See Section 12.21 and § 33.02(b).",
            {"33.02(b)"},
            allowed_foreign={"31.01", "32.51"},
        )
        assert not v.ok
        assert "12.21" in v.foreign


class TestRefusalDetection:
    def test_positive_cases(self):
        for text in (
            "I can't answer that from Texas Penal Code Chapter 33.",
            "That is outside the scope of Chapter 33.",
            "Chapter 33 does not address punishment ranges.",
            "No provision in Chapter 33 covers civil liability.",
        ):
            assert looks_like_refusal(text), text

    def test_negative_cases(self):
        for text in (
            "Under § 33.02(a), knowingly accessing a computer without consent is an offence.",
            "The grade is a state jail felony under § 33.02(b).",
        ):
            assert not looks_like_refusal(text), text


def test_cross_references_discovered_from_the_corpus(corpus):
    refs = corpus.cross_references()
    # Chapter 33 borrows these definitions from elsewhere in Texas law.
    for expected in ("31.01", "32.51", "31.002", "182.002", "15.01"):
        assert expected in refs
    assert not any(r.startswith("33.") for r in refs)


class TestRefusalWordingVariants:
    """Real drafts the model produced that an exact-phrase list missed."""

    def test_cannot_provide_with_chapter_12_explanation(self):
        text = (
            "I cannot provide information about punishment ranges, including the "
            "number of years for a state jail felony, as that information is found "
            "in Chapter 12 of the Texas Penal Code, which I cannot access."
        )
        assert looks_like_refusal(text)
        assert verify(text, set(), require_citation=not looks_like_refusal(text)).ok

    def test_other_paraphrases(self):
        for text in (
            "I can't provide that from Chapter 33.",
            "I am unable to determine that from the statutory text available.",
            "That is not available in Chapter 33.",
            "Chapter 33 does not address civil liability.",
            "No provision in Chapter 33 speaks to this.",
        ):
            assert looks_like_refusal(text), text

    def test_grounded_answers_are_not_read_as_refusals(self):
        for text in (
            "Under § 33.02(a), knowingly accessing a computer without the effective "
            "consent of the owner is an offence.",
            "An offence under § 33.05 does not require that the votes actually be "
            "used in the official determination of the outcome.",
            "§ 33.022(a) applies to a person other than a network provider acting "
            "for a legitimate business purpose.",
        ):
            assert not looks_like_refusal(text), text
