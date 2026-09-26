"""Eval runner: executes the suites, scores them, writes a CSV + summary."""

from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ..agent.loop import LegalAgent
from ..agent.prompts import PROMPT_VERSION
from ..config import get_settings
from ..corpus import get_corpus
from . import metrics as M

DATASETS = Path(__file__).parent / "datasets"


def load_cases(suite: str = "all") -> list[dict]:
    """Load eval cases. ``suite`` is ``all``, ``golden``, or ``refusal``."""
    files = []
    if suite in ("all", "golden"):
        files.append(DATASETS / "golden.jsonl")
    if suite in ("all", "refusal"):
        files.append(DATASETS / "out_of_scope.jsonl")
    if not files:
        raise ValueError(f"Unknown suite: {suite!r} (use all | golden | refusal)")

    cases: list[dict] = []
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cases.append(json.loads(line))
    return cases


def score_case(case: dict, result, latency_ms: int) -> M.CaseScore:
    expected_refusal = bool(case.get("expect_refusal"))
    return M.CaseScore(
        id=case["id"],
        question=case["question"],
        status=result.status,
        answer=result.answer,
        citations=result.citations,
        tools_used=[s.name for s in result.trajectory],
        steps=result.steps_used,
        citation_precision=M.citation_precision(result),
        section_recall=M.section_recall(result, case.get("expect_sections", [])),
        cite_hit=M.cite_hit(result, case.get("expect_cites", [])),
        tool_choice_hit=M.tool_choice_hit(result, case.get("expect_tools", [])),
        acknowledged_scope_limit=M.acknowledges_scope_limit(result),
        failed_to_answer=M.failed_to_answer(result),
        expected_refusal=expected_refusal,
        leaked_punishment=M.mentions_punishment_range(result),
        tokens=result.cost.total_tokens,
        cost_usd=result.cost.total_cost,
        latency_ms=latency_ms,
        notes="; ".join(result.verifier_notes),
    )


def run_suite(
    suite: str = "all",
    limit: int | None = None,
    backend: str = "pinecone",
    with_ragas: bool = False,
    console=None,
) -> dict:
    """Run a suite end to end and write ``evals_out/``."""
    settings = get_settings()
    settings.ensure_dirs()

    cases = load_cases(suite)
    if limit:
        cases = cases[:limit]

    corpus = get_corpus()
    agent = LegalAgent(corpus=corpus, backend=backend)

    scores: list[M.CaseScore] = []
    ragas_rows: list[dict] = []

    for i, case in enumerate(cases, 1):
        if console:
            console.print(f"[dim]{i}/{len(cases)}[/dim] {case['id']}: {case['question'][:72]}")
        started = time.perf_counter()
        # Eval runs are not logged to the spend log, to keep interactive
        # usage stats separate from benchmark noise.
        result = agent.ask(case["question"], log=False)
        latency = int((time.perf_counter() - started) * 1000)
        score = score_case(case, result, latency)
        scores.append(score)

        if with_ragas and not case.get("expect_refusal"):
            ragas_rows.append(
                {
                    "user_input": case["question"],
                    "retrieved_contexts": [s.text for s in result.sources] or [""],
                    "response": result.answer,
                    "reference": case.get("reference", ""),
                }
            )

    summary = M.summarise(scores)
    summary.update(
        {
            "suite": suite,
            "backend": backend,
            "prompt_version": PROMPT_VERSION,
            "model": agent.model,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_csv = settings.eval_out_dir / f"eval_{suite}_{stamp}.csv"
    out_json = settings.eval_out_dir / f"summary_{suite}_{stamp}.json"

    rows = [s.as_row() for s in scores]
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    out_json.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    if with_ragas and ragas_rows:
        summary["ragas"] = _run_ragas(ragas_rows, settings, stamp, console)
        out_json.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    if console:
        _print_summary(summary, scores, out_csv, out_json, console)
    return summary


def _run_ragas(rows: list[dict], settings, stamp: str, console=None) -> dict | None:
    """Optional Ragas pass. Isolated so a Ragas failure cannot lose the run."""
    try:
        import pandas as pd
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import answer_correctness, faithfulness

        result = evaluate(Dataset.from_list(rows), metrics=[faithfulness, answer_correctness])
        df = result.to_pandas()
        path = settings.eval_out_dir / f"ragas_{stamp}.csv"
        df.to_csv(path, index=False)
        numeric = df.select_dtypes("number").mean().to_dict()
        if console:
            console.print(f"[dim]ragas written to {path}[/dim]")
        return {k: float(v) for k, v in numeric.items()}
    except Exception as exc:
        if console:
            console.print(f"[yellow]Ragas step skipped: {exc}[/yellow]")
        return None


def _print_summary(summary: dict, scores, out_csv: Path, out_json: Path, console) -> None:
    from rich.table import Table

    def pct(value) -> str:
        return "—" if value is None else f"{value * 100:.1f}%"

    table = Table(title="Eval summary", show_header=False, title_justify="left")
    table.add_row("cases", str(summary["cases"]))
    table.add_row("citation precision", pct(summary.get("citation_precision")))
    table.add_row("expected-cite hit", pct(summary.get("cite_hit")))
    table.add_row("section recall", pct(summary.get("section_recall")))
    table.add_row("tool choice hit", pct(summary.get("tool_choice_hit")))
    table.add_row(
        "scope acknowledged (out of scope)",
        pct(summary.get("scope_acknowledged_out_of_scope")),
    )
    table.add_row("false refusal rate (in scope)", pct(summary.get("false_refusal_rate")))
    table.add_row("punishment-range leak rate", pct(summary.get("punishment_leak_rate")))
    table.add_row("avg steps", f"{summary.get('avg_steps') or 0:.1f}")
    table.add_row("total tokens", f"{summary['total_tokens']:,}")
    table.add_row("total cost", f"${summary['total_cost_usd']:.4f}")
    if summary.get("ragas"):
        for key, value in summary["ragas"].items():
            table.add_row(f"ragas:{key}", f"{value:.3f}")
    console.print(table)

    failures = [
        s
        for s in scores
        if not s.correct_refusal_behaviour
        or (s.citation_precision is not None and s.citation_precision < 1.0)
        or s.leaked_punishment
    ]
    if failures:
        detail = Table(title=f"{len(failures)} case(s) needing attention", title_justify="left")
        detail.add_column("id", width=5)
        detail.add_column("problem", overflow="fold")
        detail.add_column("question", overflow="fold")
        for s in failures:
            problems = []
            if not s.correct_refusal_behaviour:
                problems.append(
                    "answered out of scope without flagging it"
                    if s.expected_refusal
                    else "declined an in-scope question"
                )
            if s.citation_precision is not None and s.citation_precision < 1.0:
                problems.append(f"citation precision {s.citation_precision:.2f}")
            if s.leaked_punishment:
                problems.append("stated a punishment range")
            detail.add_row(s.id, "; ".join(problems), s.question[:70])
        console.print(detail)

    console.print(f"[dim]rows: {out_csv}[/dim]")
    console.print(f"[dim]summary: {out_json}[/dim]")
