"""Command line interface.

    cyberlaw ingest              parse + chunk only (free)
    cyberlaw ingest --push       embed and upsert to Pinecone (costs money)
    cyberlaw ask "..."           run the agent, showing its trajectory
    cyberlaw define owner        deterministic definition lookup, no LLM
    cyberlaw penalty 33.02       deterministic penalty ladder, no LLM
    cyberlaw sections            chapter map
    cyberlaw search "..."        raw retrieval, no LLM
    cyberlaw eval                run the eval suite
    cyberlaw inspect             corpus + index + spend summary
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import get_settings

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Agentic RAG over Texas Penal Code Chapter 33 (Computer Crimes).",
)
console = Console()


def _corpus():
    from .corpus import CorpusNotBuilt, get_corpus

    try:
        return get_corpus()
    except CorpusNotBuilt as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


# --------------------------------------------------------------------------
@app.command()
def ingest(
    push: bool = typer.Option(
        False, "--push", help="Embed and upsert to the vector store (costs money)."
    ),
    keep: bool = typer.Option(
        False, "--keep", help="Do not clear the namespace before upserting."
    ),
    backend: str = typer.Option("pinecone", help="pinecone | memory"),
    html: Path = typer.Option(None, help="Override the source HTML path."),
):
    """Parse, chunk, and build the deterministic registries."""
    from .ingestion.index import ingest as run_ingest

    report = run_ingest(html, push=push, replace=not keep, backend=backend)

    table = Table(title="Ingest report", show_header=False, title_justify="left")
    table.add_row("sections", str(report.sections))
    table.add_row("chunks", str(report.chunks))
    table.add_row("chunk tokens", f"{report.total_chunk_tokens:,} (max {report.max_chunk_tokens})")
    table.add_row("definitions", str(report.definitions))
    table.add_row("penalty rungs", str(report.penalty_rungs))
    if report.pushed:
        table.add_row("namespace", report.namespace)
        table.add_row("embed tokens", f"{report.embed_tokens:,}")
        table.add_row("embed cost", f"${report.embed_cost:.6f}")
        table.add_row("upsert cost", f"${report.upsert_cost:.6f} ({report.write_units} WU)")
        table.add_row("[bold]total cost", f"[bold]${report.total_cost:.6f}")
    else:
        table.add_row("pushed", "[yellow]no — rerun with --push to index[/yellow]")
    console.print(table)
    for path in report.artifacts:
        console.print(f"  [dim]wrote[/dim] {path}")


# --------------------------------------------------------------------------
@app.command()
def ask(
    question: str = typer.Argument(..., help="Your question or fact pattern."),
    backend: str = typer.Option("pinecone", help="pinecone | memory"),
    model: str = typer.Option(None, help="Override the chat model."),
    show_trace: bool = typer.Option(True, "--trace/--no-trace", help="Show tool calls."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of prose."),
):
    """Ask the agent a question."""
    from .agent.loop import LegalAgent

    corpus = _corpus()
    agent = LegalAgent(corpus=corpus, backend=backend, model=model)

    with console.status("[dim]thinking…[/dim]"):
        result = agent.ask(question)

    if json_out:
        console.print_json(json.dumps(result.model_dump(), default=str))
        return

    if show_trace and result.trajectory:
        trace = Table(title="Agent trajectory", title_justify="left")
        trace.add_column("#", width=3)
        trace.add_column("tool", style="cyan")
        trace.add_column("arguments", overflow="fold")
        trace.add_column("result", overflow="fold")
        trace.add_column("ms", justify="right", width=6)
        for i, step in enumerate(result.trajectory, 1):
            args = ", ".join(f"{k}={v!r}" for k, v in step.arguments.items())
            trace.add_row(
                str(i),
                step.name,
                args or "—",
                f"[red]{step.error}[/red]" if step.error else step.result_summary,
                str(step.latency_ms),
            )
        console.print(trace)

    colour = {"grounded": "green", "refused": "yellow", "ungrounded": "red"}[result.status]
    console.print(
        Panel(
            result.answer,
            title=f"[{colour}]{result.status}[/{colour}]",
            border_style=colour,
        )
    )

    if result.citations:
        console.print("[bold]Citations verified against retrieved text:[/bold]")
        for cite in result.citations:
            src = next((s for s in result.sources if s.cite == cite), None)
            url = f" [dim]{src.url}[/dim]" if src else ""
            console.print(f"  § {cite}{url}")

    if result.verifier_notes:
        console.print("[yellow]Verifier notes:[/yellow]")
        for note in result.verifier_notes:
            console.print(f"  • {note}")

    c = result.cost
    console.print(
        f"[dim]{result.steps_used} step(s) · {c.total_tokens:,} tokens · "
        f"${c.total_cost:.6f}[/dim]"
    )


# --------------------------------------------------------------------------
@app.command()
def define(term: str):
    """Look up a statutory definition (deterministic, no LLM call)."""
    from .tools.statute_tools import make_look_up_definition

    console.print(make_look_up_definition(_corpus())(term=term).content)


@app.command()
def penalty(
    section: str,
    amount: float = typer.Option(None, help="Filter rungs by an aggregate USD amount."),
):
    """Show a section's offence grades (deterministic, no LLM call)."""
    from .tools.statute_tools import make_penalty_lookup

    result = make_penalty_lookup(_corpus())(section=section, aggregate_amount=amount)
    console.print(result.content)


