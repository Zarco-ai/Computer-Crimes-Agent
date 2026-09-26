"""Parser tests: hierarchy, citations, and the marker ambiguities."""

from __future__ import annotations


def test_all_ten_sections_found(chapter):
    assert [s.number for s in chapter.sections] == [
        "33.01",
        "33.02",
        "33.021",
        "33.022",
        "33.023",
        "33.024",
        "33.03",
        "33.04",
        "33.05",
        "33.07",
    ]


def test_headings_are_captured(chapter):
    assert chapter.section("33.02").heading == "BREACH OF COMPUTER SECURITY"
    # 33.05 is voting-machine tampering, NOT "harmful access" -- a section
    # mix-up here would make every penalty answer for it wrong.
    assert "VOTING MACHINE" in chapter.section("33.05").heading


def test_subsection_markers_of_33_02(chapter):
    markers = [p.marker for p in chapter.section("33.02").provisions]
    assert markers == ["a", "b", "b-1", "b-2", "c", "d", "e", "f"]


def test_lowercase_c_is_a_subsection_not_a_roman_numeral(chapter):
    """(c) must not nest under (B): 'c' is also a roman character."""
    sec = chapter.section("33.02")
    assert sec.find("33.02(c)") is not None
    assert sec.find("33.02(b-2)(7)(B)(c)") is None


def test_roman_numerals_nest_under_uppercase_paragraphs(chapter):
    sec = chapter.section("33.02")
    for cite in ("33.02(b-1)(2)(A)(i)", "33.02(b-1)(2)(A)(ii)", "33.02(b-1)(2)(B)(ii)"):
        node = sec.find(cite)
        assert node is not None, cite
        assert node.depth == 4


def test_definitions_section_uses_numerals_as_top_level(chapter):
    sec = chapter.section("33.01")
    markers = [p.marker for p in sec.provisions]
    assert markers[0] == "1"
    # The -a/-b/-c insertions are distinct definitions, not children.
    assert "10-a" in markers and "13-c" in markers
    assert len(markers) == 23


def test_lead_in_only_sections_keep_their_text(chapter):
    for number in ("33.03", "33.04"):
        sec = chapter.section(number)
        assert sec.provisions == []
        assert len(sec.lead_in) > 80
        assert sec.full_text().strip()


def test_history_and_editorial_notes_separated_from_body(chapter):
    sec = chapter.section("33.02")
    assert sec.history, "expected Added by / Amended by lines"
    assert all("Acts" in h or "Amended" in h for h in sec.history)
    body = sec.full_text()
    assert "Added by Acts" not in body
    # The one editorial note in the file is attached, not dropped into text.
    notes = [n for s in chapter.sections for n in s.editorial_notes]
    assert any("For text of" in n for n in notes)


def test_citations_are_wellformed(chapter):
    for sec in chapter.sections:
        for root in sec.provisions:
            for node in root.walk():
                assert node.cite.startswith(sec.number)
                assert node.section == sec.number
                assert node.cite == sec.number + "".join(f"({p})" for p in node.path)


def test_rendered_text_round_trips_markers(chapter):
    node = chapter.section("33.02").find("33.02(b-2)")
    rendered = node.rendered()
    assert rendered.startswith("(b-2)")
    assert "(1)" in rendered and "(7)" in rendered
    assert "$300,000" in rendered


def test_provision_kinds(chapter):
    sec = chapter.section("33.02")
    assert sec.find("33.02(a)").kind == "offense"
    assert sec.find("33.02(b)").kind == "penalty"
    assert sec.find("33.02(e)").kind == "defense"
    assert chapter.section("33.01").provisions[0].kind == "definition"
    # A ladder introducer with no grade language of its own is promoted.
    assert chapter.section("33.023").find("33.023(d-1)").kind == "penalty"


def test_inline_section_scoped_definition_detected(chapter):
    node = chapter.section("33.023").find("33.023(a)")
    assert node.kind == "definition"
    assert "ransomware" in node.text
