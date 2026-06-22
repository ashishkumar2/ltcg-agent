# ltcg-agent

A production-grade AI agent that computes Indian capital gains tax on US-listed equity for Indian residents. It reads broker statements from IBKR or Schwab, applies FIFO lot matching, converts USD proceeds to INR using SBI TTBR rates (Rule 115), applies §112 / §111A / §70 / §74 rules, finds tax-saving opportunities, and produces a plain-language explanation citing the exact statutory provisions — all with every rupee figure traceable to its source.

**Not tax advice.** All output must be verified by a Chartered Accountant before filing.

---

## Why this exists

Indian residents holding US equity face a paperwork problem. Each sale requires:

1. Identifying which lots to close (FIFO)
2. Converting both the acquisition cost and disposal proceeds to INR using SBI TTBR on the respective dates (Rule 115)
3. Classifying the holding as short-term or long-term (24-month threshold post Finance Act 2024)
4. Applying the correct rate — 12.5% flat under §112(1)(c)(iii), no indexation, no ₹1.25L exemption (that is §112A, which does not apply to foreign equity)
5. Running set-off: STCL offsets both STCG and LTCG (§70(2)); LTCL offsets LTCG only (§70(3))
6. Computing surcharge at the correct slab (NOT capped at 15% for §112) and 4% H&E cess

This agent automates steps 1–6, surfaces harvest and crossover opportunities, and explains every figure by retrieving the relevant statutory text from a curated RAG corpus.

---

## Architecture

The agent is a LangGraph `StateGraph` — six deterministic nodes in sequence, with an LLM invoked only for plain-language explanation (never for arithmetic):

```
broker statement
      │
      ▼
 [load_rules]  ← versioned YAML (fy2324 / fy2425 / fy2526)
      │
      ▼
  [ingest]     ← IBKR or Schwab CSV adapter
      │
      ▼
[build_lots]   ← FIFO lot matching + SBI TTBR conversion on acquisition date
      │
      ▼
[calculate_tax]← realized gains, §112 / §111A classification, §70 set-off
      │
      ▼
[build_summary]← FyAggregates → SetoffResult → TaxEstimate (surcharge + cess)
      │
      ▼
  [explain]    ← RAG retriever → LLM explains WHY (numbers injected verbatim)
      │
      ▼
[generate_report] → HTML / JSON report
```

### Non-negotiable design rules

| Rule | Why |
|------|-----|
| LLM never does money math | LLMs hallucinate numbers; all arithmetic is pure Python with `Decimal` |
| Tax rules are versioned data | A YAML file per FY; rules config changes without touching engine code |
| Every INR figure is traceable | `ConvertedAmount` stores USD cents, INR paise, TTBR rate, rate date, and source |
| Corpus freshness is checked | Warns if the RAG index or rules config predates the latest Union Budget |
| Output is not tax advice | Every surface — `TaxEstimate`, `OpportunityReport`, `Explanation` — carries a CA disclaimer |

---

## Quick start

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/ashishkumar2/ltcg-agent
cd ltcg-agent

# Create venv and install
uv venv --python 3.12
uv pip install -e ".[dev]" "langchain-community>=0.3" "faiss-cpu>=1.8"

# Copy environment template
cp .env.example .env
# Edit .env — set OPENAI_API_KEY at minimum
```

### Environment variables

```bash
OPENAI_API_KEY=sk-...          # required for explain node and LLM normalizer
OPENAI_MODEL=gpt-4o            # default gpt-4o
SBI_TTBR_CACHE_PATH=.cache/ttbr.json   # optional; avoids repeat fetches
```

---

## Usage

### Run the full agent

```python
from pathlib import Path
from ltcg_agent.orchestrator.graph import build_graph, AgentState
from ltcg_agent.ingest.ibkr import IBKRAdapter
from ltcg_agent.ingest.schwab import SchwabAdapter
from ltcg_agent.fx.sbi_ttbr import TTBRClient
from ltcg_agent.rag.retriever import RagRetriever
from ltcg_agent.rag.index import RagIndex
from ltcg_agent.rag.corpus import load_corpus
from ltcg_agent.report.generator import ReportGenerator
from langchain_openai import ChatOpenAI

