# What Is an AI Agent? How, Where, and When to Use One

*A practical guide with real code from a production tax-computation agent*

---

## What is an agent?

A plain LLM call is a question followed by an answer. An agent is a program that uses an LLM as one component inside a larger loop that can **observe state, decide what to do next, call tools, and repeat** until a goal is reached.

The word "agent" is overloaded. In practice it describes a spectrum:

| Pattern | What it is | Example |
|---------|-----------|---------|
| **Prompt chain** | Fixed sequence of LLM calls | Summarise → translate → reformat |
| **RAG** | Retrieve relevant context, then generate | Answer a question using a document corpus |
| **Tool-using agent** | LLM decides which tools to call, in what order | Web search + calculator + code execution |
| **Multi-agent system** | Multiple specialised agents, each with its own tools and memory | Planner → researcher → writer → reviewer |

The minimal definition: **an agent is code where the LLM influences the control flow**, not just the output text.

---

## The anatomy of an agent

Every agent, regardless of framework, has the same four parts:

```
┌─────────────────────────────────────────────┐
│                   AGENT                     │
│                                             │
│  ┌──────────┐    ┌──────────┐    ┌───────┐ │
│  │  Memory  │◄───│   LLM    │───►│ Tools │ │
│  └──────────┘    └────┬─────┘    └───────┘ │
│                       │                     │
│                  ┌────▼─────┐               │
│                  │  State   │               │
│                  └──────────┘               │
└─────────────────────────────────────────────┘
```

**LLM** — the reasoning engine. Reads state, decides the next action. Never the only component; always one part of a larger system.

**Memory** — what the agent knows and remembers across steps. Can be as simple as a Python dict passed between functions, or as complex as a vector database for long-term retrieval.

**Tools** — functions the agent can call: database queries, web search, calculators, APIs, file I/O, subagent invocations. The LLM chooses tools; the runtime executes them safely.

**State** — the shared data structure that flows through every step. In LangGraph this is a `TypedDict`; in other frameworks it might be a dataclass or a dict. The entire conversation and all intermediate results live here.

---

## How agents are structured: graphs vs. loops

### The ReAct loop (the classic approach)

The earliest popular agent pattern is **ReAct** (Reason + Act):

```
while goal not reached:
    thought = llm("Given state, what should I do?")
    action  = llm("Which tool and with what arguments?")
    result  = execute(action)
    state   = update(state, result)
```

The LLM drives every iteration. Flexible, but hard to test, debug, or make deterministic.

### Graphs (the production approach)

A graph separates concerns: **each node is a named function with a single responsibility**. The LLM is only invoked at the nodes that need it.

This is how `ltcg-agent` is built, using LangGraph:

```python
# orchestrator/graph.py

class AgentState(TypedDict):
    financial_year: str
    broker_statement_path: str
    rules: TaxRuleSet | None
    ingestion_result: IngestionResult | None
    portfolio: Portfolio | None
    tax_events: list[TaxEvent]
    summary: TaxSummary | None
    explanation: str
    output_path: str

graph = StateGraph(AgentState)

graph.add_node("load_rules",      _node_load_rules)      # pure — no LLM
graph.add_node("ingest",          _node_ingest)           # pure — no LLM
graph.add_node("build_lots",      _node_build_lots)       # pure — no LLM
graph.add_node("calculate_tax",   _node_calculate_tax)    # pure — no LLM
graph.add_node("build_summary",   _node_build_summary)    # pure — no LLM
graph.add_node("explain",         _node_explain)          # ← only this node uses an LLM
graph.add_node("generate_report", _node_generate_report)  # pure — no LLM
```

Six of the seven nodes are pure Python. The LLM is called once, only to explain the already-computed result in plain English. This is the key insight:

> **Use the LLM for what it is good at — language — and use code for what code is good at — arithmetic, logic, and state management.**

---

## The role of RAG in an agent

RAG (Retrieval-Augmented Generation) is the most common tool an agent uses. Instead of relying on the LLM's baked-in knowledge (which may be outdated or hallucinated), RAG retrieves relevant text from a curated corpus and injects it into the prompt.

