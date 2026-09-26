"""Tool tests. The four deterministic tools need no API key at all."""

from __future__ import annotations

import pytest

from cyberlaw.tools.statute_tools import (
    make_get_section,
    make_list_sections,
    make_look_up_definition,
    make_penalty_lookup,
)


@pytest.fixture
def define(corpus):
    return make_look_up_definition(corpus)


@pytest.fixture
def penalty(corpus):
    return make_penalty_lookup(corpus)


@pytest.fixture
def section(corpus):
    return make_get_section(corpus)


class TestDefinitionTool:
    def test_returns_verbatim_text_and_citation(self, define):
        result = define(term="owner")
        assert "33.01(15)" in result.cites
        assert "has title to the property" in result.content
        assert "applies throughout Chapter 33" in result.content

    def test_flags_section_scoped_definitions(self, define):
        result = define(term="ransomware")
        assert "applies only within § 33.023" in result.content
        assert result.cites == ["33.023(a)"]

    def test_undefined_term_lists_what_is_available(self, define):
        result = define(term="phishing")
        assert "does not define" in result.content
        assert "Computer virus" in result.content
        assert result.cites == []


class TestPenaltyTool:
    def test_returns_every_rung_with_citations(self, penalty):
        result = penalty(section="33.02")
        assert "CLASS C MISDEMEANOR" in result.content
        assert "FELONY OF THE FIRST DEGREE" in result.content
        assert "33.02(b-2)(4)" in result.cites

    def test_accepts_loose_section_references(self, penalty):
        for ref in ("33.02", "§ 33.02", "Sec. 33.02", "Section 33.02(b)"):
            assert "CLASS C MISDEMEANOR" in penalty(section=ref).content

    def test_amount_filter_selects_the_right_rung(self, penalty):
        result = penalty(section="33.02", aggregate_amount=40000)
        assert "FELONY OF THE THIRD DEGREE" in result.content
        # $40,000 is above the state-jail window (2,500-30,000).
        assert "33.02(b-2)(4)" not in result.content
        assert "not graded by dollar amount" in result.content

    def test_refuses_to_state_punishment_ranges(self, penalty):
        """Chapter 33 gives grades only; ranges are Chapter 12."""
        content = penalty(section="33.02").content
        assert "Chapter 12" in content
        assert "do not state specific jail terms" in content

    def test_section_without_grading(self, penalty):
        result = penalty(section="33.01")
        assert "no offence grade" in result.content

    def test_nonexistent_section_is_reported_not_invented(self, penalty):
        result = penalty(section="33.09")
        assert "no section" in result.content
        assert "33.01" in result.content  # lists the real ones
        assert result.cites == []


class TestGetSectionTool:
    def test_returns_full_verbatim_text(self, section):
        result = section(section="33.022")
        assert "ELECTRONIC ACCESS INTERFERENCE" in result.content
        assert "intentionally interrupts or suspends access" in result.content
        assert "third degree felony" in result.content
        assert result.cites == ["33.022"]

    def test_unmarked_section_has_body(self, section):
        result = section(section="33.03")
        assert "affirmative defense" in result.content
        assert "communication common carrier" in result.content

    def test_nonexistent_section(self, section):
        assert "no section" in section(section="33.99").content


class TestListSectionsTool:
    def test_lists_every_section_with_flags(self, corpus):
        result = make_list_sections(corpus)()
        for number in corpus.section_numbers():
            assert f"§ {number}" in result.content
        assert "has offence grades" in result.content

    def test_does_not_attribute_definitions_across_similar_numbers(self, corpus):
        """§ 33.02 defines no terms; a prefix match would credit it with
        § 33.021's and § 33.023's definitions."""
        entry = next(e for e in corpus.toc() if e["section"] == "33.02")
        assert entry["defines_terms"] == []
        ch33_01 = next(e for e in corpus.toc() if e["section"] == "33.01")
        assert len(ch33_01["defines_terms"]) > 20


class TestRegistryDispatch:
    def test_unknown_tool_is_reported_not_raised(self, corpus):
        from cyberlaw.tools.base import ToolRegistry

        registry = ToolRegistry([make_list_sections(corpus)])
        result = registry.call("nope", {})
        assert result.error == "unknown_tool"
        assert "list_sections" in result.content

    def test_bad_arguments_are_reported_not_raised(self, corpus):
        from cyberlaw.tools.base import ToolRegistry

        registry = ToolRegistry([make_look_up_definition(corpus)])
        result = registry.call("look_up_definition", {"wrong_kwarg": 1})
        assert result.error == "bad_arguments"

    def test_specs_are_valid_openai_schemas(self, corpus):
        from cyberlaw.tools.base import ToolRegistry

        registry = ToolRegistry(
            [make_look_up_definition(corpus), make_penalty_lookup(corpus)]
        )
        for spec in registry.specs():
            assert spec["type"] == "function"
            assert spec["function"]["name"]
            assert spec["function"]["description"]
            assert spec["function"]["parameters"]["type"] == "object"


def test_in_memory_store_ranks_by_cosine_similarity(corpus):
    from cyberlaw.retrieval.store import InMemoryStore

    store = InMemoryStore()
    chunks = corpus.chunks[:3]
    vectors = [[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]]
    store.upsert(chunks, vectors)

    hits, _ = store.query([1.0, 0.0], top_k=3)
    assert [h.cite for h in hits][:2] == [chunks[0].cite, chunks[2].cite]

    filtered, _ = store.query([1.0, 0.0], top_k=3, section="33.01")
    assert all(h.section == "33.01" for h in filtered)

    # Upserting the same cite twice must replace, not duplicate.
    store.upsert([chunks[0]], [[0.5, 0.5]])
    assert store.stats()["vectors"] == 3
