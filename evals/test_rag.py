from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from ltcg_agent.engine.gains import (
    FyAggregates,
    SetoffResult,
    TaxEstimate,
    RealizedGain,
)
from ltcg_agent.fx.types import ConvertedAmount
from langchain_core.embeddings import Embeddings

from ltcg_agent.rag.corpus import CorpusChunk, load_corpus
from ltcg_agent.rag.explainer import Explanation, _format_chunks, explain
from ltcg_agent.rag.freshness import (
    LATEST_BUDGET_DATE,
    FreshnessWarning,
    check_freshness,
)
from ltcg_agent.rag.index import RagIndex
from ltcg_agent.rules.loader import load_rules_for_date


_RULESET_DATE = date(2025, 10, 1)


class _FakeEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * 16
        for i, ch in enumerate(text[:16]):
            v[i] = float(ord(ch)) / 128.0
        return v


class _FakeLLM:
    def __init__(self, response: str) -> None:
        self._response = response

    def invoke(self, messages: Any) -> Any:
        class _Msg:
            content: str

        m = _Msg()
        m.content = self._response
        return m


@pytest.fixture(scope="module")
def corpus() -> list[CorpusChunk]:
    return load_corpus()


@pytest.fixture(scope="module")
def index(corpus: list[CorpusChunk]) -> RagIndex:
    return RagIndex.build(corpus, _FakeEmbeddings())


@pytest.fixture(scope="module")
def ruleset():
    return load_rules_for_date(_RULESET_DATE)


class TestLoadCorpus:
    def test_returns_15_chunks(self, corpus: list[CorpusChunk]) -> None:
        assert len(corpus) == 15

    def test_all_chunk_ids_unique(self, corpus: list[CorpusChunk]) -> None:
        ids = [c.chunk_id for c in corpus]
        assert len(ids) == len(set(ids))

    def test_all_retrieval_dates_valid(self, corpus: list[CorpusChunk]) -> None:
        for chunk in corpus:
            assert isinstance(chunk.retrieval_date, date)
            assert chunk.retrieval_date >= date(2024, 1, 1)

    def test_all_source_urls_present(self, corpus: list[CorpusChunk]) -> None:
        for chunk in corpus:
            assert chunk.source_url.startswith("https://"), chunk.chunk_id

    def test_all_sections_present(self, corpus: list[CorpusChunk]) -> None:
        for chunk in corpus:
            assert len(chunk.section) > 5, chunk.chunk_id

    def test_expected_chunk_ids_present(self, corpus: list[CorpusChunk]) -> None:
        ids = {c.chunk_id for c in corpus}
        required = {
            "sec_2_42a_holding_period",
            "rule_115_ttbr_conversion",
            "sec_112_ltcg_rate_fa2024",
            "sec70_2_stcl_setoff",
            "sec70_3_ltcl_setoff",
            "sec74_80_carry_forward",
            "surcharge_slabs_fy2526",
            "health_education_cess",
            "gaar_wash_sale_risk",
            "schedule_fa_disclosure",
        }
        assert required <= ids

    def test_all_texts_nonempty(self, corpus: list[CorpusChunk]) -> None:
        for chunk in corpus:
            assert len(chunk.text) > 100, chunk.chunk_id


class TestRagIndex:
    def test_query_returns_k_chunks(self, index: RagIndex, corpus: list[CorpusChunk]) -> None:
        results = index.query("LTCG rate on foreign equity", k=4)
        assert len(results) == 4

    def test_query_results_are_corpus_chunks(
        self, index: RagIndex, corpus: list[CorpusChunk]
    ) -> None:
        results = index.query("holding period long-term", k=3)
        all_ids = {c.chunk_id for c in corpus}
        for r in results:
            assert r.chunk_id in all_ids

    def test_query_k1_returns_one(self, index: RagIndex) -> None:
        results = index.query("surcharge cess", k=1)
        assert len(results) == 1

    def test_store_property_available(self, index: RagIndex) -> None:
        store = index.store
        assert store is not None

    def test_build_from_subset(self) -> None:
        corpus = load_corpus()[:5]
        idx = RagIndex.build(corpus, _FakeEmbeddings())
        results = idx.query("capital gains", k=3)
        assert len(results) == 3
        valid_ids = {c.chunk_id for c in corpus}
        for r in results:
            assert r.chunk_id in valid_ids