In `ltcg-agent`, the RAG index holds 15 chunks of authoritative statutory text — the actual words of §112, Rule 115, §70, §74, and so on — stored in a FAISS vector index:

```python
# rag/index.py

class RagIndex:
    @classmethod
    def build(cls, chunks: list[CorpusChunk], embeddings: Embeddings) -> "RagIndex":
        documents = [_chunk_to_document(c) for c in chunks]
        store = FAISS.from_documents(documents, embeddings)
        return cls(store, {c.chunk_id: c for c in chunks})

    def query(self, topic: str, k: int = 4) -> list[CorpusChunk]:
        docs = self._store.similarity_search(topic, k=k)
        return [self._chunk_map[doc.metadata["chunk_id"]] for doc in docs]
```

When the agent explains a tax result, it retrieves the four most relevant chunks and injects them into the LLM prompt alongside the computed numbers:

```python
# rag/explainer.py

def explain(topic, computed_result, index, ruleset, llm, as_of=None) -> Explanation:
    chunks = index.query(topic, k=4)
    numbers_json = computed_result.model_dump_json(indent=2)   # exact engine output
    messages = [
        SystemMessage(content=_EXPLAIN_SYSTEM),                # 4 hard constraints
        HumanMessage(content=_EXPLAIN_HUMAN.format(
            topic=topic,
            numbers_json=numbers_json,      # ← LLM sees the numbers but must not alter them
            rule_text=_format_chunks(chunks),
        )),
    ]
    response = llm.invoke(messages)
    return Explanation(plain_english=str(response.content), cited_chunks=chunks, ...)
```

The system prompt enforces four hard constraints, including: *"All monetary figures MUST be copied verbatim from the engine output. You MUST NOT recompute, round differently, adjust, or substitute any figure."*

This is the safety contract that makes the explanation trustworthy: the LLM explains the math, but cannot change it.

---

## Where to use agents

Agents earn their complexity in situations where:

### 1. The task has a variable number of steps
A fixed chain of prompts works when you know exactly what to do. Use an agent when the number or type of steps depends on the input. Example: ingesting a broker statement that might be IBKR format, Schwab format, or an unknown CSV that needs LLM-assisted column mapping.

### 2. The task requires external tools
If the answer requires calling an API, querying a database, running code, or looking something up — use an agent. The LLM alone cannot reliably do any of these.

### 3. The task requires multi-step reasoning with intermediate results
When each step's output becomes the next step's input, and the whole sequence needs to be auditable, a graph agent with named nodes makes each step inspectable and testable independently.

### 4. Different subtasks require different capabilities
An agent can route: simple questions to a cheap model, complex reasoning to a capable model, arithmetic to a calculator, and statute retrieval to a vector store.

---

## When NOT to use an agent

Agents add latency, cost, and failure modes. Use a simpler approach when:

**A single well-engineered prompt is enough.** If the task fits in one context window and the output is a blob of text, a chain is overkill.

**The output must be auditable to the penny.** LLMs hallucinate. Never let an LLM compute a number that will be filed with a government. Write the arithmetic in code, then let the LLM narrate the result.

**You do not have test coverage.** An agent without evals is a liability. If you cannot verify the output of each node against known-good examples, you do not know what your agent is doing.

**Latency is the primary constraint.** Every LLM call is 0.5–5 seconds. A six-node graph with one LLM call is fast. A ReAct loop with ten tool-use iterations is slow.

---

## Where agents are used in production today

| Domain | What the agent does |
|--------|---------------------|
| Tax / finance | Ingests documents, applies rules, explains results — exactly this project |
| Legal | Retrieves case law, drafts clauses, flags jurisdiction-specific risks |
| Customer support | Classifies intent, retrieves policy docs, escalates complex cases |
| Code generation | Reads failing tests, proposes fixes, runs tests, iterates |
| Data pipelines | Parses unstructured documents, normalises schemas, validates output |
| Research | Plans a research question, searches papers, synthesises findings |
| DevOps | Reads alerts, identifies probable cause, queries runbooks, drafts a response |

