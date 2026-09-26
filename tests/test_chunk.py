"""Chunking tests, including the regression this project was rebuilt around."""

from __future__ import annotations


def test_one_chunk_per_top_level_provision(chunks, chapter):
    expected = sum(len(s.provisions) or 1 for s in chapter.sections)
    assert len(chunks) == expected


def test_definitions_are_split_into_atomic_chunks(chunks):
    """The original bug: all 23 definitions lived in one ~2,500-token vector,
    so 'what is the definition of access?' lost to § 33.02(a)."""
    defs = [c for c in chunks if c.section == "33.01"]
    assert len(defs) == 23
    assert all(c.token_count < 400 for c in defs)


def test_every_chunk_is_small_enough_to_be_specific(chunks):
    assert max(c.token_count for c in chunks) < 500


def test_chunk_ids_are_unique_and_are_citations(chunks):
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))
    assert all(c.id == c.cite for c in chunks)
    assert all(c.cite.startswith("33.") for c in chunks)


def test_parent_section_enables_expansion(chunks):
    assert all(c.parent_section == c.section for c in chunks)


def test_definition_chunks_carry_their_terms(chunks):
    by_cite = {c.cite: c for c in chunks}
    assert by_cite["33.01(1)"].defined_terms == ["Access"]
    assert by_cite["33.01(10)"].defined_terms == ["Computer virus"]
    # One provision can define several aliases at once.
    assert by_cite["33.01(11-a)"].defined_terms == ["Decryption", "decrypt", "decrypted"]


def test_definition_chunks_state_the_term_up_front(chunks):
    """The orienting first line is what makes a definition chunk match a
    'what does X mean' query instead of an offence provision."""
    chunk = next(c for c in chunks if c.cite == "33.01(1)")
    assert chunk.text.startswith('Statutory definition of "Access"')
    assert "In this chapter:" in chunk.text
    assert "33.01(1)" in chunk.text


def test_unmarked_sections_become_one_chunk(chunks):
    for number in ("33.03", "33.04"):
        matching = [c for c in chunks if c.section == number]
        assert len(matching) == 1
        assert matching[0].cite == number
        assert len(matching[0].text) > 100


def test_penalty_ladder_stays_in_one_chunk(chunks):
    """A ladder split across chunks would strand grades from conditions."""
    chunk = next(c for c in chunks if c.cite == "33.02(b-2)")
    assert chunk.kind == "penalty"
    for amount in ("$100", "$750", "$2,500", "$30,000", "$150,000", "$300,000"):
        assert amount in chunk.text
    assert "felony of the first degree" in chunk.text


def test_nested_children_are_rolled_into_their_parent(chunks):
    chunk = next(c for c in chunks if c.cite == "33.02(b-1)")
    assert "(2)" in chunk.text and "(A)" in chunk.text and "(i)" in chunk.text
    assert not any(c.cite.startswith("33.02(b-1)(") for c in chunks)


def test_jsonl_round_trip(chunks, tmp_path):
    from cyberlaw.ingestion.chunk import read_chunks, write_chunks

    path = tmp_path / "chunks.jsonl"
    write_chunks(chunks, path)
    reloaded = read_chunks(path)
    assert len(reloaded) == len(chunks)
    assert [c.model_dump() for c in reloaded] == [c.model_dump() for c in chunks]
