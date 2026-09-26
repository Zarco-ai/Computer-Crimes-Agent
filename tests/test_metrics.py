"""Metric tests.

These pin down a distinction that is easy to get wrong and which silently
corrupts every reported number: "acknowledged a scope limit" and "failed to
answer" are different things, measured differently, and applied to different
case types.
"""

from __future__ import annotations

from cyberlaw.evals import metrics as M
from cyberlaw.schemas import AgentAnswer, ToolCallRecord


def answer(text: str, *, citations=None, status="grounded", surfaced=None) -> AgentAnswer:
    return AgentAnswer(
        question="q",
        answer=text,
        citations=citations or [],
        status=status,
        trajectory=[
            ToolCallRecord(
                step=1,
                name="search_statute",
                arguments={},
                result_summary="",
                cites_surfaced=surfaced or [],
            )
        ],
    )


class TestRefusalVsGroundedAnswer:
    def test_cited_answer_with_limiting_language_is_not_a_failure_to_answer(self):
        """The r14 regression: this answer is correct and cited, but contains
        'does not provide', which a wording-only check reads as a refusal."""
        result = answer(
            "Chapter 33 does not provide a general defence for being a minor; "
            "however, under § 33.021(e) it is a defence that the actor was "
            "married to the minor.",
            citations=["33.021(e)"],
            surfaced=["33.021(e)"],
        )
        assert not M.failed_to_answer(result)
        # It does still acknowledge a limit -- which is the right bar for an
        # out-of-scope question, and the wrong one for an in-scope question.
        assert M.acknowledges_scope_limit(result)

    def test_bare_refusal_is_a_failure_to_answer(self):
        result = answer(
            "I can't answer that from Chapter 33.", citations=[], status="refused"
        )
        assert M.failed_to_answer(result)
        assert M.acknowledges_scope_limit(result)

    def test_ungrounded_is_always_a_failure(self):
        result = answer("...", citations=["33.02(a)"], status="ungrounded")
        assert M.failed_to_answer(result)

    def test_plain_grounded_answer_is_neither(self):
        result = answer(
            "Under § 33.02(a), knowingly accessing a computer without the "
            "effective consent of the owner is an offence.",
            citations=["33.02(a)"],
            surfaced=["33.02(a)"],
        )
        assert not M.failed_to_answer(result)
        assert not M.acknowledges_scope_limit(result)

    def test_scoped_answer_with_contrast_passes_the_out_of_scope_bar(self):
        """Declining the question asked, then offering Chapter 33 material as
        contrast, is honest and must not be scored as answering out of scope."""
        result = answer(
            "California Penal Code § 502 is outside Chapter 33, which is my only "
            "source. For contrast, Texas addresses unauthorised access in "
            "§ 33.02(a).",
            citations=["33.02(a)"],
            surfaced=["33.02(a)"],
        )
        assert M.acknowledges_scope_limit(result)


class TestCaseScoring:
    def _score(self, expected_refusal: bool, **kw) -> M.CaseScore:
        return M.CaseScore(
            id="x", question="q", status="grounded", answer="a",
            expected_refusal=expected_refusal, **kw
        )

    def test_out_of_scope_case_needs_acknowledgement(self):
        assert self._score(True, acknowledged_scope_limit=True).correct_refusal_behaviour
        assert not self._score(True, acknowledged_scope_limit=False).correct_refusal_behaviour

    def test_in_scope_case_needs_an_actual_answer(self):
        assert self._score(False, failed_to_answer=False).correct_refusal_behaviour
        assert not self._score(False, failed_to_answer=True).correct_refusal_behaviour

    def test_in_scope_case_is_not_penalised_for_limiting_language(self):
        score = self._score(False, acknowledged_scope_limit=True, failed_to_answer=False)
        assert score.correct_refusal_behaviour


class TestCitationPrecision:
    def test_unsupported_citation_lowers_precision(self):
        result = answer(
            "See § 33.02(a) and § 33.05(b).",
            citations=["33.02(a)", "33.05(b)"],
            surfaced=["33.02(a)"],
        )
        assert M.citation_precision(result) == 0.5

    def test_rung_inside_a_retrieved_ladder_counts_as_supported(self):
        result = answer("See § 33.02(b-2)(4).", surfaced=["33.02(b-2)"])
        assert M.citation_precision(result) == 1.0

    def test_no_citations_returns_none_not_perfect(self):
        """A refusal must not be averaged in as 100% precision."""
        assert M.citation_precision(answer("I can't answer that.")) is None


class TestPunishmentLeakDetection:
    def test_catches_confinement_and_fine_ranges(self):
        for text in (
            "That is punishable by 180 days to 2 years in state jail.",
            "It carries up to 10 years of confinement.",
            "The fine of up to $10,000 applies.",
            "This is punishable by confinement.",
            "You face 180 days in jail.",
        ):
            assert M.mentions_punishment_range(answer(text)), text

    def test_naming_the_grade_alone_is_fine(self):
        for text in (
            "The offence is a state jail felony under § 33.02(b).",
            "It is a Class B misdemeanor, escalating to a felony of the first degree.",
            "The aggregate amount involved is $2,500 or more but less than $30,000.",
        ):
            assert not M.mentions_punishment_range(answer(text)), text


def test_summarise_separates_the_two_populations():
    scores = [
        M.CaseScore(
            id="g1", question="q", status="grounded", answer="a",
            expected_refusal=False, failed_to_answer=False, citation_precision=1.0,
        ),
        M.CaseScore(
            id="r1", question="q", status="refused", answer="a",
            expected_refusal=True, acknowledged_scope_limit=True, failed_to_answer=True,
        ),
    ]
    summary = M.summarise(scores)
    assert summary["cases"] == 2
    # The refusal must not count against the in-scope false-refusal rate.
    assert summary["false_refusal_rate"] == 0.0
    assert summary["scope_acknowledged_out_of_scope"] == 1.0