class TestCheckFreshness:
    def test_fresh_corpus_and_rules_returns_none(self) -> None:
        result = check_freshness(
            corpus_max_date=date(2025, 7, 15),
            rules_effective_from=date(2025, 4, 1),
        )
        assert result is None

    def test_stale_corpus_returns_warning(self) -> None:
        result = check_freshness(
            corpus_max_date=date(2024, 11, 1),
            rules_effective_from=date(2025, 4, 1),
        )
        assert isinstance(result, FreshnessWarning)
        assert "corpus last indexed 2024-11-01" in result.message
        assert "Budget 2025-26" in result.message

    def test_stale_rules_returns_warning(self) -> None:
        result = check_freshness(
            corpus_max_date=date(2025, 7, 15),
            rules_effective_from=date(2024, 4, 1),
        )
        assert isinstance(result, FreshnessWarning)
        assert "rules config" in result.message

    def test_both_stale_mentions_both(self) -> None:
        result = check_freshness(
            corpus_max_date=date(2024, 6, 1),
            rules_effective_from=date(2024, 4, 1),
        )
        assert result is not None
        assert "corpus" in result.message
        assert "rules config" in result.message

    def test_freshness_warning_fields(self) -> None:
        result = check_freshness(
            corpus_max_date=date(2024, 8, 1),
            rules_effective_from=date(2024, 4, 1),
        )
        assert result is not None
        assert result.latest_budget_date == LATEST_BUDGET_DATE
        assert result.corpus_max_date == date(2024, 8, 1)
        assert result.rules_effective_from == date(2024, 4, 1)

    def test_message_contains_ca_advice(self) -> None:
        result = check_freshness(
            corpus_max_date=date(2024, 1, 1),
            rules_effective_from=date(2024, 1, 1),
        )
        assert result is not None
        assert "Chartered Accountant" in result.message

    def test_corpus_exactly_on_budget_date_not_stale(self) -> None:
        result = check_freshness(
            corpus_max_date=LATEST_BUDGET_DATE,
            rules_effective_from=LATEST_BUDGET_DATE,
        )
        assert result is None


