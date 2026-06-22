# CLAUDE.md — ltcg-agent

## Project purpose

`ltcg-agent` is a capital-gains and tax-loss-harvesting agent for Indian tax residents
holding US equities. It parses broker statements, converts USD amounts to INR using SBI
TTBR rates, applies Indian IT Act rules (LTCG §112A, STCG §111A, grandfathering, etc.),
identifies harvesting opportunities, and emits a Schedule FA / ITR-2 ready report with
LLM-generated plain-English explanations grounded in actual rule text.

## Five non-negotiable design rules

1. **The LLM never does money math.** All tax, gain, and FX arithmetic is deterministic
   Python with unit tests. The model only parses messy input, explains already-computed
   results, and flags reporting obligations. A hallucinated tax figure is worse than no
   tool — never let one reach the user.

2. **Tax rules are versioned data, not code.** Rates, holding-period thresholds, set-off
   rules, surcharge slabs, and exemptions live in `rules/configs/*.yaml`, each field
   carrying `effective_from`, `effective_to`, and a `source` citation. Engine code reads
   the `TaxRuleSet` matching the relevant date; it never hardcodes a number.

3. **Every INR figure is traceable.** No INR amount exists anywhere in the system without
   a trail behind it: USD amount, FX rate, FX rate date, source, and the formula applied.
   Explainability is the trust mechanism, not a nice-to-have. Every `TaxEvent` carries
   `acquisition_fx` and `disposal_fx` of type `FxProvenance`.

4. **This is not tax advice.** All output is an estimate. Every report ends with a
   disclaimer and "verify with a chartered accountant before filing," and the agent
   escalates explicitly on cases it cannot handle confidently (RSU/ESPP, residency-status
   changes, multi-broker duplicate lots, dividend/foreign tax credit questions). These are
   surfaced as `EscalationFlag` objects in `TaxSummary.escalation_flags`.

5. **No comments in code.** Use self-documenting names, types, and tests instead.

## Money representation

All monetary values are integers — **never float**.

- INR amounts: `Money(amount: int, currency: "INR")` — integer **paise** (1 INR = 100 paise)
- USD amounts: `Money(amount: int, currency: "USD")` — integer **cents** (1 USD = 100 cents)

`Money` is signed — negative amounts represent losses or net positions. Arithmetic is
in the integer domain. Rounding (after FX conversion) uses `round()` on the intermediate
float and immediately converts back to `int`.

## Code style

- **No comments anywhere** — names, types, and tests carry all documentation.
- Ruff enforces formatting + import sorting; `ruff check --fix` before every commit.
- `mypy --strict` must pass.

## Python version & dependencies

Python 3.11+ required. Key libraries:

| Library | Purpose |
|---------|---------|
| pydantic v2 | Domain models, settings, serialisation |
| langgraph | Orchestration graph |
| langchain / langchain-openai | LLM calls, RAG chain |
| faiss-cpu | FAISS vector index for IT rule retrieval |
| httpx | SBI TTBR HTTP lookups |
| diskcache | Persistent FX rate cache |
| pyyaml | Versioned tax-rule configs |
| pytest + pytest-asyncio | Test suite |
| ruff | Lint + format |

## Module map

```
ltcg_agent/
  models/
    money.py          Signed integer Money type (paise / cents)
    portfolio.py      Trade, Lot, Portfolio (FIFO lot split)
    tax.py            TaxEvent (with FxProvenance), TaxSummary, HarvestCandidate
    provenance.py     FxProvenance — full FX conversion audit trail
    escalation.py     EscalationFlag, EscalationReason, EscalationSeverity
  ingest/             Broker adapters (one class per source, common interface)
  fx/                 SBI TTBR lookup + diskcache persistence
  engine/
    lot_matcher.py    FIFO matching, partial-lot split
    ltcg.py           TaxEngine — disposal → TaxEvent with FxProvenance
    harvesting.py     HarvestingEngine — unrealised loss candidates
    escalation.py     EscalationDetector — flags complex cases for CA review
  rules/
    loader.py         load_rules("2024-25") → TaxRuleSet; RuleField[T] with citation
    configs/          fy2425.yaml, fy2324.yaml — per-field effective_from + source
  rag/                FAISS index + retrieval over IT Act rule text
  orchestrator/       LangGraph graph wiring all nodes
  report/             XLSX generator — Summary, Tax Events, Schedule FA, Disclaimer
tests/
evals/                Golden scenario YAML fixtures + parametrised tests
data/
  rules/              Bundled IT Act text for RAG ingestion
  raw/                Drop broker statements here for ad-hoc ingestion
```

## Architecture invariants

- `engine/` is **pure Python** — no I/O, no LLM calls, no async. Always testable offline.
- `ingest/` adapters implement `BrokerAdapter` (abstract base in `ingest/base.py`).
- `fx/` is the single source of truth for all USD→INR conversions; never convert inline.
- `rules/` YAML files are the single source of truth. Engine reads `field.value`; reports
  surface `field.source` and `field.effective_from` for auditability.
- The LangGraph graph in `orchestrator/` is the only place nodes are wired together.
- LLM is called only in `rag/retriever.py` (explanations) and `ingest/` (parsing messy
  input). It never touches a number that will appear in a tax computation.

## Tax rules summary (FY 2024–25)

| Category | Rate | Holding | Exemption |
|----------|------|---------|-----------|
| LTCG (foreign equity) | 12.5% | > 24 months | ₹1.25L INR/year |
| STCG | 20% | ≤ 24 months | None |
| Grandfathering | Cost = max(actual, FMV 31 Jan 2018) | pre-2018 lots | LTCG only |

SBI TTBR on the **date of acquisition** → cost basis.
SBI TTBR on the **date of sale** → sale proceeds. (CBDT circular.)

## Escalation cases (always flag, do not compute)

- RSU / ESPP / ISO / NSO identified in trades
- Residency status not confirmed as Resident Indian for full year
- Same ticker, same acquisition date, multiple brokers (duplicate lot risk)
- Dividend income or foreign tax credit (FTC) questions
- Any lot predating 1 April 2000 (pre-indexed cost era)

## Testing conventions

- Test naming: `test_<method>_<scenario>_<expected>`
- Golden scenarios in `evals/` are YAML fixtures; `evals/conftest.py` parameterises them.
- `engine/` tests must run without network access.
- FX tests mock `httpx.AsyncClient`; never hit SBI live in CI.
- `TaxRuleSet` in tests is constructed with `RuleField(value=..., effective_from=..., source="test")`.

## Running

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
mypy ltcg_agent
pytest

ltcg ingest data/raw/schwab_2024.csv --broker schwab
ltcg run --fy 2024-25 --statement data/raw/schwab_2024.csv --broker schwab --report output/report
```

## Environment variables

```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
SBI_TTBR_CACHE_DIR=.cache/ttbr
LOG_LEVEL=INFO
```