The common thread: **structured external knowledge + LLM reasoning + code-enforced guardrails**.

---

## How to build one: a practical checklist

### 1. Define state first
Write the `TypedDict` or dataclass before writing any nodes. State is the contract between all components.

```python
class AgentState(TypedDict):
    input_path: str
    parsed_data: ParsedData | None
    computed_result: Result | None
    explanation: str
```

### 2. Separate pure nodes from LLM nodes
Every node should be testable in isolation. Nodes that call an LLM get a mock in tests; pure nodes get real inputs and exact expected outputs.

### 3. Version your rules as data, not code
Tax rates change. Prompts change. Anything that changes with time belongs in a config file, not in source code.

```yaml
# rules/configs/fy2526.yaml
ltcg:
  rate_pct:
    value: 12.5
    effective_from: "2024-07-23"
    source: "Finance (No. 2) Act 2024 s.7 ..."
```

### 4. Make every figure traceable
Every number that flows through the system should carry a provenance record: where it came from, what rate was applied, on what date. The `ConvertedAmount` type in this project stores all of this:

```python
@dataclass(frozen=True)
class ConvertedAmount:
    usd_cents: int
    inr_paise: int
    rate: int           # TTBR paise per USD
    rate_date: date     # the date on which this rate was fetched
    source: str         # "sbi_ttbr" | "seed_cache" | "lot_record"
```

### 5. Write evals before you write the agent
Golden-scenario tests — input → expected output — are the only way to know your agent is correct. Write them first, from real examples, before wiring up the graph.

```yaml
# evals/golden_scenarios.yaml
- id: ltcg_basic_24m_threshold
  description: Single AAPL lot, held 25 months, sold at gain
  acquisition_date: 2022-10-01
  disposal_date: 2024-11-15
  expected_term: long
  expected_ltcg_tax_paise: 143750
```

### 6. Add freshness checks to external knowledge
Any corpus, rulebook, or external dataset can become stale. Build a check that warns explicitly when data predates a known revision date.

```python
def check_freshness(corpus_max_date: date, rules_effective_from: date) -> FreshnessWarning | None:
    stale_corpus = corpus_max_date < LATEST_BUDGET_DATE
    stale_rules = rules_effective_from < LATEST_BUDGET_DATE
    if not stale_corpus and not stale_rules:
        return None
    # ... return a structured warning
```

### 7. Never skip the disclaimer
Any agent that produces output a human might act on — financial, legal, medical — must carry a disclaimer at every output surface. Hard-code it in the model, not in the template, so it cannot be accidentally omitted.

```python
class TaxEstimate(BaseModel):
    total_tax_paise: int
    disclaimer: str = _DISCLAIMER   # always present, always the same text
```

---

## The four questions to ask before building an agent

1. **Is the task multi-step with uncertain path?** If no — write a function.
2. **Does the LLM add genuine value, or just latency?** If the latter — remove it.
3. **Can I write evals that verify correctness?** If no — the agent is not ready to ship.
4. **Is every number that reaches the user traceable to code, not an LLM?** If no — redesign.

Agents are powerful because they compose reasoning with tools and state. They are dangerous for the same reason. The discipline of keeping LLMs in their lane — language, not arithmetic; explanation, not decision — is what separates a reliable agent from an unpredictable one.

---

## Further reading

- [LangGraph documentation](https://langchain-ai.github.io/langgraph/) — graph-based agent orchestration
- [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629) — the paper that named the pattern
- [Anthropic's model documentation](https://docs.anthropic.com) — tool use, prompt engineering, system prompts
- [LangChain LCEL guide](https://python.langchain.com/docs/concepts/lcel/) — composable chains without deprecated `langchain.chains`

---

*This article uses [ltcg-agent](https://github.com/ashishkumar2/ltcg-agent) as its running example. All code snippets are taken from the actual source. The tax-computation logic in that project is for educational purposes only and must be verified by a Chartered Accountant before use in a filing.*
