"""The agent loop: native OpenAI tool calling, no framework.

The whole control flow is here and readable top to bottom:

    system prompt + question
      -> model picks tools
      -> we execute them and feed results back
      -> repeat until the model answers or the step cap is hit
      -> citation verifier gates the answer
      -> one retry with the violation explained, then refuse

Everything the model saw and did is recorded in ``AgentAnswer.trajectory``,
which is what the CLI prints, the UI renders, and the eval harness scores.
"""

from __future__ import annotations

import json
import time
from functools import lru_cache

from openai import OpenAI

from ..config import get_settings
from ..corpus import Corpus, get_corpus
from ..observability.costs import cost_from_usage, log_run
from ..retrieval.retriever import Retriever, build_store
from ..schemas import AgentAnswer, CostRecord, Retrieved, ToolCallRecord
from ..tools.base import ToolRegistry
from ..tools.statute_tools import build_tools
from .prompts import PROMPT_VERSION, REFUSAL_TEXT, SYSTEM_PROMPT, verifier_feedback
from .verifier import looks_like_refusal, verify


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set (see .env.example).")
    return OpenAI(api_key=settings.openai_api_key)


class LegalAgent:
    """Scenario-analysis agent over Texas Penal Code Chapter 33."""

    def __init__(
        self,
        tools: ToolRegistry | None = None,
        corpus: Corpus | None = None,
        *,
        backend: str = "pinecone",
        model: str | None = None,
    ):
        settings = get_settings()
        self.corpus = corpus or get_corpus()
        self.tools = tools or build_tools(
            Retriever(build_store(backend), self.corpus), self.corpus
        )
        self.model = model or settings.chat_model
        self.known_sections = set(self.corpus.section_numbers())
        self.allowed_foreign = self.corpus.cross_references()

    # ------------------------------------------------------------------
    def ask(self, question: str, *, log: bool = True) -> AgentAnswer:
        settings = get_settings()

        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]

        trajectory: list[ToolCallRecord] = []
        sources: list[Retrieved] = []
        supported: set[str] = set()
        cost = CostRecord()
        retries_left = settings.max_verifier_retries
        verifier_notes: list[str] = []
        status = "grounded"
        answer_text = ""
        step = 0

        while step < settings.max_agent_steps:
            step += 1
            response = _client().chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools.specs(),
                tool_choice="auto",
                temperature=settings.temperature,
            )
            cost = cost.merge(cost_from_usage(response.usage))
            choice = response.choices[0].message

            # --- the model wants tools ---------------------------------
            if choice.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": choice.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in choice.tool_calls
                        ],
                    }
                )

                for tc in choice.tool_calls:
                    started = time.perf_counter()
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError as exc:
                        args = {}
                        result = None
                        error = f"could not parse arguments: {exc}"
                    else:
                        result = self.tools.call(tc.function.name, args)
                        error = result.error

                    if result is None:
                        content = f"Tool call failed: {error}"
                        record_cites: list[str] = []
                    else:
                        content = result.content
                        record_cites = result.cites
                        supported.update(result.cites)
                        sources.extend(result.sources)
                        cost = cost.merge(result.cost)

                    trajectory.append(
                        ToolCallRecord(
                            step=step,
                            name=tc.function.name,
                            arguments=args,
                            result_summary=(result.summary if result else content[:120]),
                            cites_surfaced=record_cites,
                            latency_ms=int((time.perf_counter() - started) * 1000),
                            error=error,
                        )
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": content,
                        }
                    )
                continue

            # --- the model produced an answer: verify it ---------------
            answer_text = (choice.content or "").strip()
            refusal = looks_like_refusal(answer_text)
            verdict = verify(
                answer_text,
                supported,
                known_sections=self.known_sections,
                allowed_foreign=self.allowed_foreign,
                require_citation=not refusal,
            )

            if verdict.ok:
                status = "refused" if refusal else "grounded"
                break

            verifier_notes.extend(verdict.notes)
            if retries_left <= 0:
                # Out of retries with an ungrounded answer: refuse rather
                # than emit law we cannot back up.
                answer_text = REFUSAL_TEXT
                status = "ungrounded"
                break

            retries_left -= 1
            bad = verdict.unsupported + verdict.foreign
            messages.append({"role": "assistant", "content": answer_text})
            messages.append(
                {"role": "user", "content": verifier_feedback(bad, sorted(supported))}
            )
        else:
            # Step cap reached without a final answer.
            verifier_notes.append(
                f"Stopped after {settings.max_agent_steps} steps without a final answer."
            )
            answer_text = answer_text or REFUSAL_TEXT
            status = "ungrounded"

        final = AgentAnswer(
            question=question,
            answer=answer_text,
            citations=(
                verify(
                    answer_text,
                    supported,
                    known_sections=self.known_sections,
                    allowed_foreign=self.allowed_foreign,
                    require_citation=False,
                ).citations
            ),
            sources=_dedupe_sources(sources),
            trajectory=trajectory,
            status=status,
            verifier_notes=list(dict.fromkeys(verifier_notes)),
            cost=cost,
            steps_used=step,
        )

        if log:
            log_run(
                question,
                cost,
                status=status,
                steps=step,
                tools_used=[t.name for t in trajectory],
                prompt_version=PROMPT_VERSION,
            )
        return final


def _dedupe_sources(sources: list[Retrieved]) -> list[Retrieved]:
    """Keep the highest-scoring instance of each cited provision."""
    best: dict[str, Retrieved] = {}
    for s in sources:
        existing = best.get(s.cite)
        if existing is None or s.score > existing.score:
            best[s.cite] = s
    return sorted(best.values(), key=lambda s: -s.score)
