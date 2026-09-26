# Chapter 33 Statutory Agent

An agentic RAG system over a single, self-contained legal corpus: **Texas Penal
Code, Title 7, Chapter 33 — Computer Crimes** (ten sections, 46 KB of HTML).

It answers definitional questions, offence-grading questions, and cybercrime
fact patterns with a verbatim statutory citation for every claim — and refuses
when the answer is not in Chapter 33.

```console
$ cyberlaw ask "A fired employee logs into a shared server with an old admin
                account and deletes project logs out of spite. What are they facing?"

  #  tool             arguments                                   result                    ms
  1  search_statute   query='unauthorized access to a computer'    6 hits: 33.02(b-1), …    764
  2  search_statute   query='deleting data from a computer'        6 hits: 33.023(b), …     553
  3  penalty_lookup   section='33.02'                              33.02: 9 rungs             0
  4  penalty_lookup   section='33.022'                             33.022: 1 rung             0
  5  penalty_lookup   section='33.023'                             33.023: 12 rungs           0

╭────────────────────────── grounded ──────────────────────────╮
│ - Knowingly accessed a computer system without the effective  │
│   consent of the owner — § 33.02(a).                          │
│ - Deleting property with intent to harm falls under           │
│   § 33.02(b-1).                                               │
│ - Grade is a Class B misdemeanor or state jail felony         │
│   depending on priors and system ownership — § 33.02(b).      │
│ What would decide it: aggregate amount; prior convictions;    │
│ ownership of the system.                                      │
╰───────────────────────────────────────────────────────────────╯
3 steps · 8,610 tokens · $0.001482
```

---

## The problem this was built to fix

The first version of this project chunked **one vector per whole section**. Its
own eval output ([`docs/baseline_whole_section_eval.csv`](docs/baseline_whole_section_eval.csv), row 1) shows the failure:

| Query | Retrieved |
| --- | --- |
| "Under Chapter 33, what is the legal definition of 'Access'?" | **§ 33.02(a)** — *Breach of Computer Security* |

§ 33.01 is a ~2,500-token wall of 23 definitions, so its embedding averaged out
to mush and lost to a short, specific offence provision. With `top_k=1` there
was no recovery.

After re-chunking to atomic subsections:

| Query | Rank 1 | Rank 2 |
| --- | --- | --- |
| "Under Chapter 33, what is the legal definition of 'Access'?" | **§ 33.01(1) — 0.740** | § 33.022(a) — 0.476 |

---

## Design

### Two of the three "RAG" questions are not retrieval questions

The insight the architecture turns on: Chapter 33's definitions and penalty
grades are **closed, enumerable sets**. Answering them with vector search
invites a near-miss; answering them from a parsed table cannot hallucinate and
costs nothing.

| Tool | Kind | Why |
| --- | --- | --- |
| `search_statute` | semantic | Open-ended scenarios — genuinely fuzzy. |
| `look_up_definition` | **exact** | 33 defined terms in a closed list. Also reports whether a term is chapter-wide or section-scoped. |
| `penalty_lookup` | **exact** | 42 grading rungs parsed with their conditions and dollar windows. |
| `get_section` | **exact** | Verbatim text by section number. |
| `list_sections` | **exact** | Chapter map; prevents section mix-ups. |

Four of five tools never touch the vector store.

### Chunking: atomic subsections with parent expansion

One chunk per top-level provision, nested children rolled in, section lead-in
prepended, and an orienting first line so a definition chunk reads as an answer
to "what does X mean":

```
Statutory definition of "Access". Tex. Penal Code § 33.01(1) — Definitions
In this chapter:
(1)  "Access" means to approach, instruct, communicate with, store data in, …
```

**71 chunks · median 86 tokens · max 324** (was 10 chunks, one ~2,500 tokens).

Children are *not* split out: a chunk reading "the government; or" carries no
retrievable signal and its citation would be meaningless. Each chunk keeps
`parent_section`, so `--expand` trades precision for completeness after a hit.
Fixed-size splitters were rejected because they cut mid-provision, which makes
a citation ambiguous — the one thing this system exists to prevent.

### The citation verifier

A prompt saying "only cite what you retrieved" is a *request*. This is the
check:

1. Extract every `§ 33.x` citation from the draft answer.
2. Match each against the provisions tools actually returned. Ancestor and
   descendant citations pass (retrieving the `(b-2)` ladder supports citing
   `(b-2)(4)`); a sibling section does not.
3. Reject citations to chapters outside the corpus — while allowing the 12
   cross-references Chapter 33's own text contains (§ 31.01, § 32.51, § 15.01, …).
4. On failure, tell the model exactly what was unsupported and retry once.
5. Still failing → return an explicit refusal rather than uncited law.

It works. Asked *"Does section 33.09 make cryptocurrency theft a felony?"*:

```
Verifier notes:
  • § 33.09 is not a real Chapter 33 section.
  • Unsupported citations (no tool returned them): 33.09
→ status: ungrounded, answer replaced with a refusal
```

### No punishment ranges, by construction

Chapter 33 assigns an offence **grade**; the confinement and fine ranges live in
**Penal Code Chapter 12**, which is not in this corpus. `penalty_lookup` says so
in its own output, the prompt forbids stating ranges, and an eval metric
measures leakage. Current leak rate: **0%**.

---

## Results