corpus = load_corpus()
index = RagIndex.build(corpus, OpenAIEmbeddings())
retriever = RagRetriever(index, model="gpt-4o")
graph = build_graph(
    adapters=[IBKRAdapter(), SchwabAdapter()],
    ttbr_client=TTBRClient(),
    retriever=retriever,
    generator=ReportGenerator(),
)
compiled = graph.compile()

result = compiled.invoke(AgentState(
    financial_year="2025-26",
    broker_statement_path="my_trades.csv",
    broker="ibkr",
    output_path="report.html",
    # ... other fields default to None / []
))
print(result["explanation"])
```

### Use engine functions directly

```python
from datetime import date
from ltcg_agent.engine.gains import classify_term, realized_gain, aggregate_for_fy, apply_setoff, estimate_tax
from ltcg_agent.rules.loader import load_rules_for_date

ruleset = load_rules_for_date(date(2025, 10, 1))  # resolves to fy2526

# classify holding period
term = classify_term(date(2023, 1, 15), date(2025, 4, 10), ruleset)
# → "long"  (held > 24 months per §2(42A) post FA2024)
```

### Find tax-saving opportunities

```python
from ltcg_agent.engine.opportunities import build_opportunity_report

report = build_opportunity_report(
    lots=portfolio.lots,
    fy_agg=aggregates,
    setoff=setoff_result,
    as_of=date.today(),
    price_source=my_price_source,   # implement PriceSource protocol
    stcg_marginal_rate_pct=Decimal("30"),
    taxable_income_inr=5_000_000,
    regime="old",
    ruleset=ruleset,
)
# report.harvest_opportunities — lots at a loss sorted by tax saved
# report.crossover_opportunities — gains lots approaching the 24-month threshold
# report.carry_forward — unabsorbed losses eligible for 8-year carry-forward
```

### Explain a computed result

```python
from ltcg_agent.rag.explainer import explain
from ltcg_agent.rag.index import RagIndex
from ltcg_agent.rag.corpus import load_corpus

index = RagIndex.build(load_corpus(), embeddings)
explanation = explain(
    topic="ltcg_rate",
    computed_result=tax_estimate,   # any Pydantic BaseModel
    index=index,
    ruleset=ruleset,
    llm=ChatOpenAI(model="gpt-4o"),
)
print(explanation.plain_english)
# → "Under Section 112(1)(c)(iii) as amended by Finance (No. 2) Act 2024,
#    the LTCG of ₹X is taxed at 12.5% flat, yielding ₹Y..."
```

---

## Project structure

```
ltcg_agent/
├── engine/
│   ├── gains.py          classify_term, realized_gain, aggregate_for_fy,
│   │                     apply_setoff, estimate_tax — pure functions, no LLM
│   ├── opportunities.py  find_harvest_opportunities, find_crossover_opportunities,
│   │                     find_carry_forward, build_opportunity_report
│   ├── harvesting.py     HarvestingEngine (lot-level orchestration)
│   ├── escalation.py     EscalationCase — complex cases flagged for CA review
│   └── lot_matcher.py    FIFO matching across lots
├── fx/
│   ├── sbi_ttbr.py       TTBRClient — fetches / caches SBI TTBR (Rule 115)
│   ├── store.py          FxStore — persistent rate cache
│   ├── cache.py          in-memory rate cache
│   └── types.py          ConvertedAmount, RateEntry
├── ingest/
│   ├── base.py           BrokerAdapter protocol, IngestionResult
│   ├── ibkr.py           IBKR Flex Query CSV adapter
│   ├── schwab.py         Schwab trade confirm CSV adapter
│   ├── csv_adapter.py    generic CSV normaliser
│   └── llm_normalizer.py LLM-assisted header mapping for unknown formats
├── models/
│   ├── lot.py            TaxLot
│   ├── instrument.py     Instrument
│   ├── money.py          Money, Paise helpers
│   ├── portfolio.py      Portfolio, Trade
│   ├── provenance.py     Provenance — audit trail per figure
│   ├── tax.py            TaxEvent, TaxSummary
│   └── escalation.py     EscalationCase
├── orchestrator/
│   └── graph.py          LangGraph StateGraph — 7 nodes, wires everything together
├── rag/
│   ├── corpus.py         CorpusChunk dataclass, load_corpus()
│   ├── seed_corpus.jsonl 15 statutory chunks (§2(42A), §112, Rule 115, §70, §74 …)
│   ├── index.py          RagIndex — FAISS with injectable embeddings
│   ├── freshness.py      check_freshness(), FreshnessWarning, LATEST_BUDGET_DATE
│   ├── explainer.py      explain() — LLM explains engine output, no recomputation
│   └── retriever.py      RagRetriever — LCEL chain for open-ended questions
├── report/
│   └── generator.py      ReportGenerator — HTML + JSON output
└── rules/
    ├── loader.py         load_rules_for_date(), ForeignEquityRuleSet
    └── configs/
        ├── fy2324.yaml   FY 2023-24 rules
        ├── fy2425.yaml   FY 2024-25 rules
        └── fy2526.yaml   FY 2025-26 rules (FA2024 rates: 12.5%, 24-month threshold)

