"""Registry tests: the deterministic answers must be exactly right."""

from __future__ import annotations

import pytest

from cyberlaw.ingestion.registry import parse_amount_range


class TestDefinitions:
    def test_chapter_wide_terms_resolve_to_the_right_provision(self, registry):
        cases = {
            "access": "33.01(1)",
            "owner": "33.01(15)",
            "effective consent": "33.01(12)",
            "computer virus": "33.01(10)",
            "property": "33.01(16)",
            "harm": "33.01(14)",
            "aggregate amount": "33.01(2)",
            "critical infrastructure facility": "33.01(10-a)",
        }
        for term, cite in cases.items():
            hits = registry.lookup_definition(term)
            assert hits, term
            assert hits[0].cite == cite, term
            assert hits[0].scope == "chapter"

    def test_section_scoped_terms_report_their_scope(self, registry):
        """'ransomware' applies only inside § 33.023 -- mislabelling that as
        chapter-wide would misstate the law."""
        hit = registry.lookup_definition("ransomware")[0]
        assert hit.cite == "33.023(a)"
        assert hit.scope == "33.023"

        minor = registry.lookup_definition("minor")[0]
        assert minor.cite == "33.021(a)(1)"
        assert minor.scope == "33.021"

    def test_partial_term_matches(self, registry):
        assert registry.lookup_definition("virus")[0].cite == "33.01(10)"
        assert registry.lookup_definition("consent")[0].cite == "33.01(12)"

    def test_aliases_share_one_provision(self, registry):
        for alias in ("decrypt", "decrypted", "Decryption"):
            assert registry.lookup_definition(alias)[0].cite == "33.01(11-a)"

    def test_undefined_term_returns_nothing(self, registry):
        assert registry.lookup_definition("phishing") == []
        assert registry.lookup_definition("") == []

    def test_a_term_defined_twice_returns_both_scopes(self, registry):
        hits = registry.lookup_definition("identifying information")
        cites = {h.cite for h in hits}
        assert "33.01(14-a)" in cites
        assert "33.07(f)(2)" in cites


class TestAmountParsing:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("if the aggregate amount involved is less than $100", (None, 100.0)),
            ("is $100 or more but less than $750", (100.0, 750.0)),
            ("is $2,500 or more but less than $30,000", (2500.0, 30000.0)),
            ("is $300,000 or more", (300000.0, None)),
            ("no money mentioned here", (None, None)),
        ],
    )
    def test_ranges(self, text, expected):
        assert parse_amount_range(text) == expected


class TestPenalties:
    def test_33_02_ladder_is_complete_and_ordered(self, registry):
        ladder = registry.ladder("33.02")
        rungs = [r for r in ladder.rungs if r.cite.startswith("33.02(b-2)")]
        assert [r.grade for r in rungs] == [
            "Class C misdemeanor",
            "Class B misdemeanor",
            "Class A misdemeanor",
            "state jail felony",
            "felony of the third degree",
            "felony of the second degree",
            "felony of the first degree",
        ]
        assert [(r.min_amount, r.max_amount) for r in rungs] == [
            (None, 100.0),
            (100.0, 750.0),
            (750.0, 2500.0),
            (2500.0, 30000.0),
            (30000.0, 150000.0),
            (150000.0, 300000.0),
            (300000.0, None),
        ]

    def test_33_02_baseline_and_escalation(self, registry):
        rungs = [r for r in registry.ladder("33.02").rungs if r.cite == "33.02(b)"]
        grades = {r.grade for r in rungs}
        assert grades == {"Class B misdemeanor", "state jail felony"}
        escalation = next(r for r in rungs if r.grade == "state jail felony")
        assert "previously convicted" in escalation.condition
        assert "critical infrastructure facility" in escalation.condition

    def test_no_duplicate_rungs(self, registry):
        for ladder in registry.penalties:
            seen = [(r.grade, r.cite, r.condition) for r in ladder.rungs]
            assert len(seen) == len(set(seen)), ladder.section

    def test_alternate_grade_phrasing_is_caught(self, registry):
        """§ 33.022(b) says 'third degree felony', not 'felony of the third
        degree' -- both spellings appear in the chapter."""
        ladder = registry.ladder("33.022")
        assert ladder is not None
        assert any("third degree" in r.grade for r in ladder.rungs)

    def test_multiple_grades_in_one_provision(self, registry):
        """§ 33.07(c) grades Subsection (a) and (b) differently in one
        provision, plus an escalation."""
        grades = {r.grade for r in registry.ladder("33.07").rungs}
        assert "felony of the third degree" in grades
        assert "Class A misdemeanor" in grades

    def test_conditions_from_nested_subparagraphs_are_kept(self, registry):
        rung = next(
            r for r in registry.ladder("33.02").rungs if r.cite == "33.02(b-2)(7)"
        )
        assert "$300,000 or more" in rung.condition
        assert "more than one computer" in rung.condition

    def test_sections_without_grading_have_no_ladder(self, registry):
        assert registry.ladder("33.01") is None
        assert registry.ladder("33.04") is None

    def test_voting_machine_section_is_first_degree(self, registry):
        rungs = registry.ladder("33.05").rungs
        assert any(r.grade == "felony of the first degree" for r in rungs)


def test_registry_round_trip(registry, tmp_path):
    from cyberlaw.ingestion.registry import Registry

    path = tmp_path / "registry.json"
    registry.save(path)
    reloaded = Registry.load(path)
    assert len(reloaded.definitions) == len(registry.definitions)
    assert reloaded.lookup_definition("owner")[0].cite == "33.01(15)"
    assert len(reloaded.ladder("33.02").rungs) == len(registry.ladder("33.02").rungs)