42 cases, `gpt-4o-mini`, prompt `v2.0-agentic`
([summary](docs/eval_summary_latest.json) · [per-case rows](docs/eval_rows_latest.csv)):

| Metric | Result |
| --- | --- |
| Citation precision (every cite actually retrieved) | **100.0%** |
| Expected-citation hit | 94.8% |
| Section recall | 96.6% |
| Tool-choice hit | 82.8% |
| Scope acknowledged on out-of-scope questions | 92.3% (12/13) |
| False refusal rate on in-scope questions | 3.4% (1/29) |
| Punishment-range leak rate | **0.0%** |
| Avg steps · total cost | 2.0 · **$0.026** for the whole suite |

Two suites, because it is trivial to win one by destroying the other:
**28 in-scope** cases (definitions, offences, grading, scenarios) and **14
out-of-scope** cases (Chapter 12 ranges, CFAA, Chapter 31/32, civil remedies,
case law, another state, and a nonexistent § 33.09).

### Known limitations

Both remaining failures are real and are left red rather than tuned away.

**`r05` — the verifier checks grounding, not relevance.** Asked for the elements
of *fraudulent use or possession of identifying information* (§ 32.51, outside
the corpus), the agent described § 33.02(b-1) and labelled it with the other
offence's name. Citation precision stays 100% because § 33.02(b-1) *was*
retrieved. The verifier proves a provision was read — not that it answers the
question asked. Closing this needs a relevance check, not a grounding check.

**`g28` — the model sometimes skips tools, and the backstop fires.** Asked
whether conduct can be prosecuted under Chapter 33 *and* another chapter, the
agent answered from memory with no tool calls. The answer is § 33.02(d), which
it never retrieved. The verifier caught the uncited assertion and refused. The
safety property held; the recall did not.

These are opposite failure modes, and the tension is the honest finding:
hardening the scope rules to fix `r05`-style substitution raised in-scope
refusals, and relaxing them did the reverse.

### Not added: Chapter 12

`penalty_lookup` could return "180 days–2 years" instead of "state jail felony"
by ingesting Penal Code §§ 12.21–12.35 as a second namespace. It is deliberately
absent: the honest answer is *"Chapter 33 gives the grade; the range is Chapter
12, which I can't see,"* and fabricating the range would be exactly the failure
this project is about. `ingest` takes an `html_path`, so adding it is a small
change — with a separate namespace so citations stay honest about their source.

---

## Layout

```
data/raw/pe.33.htm              source statute (public record)
data/processed/                  generated: chapter33.json, chunks.jsonl, registry.json
src/cyberlaw/
  config.py                      pydantic-settings: paths, models, prices, top_k
  schemas.py                     Provision · Section · Chunk · Citation · AgentAnswer
  corpus.py                      loads the three artifacts once per process
  ingestion/
    parse_html.py                flat <p> stream -> citable provision tree
    chunk.py                     the chunking strategy (swap this one file)
    registry.py                  definition + penalty tables
    index.py                     embed & upsert, with cost reporting
  retrieval/
    store.py                     VectorStore Protocol + InMemoryStore
    pinecone_store.py            Pinecone implementation
    retriever.py                 embed -> search -> optional section expansion
  tools/                         the five tools + registry/dispatch
  agent/
    loop.py                      native OpenAI tool-calling loop
    prompts.py                   versioned system prompt
    verifier.py                  the citation gate
  evals/                         golden + out-of-scope sets, metrics, runner
  ui/app.py                      Streamlit chat with an audit trail
tests/                           95 tests, all offline
```

Seams sit where experiments happen: chunking is one module behind a
`chunks.jsonl` contract; the store is a Protocol, so Pinecone vs. local is a
config line; tools are a registry, so adding one is a file plus an entry. All 95
tests run with **no API key and no network** — parsing, chunking, the registry,
the verifier, and the four deterministic tools are all pure functions over local
data.

---

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ui,evals,dev]"
cp .env.example .env          # add OPENAI_API_KEY and pinecone_apikey
```

```bash
cyberlaw ingest               # parse + chunk + registries (free, no API calls)
cyberlaw ingest --push        # embed & upsert  (~$0.009 for the whole chapter)
```

Vectors go to namespace `ch33-atomic-v2`, leaving any previous `__default__`
vectors intact as a rollback and A/B baseline.

```bash
cyberlaw ask "What is the penalty for breach of computer security?"
cyberlaw define "effective consent"      # deterministic, no LLM call
cyberlaw penalty 33.023 --amount 40000   # deterministic, no LLM call
cyberlaw search "ransomware" -k 5        # raw retrieval, no LLM
cyberlaw sections
cyberlaw eval --suite all --ragas
cyberlaw inspect
cyberlaw ui                              # Streamlit
pytest                                   # 95 tests, offline
```

No Pinecone? `--backend memory` embeds the 71 local chunks on first use and
brute-forces cosine similarity — instant at this corpus size, and the parity
reference for the Pinecone path.

## Cost

Every run appends token and dollar accounting to `logs/query_costs.jsonl`;
`cyberlaw inspect` aggregates it.

| | |
| --- | --- |
| Full ingest (embed + upsert) | $0.0090 |
| One agent question | ~$0.0015 |
| Full 42-case eval suite | $0.0263 |

---

**Not legal advice.** This is a retrieval system over one chapter of statutory
text, built as an engineering exercise. It states offence grades, never
punishment ranges, and cites only text it retrieved. Consult a licensed Texas
attorney.