evals/
├── golden_scenarios.yaml  44 end-to-end scenarios with expected tax figures
├── test_golden_scenarios.py
├── test_opportunities.py  harvest / crossover / carry-forward evals
└── test_rag.py            33 RAG corpus / index / freshness / explain tests
```

---

## Running tests

```bash
# All evals (77 pass)
.venv/Scripts/python.exe -m pytest evals/ -v --override-ini="addopts="

# Unit tests
.venv/Scripts/python.exe -m pytest tests/ -v --override-ini="addopts="

# Single module
.venv/Scripts/python.exe -m pytest evals/test_rag.py -v --override-ini="addopts="
```

---

## Tax rules covered (FY 2025-26)

| Topic | Provision | Value |
|-------|-----------|-------|
| Holding period threshold | §2(42A), FA2024 | 24 months |
| LTCG rate | §112(1)(c)(iii), FA2024 | 12.5% flat |
| Indexation | §48 second proviso removed | No |
| LTCG exemption | §112 (not §112A) | None |
| STCG rate | §111A inapplicable | Slab rates |
| STCL set-off | §70(2) | STCG then LTCG |
| LTCL set-off | §70(3) | LTCG only |
| Carry-forward | §74 + §80 | 8 years, timely filing required |
| Surcharge | FA2023/FA2025 | Slab; NOT capped at 15% for §112 |
| H&E Cess | FA2018 | 4% |
| FX conversion | Rule 115 | SBI TTBR on acquisition and disposal dates |
| GAAR / wash-sale | §95–102, CBDT Circular 6/2016 | Flagged for CA review |
| Schedule FA disclosure | ITR-2/3 | Flagged |

---

## RAG corpus

The `rag/seed_corpus.jsonl` file ships 15 statutory chunks, each with a `source_url` pointing to the authoritative government source and a `retrieval_date`. The `check_freshness()` function warns if any chunk or the rules config predates `LATEST_BUDGET_DATE = date(2025, 2, 1)` (Union Budget 2025-26).

To update the corpus after a new Budget, add entries to `seed_corpus.jsonl` with a post-Budget `retrieval_date` and update the relevant YAML in `rules/configs/`.

---

## Contributors

**Ashish Basani** — [basaniashish@gmail.com](mailto:basaniashish@gmail.com) · [GitHub @ashishkumar2](https://github.com/ashishkumar2)

Design, architecture, domain modelling, statutory research, and all engineering decisions. See [CONTRIBUTORS.md](CONTRIBUTORS.md) for full details.

---

## Important disclaimer

This software is provided for educational and informational purposes only. It does not constitute tax, legal, or financial advice. All computed figures are estimates based on the statutory rules as understood at the time of writing and must be independently verified by a qualified Chartered Accountant before use in any tax filing. The authors make no warranty, express or implied, as to the accuracy or completeness of the output.
