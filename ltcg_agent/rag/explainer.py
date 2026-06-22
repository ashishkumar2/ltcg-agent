from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from ltcg_agent.rag.corpus import CorpusChunk
from ltcg_agent.rag.freshness import FreshnessWarning, check_freshness
from ltcg_agent.rag.index import RagIndex
from ltcg_agent.rules.loader import ForeignEquityRuleSet

_DISCLAIMER = (
    "IMPORTANT — This explanation is for educational purposes only and does not constitute "
    "tax advice. All figures are taken directly from the engine computation and have not "
    "been independently recomputed. Verify with a qualified Chartered Accountant before filing."
)

_EXPLAIN_SYSTEM = (
    "You are a statutory tax explainer for an Indian resident investor's capital gains computation.\n"
    "Your only role is to explain WHY the engine's computed figures are correct by citing the\n"
    "relevant provisions of the Income Tax Act 1961 and associated rules.\n\n"
    "HARD CONSTRAINTS — violating any of these is a critical error:\n"
    "1. All monetary figures in your response MUST be copied verbatim from the engine output\n"
    "   provided in the user message. You MUST NOT recompute, round differently, adjust, or\n"
    "   substitute any figure.\n"
    "2. Every claim about a tax rate, threshold, holding period, or exemption must cite a\n"
    "   specific section (e.g., 'Section 112(1)(c)(iii)') or rule (e.g., 'Rule 115(1)').\n"
    "3. If the retrieved rule text does not address part of the computation, say explicitly:\n"
    "   'The retrieved provisions do not address [X]; a CA should confirm.'\n"
    "4. End your response with exactly this sentence:\n"
    "   'All figures above are taken directly from the engine computation and have not been "
    "independently recomputed.'"
)

_EXPLAIN_HUMAN = (
    "Topic: {topic}\n\n"
    "Engine computation output (DO NOT ALTER ANY FIGURE — reproduce verbatim):\n"
    "{numbers_json}\n\n"
    "Relevant statutory provisions retrieved:\n"
    "{rule_text}\n\n"
    "Explain in plain English what the engine computed for this topic and why each step "
    "follows from the statutory provisions cited above. Every monetary figure must appear "
    "exactly as shown in the engine output."
)


@dataclass(frozen=True)
class Explanation:
    topic: str
    plain_english: str
    cited_chunks: list[CorpusChunk]
    freshness_warning: FreshnessWarning | None
    disclaimer: str


def explain(
    topic: str,
    computed_result: BaseModel,
    index: RagIndex,
    ruleset: ForeignEquityRuleSet,
    llm: BaseChatModel,
    as_of: date | None = None,
) -> Explanation:
    chunks = index.query(topic, k=4)

    corpus_dates = [c.retrieval_date for c in chunks]
    corpus_max = max(corpus_dates) if corpus_dates else ruleset.effective_from
    freshness = check_freshness(corpus_max, ruleset.effective_from, as_of)

    rule_text = _format_chunks(chunks)
    numbers_json = computed_result.model_dump_json(indent=2)

    messages = [
        SystemMessage(content=_EXPLAIN_SYSTEM),
        HumanMessage(
            content=_EXPLAIN_HUMAN.format(
                topic=topic,
                numbers_json=numbers_json,
                rule_text=rule_text,
            )
        ),
    ]
    response = llm.invoke(messages)

    return Explanation(
        topic=topic,
        plain_english=str(response.content),
        cited_chunks=chunks,
        freshness_warning=freshness,
        disclaimer=_DISCLAIMER,
    )


def _format_chunks(chunks: list[CorpusChunk]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(
            f"[{i}] {c.title}\n"
            f"    Section: {c.section}\n"
            f"    Source: {c.source_url} (retrieved {c.retrieval_date})\n"
            f"    Text: {c.text}"
        )
    return "\n\n".join(parts)