class TestExplain:
    def _make_tax_estimate(self) -> TaxEstimate:
        return TaxEstimate(
            ltcg_tax_paise=575_000,
            stcg_tax_paise=0,
            surcharge_paise=0,
            cess_paise=23_000,
            total_tax_paise=598_000,
            effective_rate_bps=1300,
            regime="old",
        )

    def _make_setoff_result(self) -> SetoffResult:
        return SetoffResult(
            net_stcg_paise=2_000_000,
            net_ltcg_paise=5_000_000,
            carry_forward_stcl_paise=0,
            carry_forward_ltcl_paise=500_000,
        )

    def test_explain_returns_explanation(
        self, index: RagIndex, ruleset: Any
    ) -> None:
        result = self._make_tax_estimate()
        fake_response = (
            "The engine computed LTCG tax of 575000 paise under Section 112. "
            "All figures above are taken directly from the engine computation and "
            "have not been independently recomputed."
        )
        exp = explain(
            topic="ltcg_rate",
            computed_result=result,
            index=index,
            ruleset=ruleset,
            llm=_FakeLLM(fake_response),
        )
        assert isinstance(exp, Explanation)
        assert exp.topic == "ltcg_rate"

    def test_explain_plain_english_is_llm_response(
        self, index: RagIndex, ruleset: Any
    ) -> None:
        result = self._make_tax_estimate()
        fake_response = "Engine computed 575000 paise LTCG tax at 12.5% per Section 112."
        exp = explain(
            topic="ltcg_rate",
            computed_result=result,
            index=index,
            ruleset=ruleset,
            llm=_FakeLLM(fake_response),
        )
        assert exp.plain_english == fake_response

    def test_explain_cited_chunks_nonempty(
        self, index: RagIndex, ruleset: Any
    ) -> None:
        result = self._make_tax_estimate()
        exp = explain(
            topic="ltcg_rate",
            computed_result=result,
            index=index,
            ruleset=ruleset,
            llm=_FakeLLM("explanation text"),
        )
        assert len(exp.cited_chunks) > 0

    def test_explain_cited_chunks_are_corpus_chunks(
        self, index: RagIndex, ruleset: Any, corpus: list[CorpusChunk]
    ) -> None:
        result = self._make_setoff_result()
        exp = explain(
            topic="setoff",
            computed_result=result,
            index=index,
            ruleset=ruleset,
            llm=_FakeLLM("setoff explanation"),
        )
        valid_ids = {c.chunk_id for c in corpus}
        for chunk in exp.cited_chunks:
            assert chunk.chunk_id in valid_ids

    def test_explain_no_freshness_warning_for_fresh_corpus(
        self, index: RagIndex, ruleset: Any
    ) -> None:
        result = self._make_tax_estimate()
        exp = explain(
            topic="ltcg_rate",
            computed_result=result,
            index=index,
            ruleset=ruleset,
            llm=_FakeLLM("explanation"),
            as_of=date(2025, 10, 1),
        )
        assert exp.freshness_warning is None

    def test_explain_freshness_warning_for_stale_index(
        self, ruleset: Any
    ) -> None:
        stale_chunk = CorpusChunk(
            chunk_id="stale_chunk",
            title="Old rule",
            section="Section X",
            source_url="https://example.com",
            retrieval_date=date(2024, 6, 1),
            text="Some old rule text about capital gains taxation.",
        )
        stale_index = RagIndex.build([stale_chunk], _FakeEmbeddings())
        result = self._make_tax_estimate()
        exp = explain(
            topic="ltcg_rate",
            computed_result=result,
            index=stale_index,
            ruleset=ruleset,
            llm=_FakeLLM("stale explanation"),
        )
        assert exp.freshness_warning is not None
        assert "FRESHNESS WARNING" in exp.freshness_warning.message

    def test_explain_disclaimer_contains_ca(
        self, index: RagIndex, ruleset: Any
    ) -> None:
        result = self._make_tax_estimate()
        exp = explain(
            topic="surcharge",
            computed_result=result,
            index=index,
            ruleset=ruleset,
            llm=_FakeLLM("surcharge explanation"),
        )
        assert "Chartered Accountant" in exp.disclaimer

    def test_explain_disclaimer_says_not_independently_recomputed(
        self, index: RagIndex, ruleset: Any
    ) -> None:
        result = self._make_tax_estimate()
        exp = explain(
            topic="cess",
            computed_result=result,
            index=index,
            ruleset=ruleset,
            llm=_FakeLLM("cess explanation"),
        )
        assert "not been independently recomputed" in exp.disclaimer

    def test_explain_works_for_fy_aggregates(
        self, index: RagIndex, ruleset: Any
    ) -> None:
        result = FyAggregates(
            stcg_paise=3_000_000,
            ltcg_paise=8_000_000,
            stcl_paise=0,
            ltcl_paise=500_000,
        )
        exp = explain(
            topic="aggregate_for_fy",
            computed_result=result,
            index=index,
            ruleset=ruleset,
            llm=_FakeLLM("FY aggregate explanation"),
        )
        assert exp.topic == "aggregate_for_fy"
        assert len(exp.cited_chunks) > 0


class TestFormatChunks:
    def test_format_includes_title(self) -> None:
        chunk = CorpusChunk(
            chunk_id="test_chunk",
            title="Test Title",
            section="Section 112",
            source_url="https://example.com",
            retrieval_date=date(2025, 7, 15),
            text="Some statutory text.",
        )
        formatted = _format_chunks([chunk])
        assert "Test Title" in formatted

    def test_format_includes_source_url(self) -> None:
        chunk = CorpusChunk(
            chunk_id="test_chunk",
            title="Title",
            section="Section 112",
            source_url="https://incometaxindia.gov.in/example",
            retrieval_date=date(2025, 7, 15),
            text="Text.",
        )
        formatted = _format_chunks([chunk])
        assert "https://incometaxindia.gov.in/example" in formatted

    def test_format_includes_retrieval_date(self) -> None:
        chunk = CorpusChunk(
            chunk_id="test_chunk",
            title="Title",
            section="Section 112",
            source_url="https://example.com",
            retrieval_date=date(2025, 7, 15),
            text="Text.",
        )
        formatted = _format_chunks([chunk])
        assert "2025-07-15" in formatted

    def test_format_multiple_chunks_numbered(self) -> None:
        chunks = [
            CorpusChunk(
                chunk_id=f"chunk_{i}",
                title=f"Title {i}",
                section=f"Section {i}",
                source_url="https://example.com",
                retrieval_date=date(2025, 7, 15),
                text=f"Text {i}.",
            )
            for i in range(3)
        ]
        formatted = _format_chunks(chunks)
        assert "[1]" in formatted
        assert "[2]" in formatted
        assert "[3]" in formatted

    def test_format_empty_list(self) -> None:
        formatted = _format_chunks([])
        assert formatted == ""
