from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, StateGraph

from ltcg_agent.engine.harvesting import HarvestingEngine
from ltcg_agent.engine.ltcg import TaxEngine
from ltcg_agent.fx.sbi_ttbr import TTBRClient
from ltcg_agent.ingest.base import BrokerAdapter, IngestionResult
from ltcg_agent.models.portfolio import Portfolio, TaxLot, Trade
from ltcg_agent.models.tax import TaxEvent, TaxSummary
from ltcg_agent.rag.retriever import RagRetriever
from ltcg_agent.report.generator import ReportGenerator
from ltcg_agent.rules.loader import TaxRuleSet, load_rules


class AgentState(TypedDict):
    financial_year: str
    broker_statement_path: str
    broker: str
    rules: TaxRuleSet | None
    ingestion_result: IngestionResult | None
    portfolio: Portfolio | None
    tax_events: list[TaxEvent]
    summary: TaxSummary | None
    explanation: str
    output_path: str


def _node_load_rules(state: AgentState) -> AgentState:
    rules = load_rules(state["financial_year"])
    return {**state, "rules": rules}


def _node_ingest(state: AgentState, adapters: list[BrokerAdapter]) -> AgentState:
    path = Path(state["broker_statement_path"])
    adapter = next((a for a in adapters if a.supports(path)), None)
    if adapter is None:
        raise ValueError(f"No adapter supports {path}")
    result = adapter.parse(path)
    return {**state, "ingestion_result": result}


def _node_build_lots(state: AgentState, ttbr_client: TTBRClient) -> AgentState:
    ingestion = state["ingestion_result"]
    assert ingestion is not None
    buys = [t for t in ingestion.trades if t.quantity > 0]
    lots: list[TaxLot] = []
    for trade in buys:
        ttbr = ttbr_client.get_ttbr_paise(trade.trade_date)
        lots.append(
            TaxLot(
                ticker=trade.ticker,
                isin=trade.isin,
                acquisition_date=trade.trade_date,
                quantity=trade.quantity,
                cost_per_share_cents=trade.price_cents,
                acquisition_ttbr_paise=ttbr,
                broker=trade.broker,
                account_id=trade.account_id,
                source_trade_id=trade.id,
            )
        )
    return {**state, "portfolio": Portfolio(lots=lots)}


def _node_calculate_tax(state: AgentState, ttbr_client: TTBRClient) -> AgentState:
    rules = state["rules"]
    assert rules is not None
    ingestion = state["ingestion_result"]
    assert ingestion is not None
    portfolio = state["portfolio"]
    assert portfolio is not None

    engine = TaxEngine(rules)
    sells = sorted(
        [t for t in ingestion.trades if t.quantity < 0],
        key=lambda t: t.trade_date,
    )
    sells_normalised = [
        Trade(**{**t.model_dump(), "quantity": abs(t.quantity)})
        for t in sells
    ]

    all_events: list[TaxEvent] = []
    for sale in sells_normalised:
        ttbr = ttbr_client.get_ttbr_paise(sale.trade_date)
        events, portfolio = engine.process_disposal(sale, portfolio, ttbr)
        all_events.extend(events)

    return {**state, "tax_events": all_events, "portfolio": portfolio}


def _node_build_summary(state: AgentState) -> AgentState:
    rules = state["rules"]
    assert rules is not None
    engine = TaxEngine(rules)
    summary = engine.build_summary(
        financial_year=state["financial_year"],
        events=state["tax_events"],
    )
    return {**state, "summary": summary}


def _node_explain(state: AgentState, retriever: RagRetriever) -> AgentState:
    summary = state["summary"]
    assert summary is not None
    question = (
        f"Explain the LTCG and STCG tax treatment for Indian residents on US equity "
        f"disposals for FY {state['financial_year']}. "
        f"Total LTCG: {summary.total_ltcg}, STCG: {summary.total_stcg}."
    )
    answer, _ = retriever.explain(question)
    return {**state, "explanation": answer}


def _node_generate_report(state: AgentState, generator: ReportGenerator) -> AgentState:
    summary = state["summary"]
    assert summary is not None
    out = generator.generate(summary, state["explanation"], Path(state["output_path"]))
    return {**state, "output_path": str(out)}


def build_graph(
    adapters: list[BrokerAdapter],
    ttbr_client: TTBRClient,
    retriever: RagRetriever,
    generator: ReportGenerator,
) -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("load_rules", _node_load_rules)
    graph.add_node("ingest", lambda s: _node_ingest(s, adapters))
    graph.add_node("build_lots", lambda s: _node_build_lots(s, ttbr_client))
    graph.add_node("calculate_tax", lambda s: _node_calculate_tax(s, ttbr_client))
    graph.add_node("build_summary", _node_build_summary)
    graph.add_node("explain", lambda s: _node_explain(s, retriever))
    graph.add_node("generate_report", lambda s: _node_generate_report(s, generator))

    graph.set_entry_point("load_rules")
    graph.add_edge("load_rules", "ingest")
    graph.add_edge("ingest", "build_lots")
    graph.add_edge("build_lots", "calculate_tax")
    graph.add_edge("calculate_tax", "build_summary")
    graph.add_edge("build_summary", "explain")
    graph.add_edge("explain", "generate_report")
    graph.add_edge("generate_report", END)

    return graph
