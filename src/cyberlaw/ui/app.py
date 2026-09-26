"""Streamlit chat UI.

The point of the interface is not the chat bubble -- it is showing the
evidence next to the answer: which tools ran, what they returned, which
citations were verified against retrieved text, and what the run cost. A
legal assistant you cannot audit is not usable, so the audit trail is the
primary surface, not a debug panel.

Run with ``cyberlaw ui`` or ``streamlit run src/cyberlaw/ui/app.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Allow `streamlit run src/cyberlaw/ui/app.py` without installing the package.
SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cyberlaw.config import get_settings  # noqa: E402
from cyberlaw.corpus import CorpusNotBuilt, get_corpus  # noqa: E402

st.set_page_config(
    page_title="Chapter 33 Statutory Agent",
    page_icon="⚖️",
    layout="wide",
)

STATUS_STYLE = {
    "grounded": ("✅", "Every citation was verified against retrieved statutory text."),
    "refused": ("🚧", "The agent declined: the answer is not in Chapter 33."),
    "ungrounded": (
        "⛔",
        "The verifier rejected the draft answer's citations and the run fell back to a refusal.",
    ),
}


@st.cache_resource(show_spinner=False)
def load_agent(backend: str, model: str):
    from cyberlaw.agent.loop import LegalAgent

    return LegalAgent(corpus=get_corpus(), backend=backend, model=model)


@st.cache_resource(show_spinner=False)
def load_corpus():
    return get_corpus()


def sidebar(settings):
    st.sidebar.title("⚖️ Chapter 33 Agent")
    st.sidebar.caption("Texas Penal Code, Title 7, Ch. 33 — Computer Crimes")

    backend = st.sidebar.selectbox(
        "Vector store",
        ["pinecone", "memory"],
        help="`memory` embeds the 71 local chunks on first use — no Pinecone needed.",
    )
    model = st.sidebar.text_input("Chat model", value=settings.chat_model)

    try:
        corpus = load_corpus()
    except CorpusNotBuilt as exc:
        st.sidebar.error(str(exc))
        st.stop()

    with st.sidebar.expander("Corpus", expanded=False):
        tokens = [c.token_count for c in corpus.chunks]
        st.metric("Sections", len(corpus.chapter.sections))
        st.metric("Chunks", len(corpus.chunks))
        st.caption(
            f"max {max(tokens)} tokens/chunk · median {sorted(tokens)[len(tokens) // 2]}"
        )
        st.metric("Defined terms", len(corpus.registry.terms()))
        st.metric("Penalty rungs", sum(len(p.rungs) for p in corpus.registry.penalties))

    with st.sidebar.expander("Chapter map", expanded=False):
        for entry in corpus.toc():
            st.markdown(f"**§ {entry['section']}** {entry['heading'].title()}")

    st.sidebar.divider()
    st.sidebar.caption(
        "Not legal advice. Statutory text only. "
        "Offence **grades** come from Ch. 33; punishment **ranges** live in "
        "Ch. 12 and are deliberately out of scope."
    )
    return backend, model, corpus


def render_result(result):
    icon, explanation = STATUS_STYLE.get(result.status, ("", ""))

    st.markdown(result.answer)

    cols = st.columns(4)
    cols[0].metric("Status", f"{icon} {result.status}")
    cols[1].metric("Tool calls", len(result.trajectory))
    cols[2].metric("Tokens", f"{result.cost.total_tokens:,}")
    cols[3].metric("Cost", f"${result.cost.total_cost:.5f}")
    st.caption(explanation)

    if result.verifier_notes:
        st.warning("Verifier notes:\n\n" + "\n".join(f"- {n}" for n in result.verifier_notes))

    tab_cites, tab_trace, tab_sources = st.tabs(
        ["Verified citations", "Agent trajectory", "Retrieved text"]
    )

    with tab_cites:
        if not result.citations:
            st.info("No citations — the agent did not assert any statutory content.")
        for cite in result.citations:
            src = next((s for s in result.sources if s.cite == cite), None)
            if src and src.url:
                st.markdown(f"**§ {cite}** — [{src.heading.title()}]({src.url})")
            else:
                st.markdown(f"**§ {cite}**")

    with tab_trace:
        if not result.trajectory:
            st.info("No tools were called.")
        for i, step in enumerate(result.trajectory, 1):
            args = ", ".join(f"`{k}`={v!r}" for k, v in step.arguments.items()) or "—"
            label = f"{i}. `{step.name}`({args}) · {step.latency_ms} ms"
            with st.expander(label, expanded=False):
                if step.error:
                    st.error(step.error)
                st.write(step.result_summary)
                if step.cites_surfaced:
                    st.caption("Surfaced: " + ", ".join(f"§ {c}" for c in step.cites_surfaced))

    with tab_sources:
        if not result.sources:
            st.info("No vector-search results — the answer came from exact lookups.")
        for src in result.sources:
            with st.expander(f"§ {src.cite} · {src.kind} · score {src.score:.3f}"):
                st.code(src.text, language=None)
                if src.url:
                    st.caption(src.url)


def main():
    settings = get_settings()
    backend, model, corpus = sidebar(settings)

    st.title("Chapter 33 Statutory Agent")
    st.caption(
        "Ask about definitions, offences, grading, or describe a fact pattern. "
        "Every citation is checked against text the tools actually retrieved."
    )

    if "history" not in st.session_state:
        st.session_state.history = []

    examples = [
        "What is the legal definition of 'access'?",
        "A fired employee logs into a shared server with an old admin account and deletes project logs. What are they facing?",
        "Breach with intent to defraud and $40,000 in losses — what grade?",
        "How many years in prison is a state jail felony?",
    ]
    st.write("**Try:**")
    cols = st.columns(len(examples))
    clicked = None
    for col, text in zip(cols, examples):
        if col.button(text, use_container_width=True):
            clicked = text

    for entry in st.session_state.history:
        with st.chat_message("user"):
            st.write(entry["question"])
        with st.chat_message("assistant"):
            render_result(entry["result"])

    question = st.chat_input("Ask about Texas Penal Code Chapter 33…") or clicked
    if not question:
        return

    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Researching Chapter 33…"):
            try:
                agent = load_agent(backend, model)
                result = agent.ask(question)
            except Exception as exc:
                st.error(f"Run failed: {exc}")
                return
        render_result(result)

    st.session_state.history.append({"question": question, "result": result})


main()