@app.command()
def sections():
    """List every section of Chapter 33."""
    from .tools.statute_tools import make_list_sections

    console.print(make_list_sections(_corpus())().content)


@app.command()
def search(
    query: str,
    top_k: int = typer.Option(6, "--top-k", "-k"),
    backend: str = typer.Option("pinecone", help="pinecone | memory"),
    kind: str = typer.Option(None, help="offense | penalty | definition | defense | procedure"),
    expand: bool = typer.Option(False, "--expand", help="Expand hits to full sections."),
):
    """Raw retrieval with no LLM, for debugging chunking and recall."""
    from .retrieval.retriever import Retriever, build_store

    retriever = Retriever(build_store(backend), _corpus())
    hits, cost = retriever.search(query, top_k=top_k, kind=kind, expand_section=expand)

    table = Table(title=f"Top {len(hits)} for {query!r}", title_justify="left")
    table.add_column("score", justify="right", width=7)
    table.add_column("cite", style="cyan", width=18)
    table.add_column("kind", width=10)
    table.add_column("text", overflow="fold")
    for hit in hits:
        table.add_row(f"{hit.score:.3f}", hit.cite, hit.kind, hit.text[:220].replace("\n", " "))
    console.print(table)
    console.print(f"[dim]embed ${cost.embed_cost:.8f} · db ${cost.db_cost:.8f}[/dim]")


# --------------------------------------------------------------------------
@app.command("eval")
def eval_cmd(
    suite: str = typer.Option("all", help="all | golden | refusal"),
    limit: int = typer.Option(None, help="Only run the first N cases."),
    backend: str = typer.Option("pinecone", help="pinecone | memory"),
    ragas: bool = typer.Option(False, "--ragas", help="Also compute Ragas metrics."),
):
    """Run the eval suite and write a CSV report."""
    from .evals.run_eval import run_suite

    run_suite(suite=suite, limit=limit, backend=backend, with_ragas=ragas, console=console)


# --------------------------------------------------------------------------
@app.command()
def inspect(
    backend: str = typer.Option("pinecone", help="pinecone | memory"),
    remote: bool = typer.Option(True, "--remote/--local", help="Query the vector store."),
):
    """Show corpus stats, index stats, and cumulative spend."""
    settings = get_settings()
    corpus = _corpus()

    table = Table(title="Corpus", show_header=False, title_justify="left")
    table.add_row("sections", str(len(corpus.chapter.sections)))
    table.add_row("chunks", str(len(corpus.chunks)))
    tokens = [c.token_count for c in corpus.chunks]
    table.add_row("chunk tokens", f"{sum(tokens):,} (max {max(tokens)}, median {sorted(tokens)[len(tokens)//2]})")
    table.add_row("definitions", str(len(corpus.registry.definitions)))
    table.add_row("penalty rungs", str(sum(len(p.rungs) for p in corpus.registry.penalties)))
    table.add_row("chat model", settings.chat_model)
    table.add_row("embed model", settings.embed_model)
    console.print(table)

    if remote:
        try:
            from .retrieval.retriever import build_store

            stats = build_store(backend).stats()
            console.print(Panel(json.dumps(stats, indent=2), title="Vector store"))
        except Exception as exc:
            console.print(f"[yellow]Could not reach the vector store: {exc}[/yellow]")

    log = Path(settings.query_log)
    if log.exists():
        rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        spend = Table(title=f"Spend ({len(rows)} logged runs)", show_header=False, title_justify="left")
        spend.add_row("total", f"${sum(r.get('total_cost_usd', 0) for r in rows):.6f}")
        spend.add_row("tokens", f"{sum(r.get('total_tokens', 0) for r in rows):,}")
        statuses: dict[str, int] = {}
        for r in rows:
            statuses[r.get("status", "?")] = statuses.get(r.get("status", "?"), 0) + 1
        spend.add_row("statuses", ", ".join(f"{k}={v}" for k, v in sorted(statuses.items())))
        console.print(spend)


@app.command()
def ui():
    """Launch the Streamlit interface."""
    import subprocess
    import sys

    app_path = Path(__file__).parent / "ui" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)], check=False)


if __name__ == "__main__":
    app()
