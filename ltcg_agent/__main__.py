from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ltcg",
        description="LTCG Tax Agent for Indian residents holding US equities",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_p = sub.add_parser("ingest", help="Parse and store a broker statement")
    ingest_p.add_argument("path", type=Path)
    ingest_p.add_argument("--broker", required=True, choices=["schwab", "ibkr"])

    run_p = sub.add_parser("run", help="Run the full tax + harvesting agent")
    run_p.add_argument("--fy", required=True, help="Financial year e.g. 2024-25")
    run_p.add_argument("--statement", type=Path, required=True)
    run_p.add_argument("--broker", required=True, choices=["schwab", "ibkr"])
    run_p.add_argument("--report", type=Path, default=Path("output/report"))

    doctor_p = sub.add_parser(
        "rules-doctor",
        help="Print every tax rule with its source and effective dates for CA review",
    )
    doctor_p.add_argument(
        "--date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Show rules in effect on this date (default: today)",
    )
    doctor_p.add_argument(
        "--asset-class",
        default="us_listed_equity",
        metavar="ASSET_CLASS",
        help="Asset class to look up (default: us_listed_equity)",
    )

    args = parser.parse_args()

    if args.command == "ingest":
        _cmd_ingest(args)
    elif args.command == "run":
        _cmd_run(args)
    elif args.command == "rules-doctor":
        _cmd_rules_doctor(args)


def _cmd_ingest(args: argparse.Namespace) -> None:
    from ltcg_agent.ingest import IBKRAdapter, SchwabAdapter

    adapters = {"schwab": SchwabAdapter(), "ibkr": IBKRAdapter()}
    adapter = adapters[args.broker]
    result = adapter.parse(args.path)
    print(f"Parsed {len(result.trades)} trades from {args.path}")
    for w in result.parse_warnings:
        print(f"  WARNING: {w}", file=sys.stderr)


def _cmd_run(args: argparse.Namespace) -> None:
    import os

    from ltcg_agent.fx.sbi_ttbr import TTBRClient
    from ltcg_agent.fx.store import RateStore
    from ltcg_agent.ingest import IBKRAdapter, SchwabAdapter
    from ltcg_agent.orchestrator.graph import AgentState, build_graph
    from ltcg_agent.rag.index import RagIndex
    from ltcg_agent.rag.retriever import RagRetriever
    from ltcg_agent.report.generator import ReportGenerator

    embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o")
    cache_dir = Path(os.getenv("SBI_TTBR_CACHE_DIR", ".cache/ttbr"))
    index_path = Path(".cache/rag_index")

    rag_index = RagIndex(index_path, embedding_model)
    if index_path.exists():
        rag_index.load()
    else:
        rag_index.build(Path("data/rules"))

    adapters = [SchwabAdapter(), IBKRAdapter()]
    ttbr = TTBRClient(store=RateStore(cache_dir / "rates.csv"))

    graph = build_graph(
        adapters=adapters,
        ttbr_client=ttbr,
        retriever=RagRetriever(rag_index, openai_model),
        generator=ReportGenerator(),
    )
    compiled = graph.compile()
    initial_state: AgentState = {
        "financial_year": args.fy,
        "broker_statement_path": str(args.statement),
        "broker": args.broker,
        "rules": None,
        "ingestion_result": None,
        "portfolio": None,
        "tax_events": [],
        "summary": None,
        "explanation": "",
        "output_path": str(args.report),
    }
    final = compiled.invoke(initial_state)
    print(f"Report written to: {final['output_path']}")


def _cmd_rules_doctor(args: argparse.Namespace) -> None:
    from decimal import Decimal

    from rich.console import Console
    from rich.table import Table

    from ltcg_agent.rules.loader import ForeignEquityRuleSet, RuleField, load_rules_for_date

    lookup_date = date.fromisoformat(args.date) if args.date else date.today()
    try:
        ruleset = load_rules_for_date(lookup_date, asset_class=args.asset_class)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    console = Console()
    console.print()
    console.print(
        f"[bold cyan]Rules Doctor[/bold cyan]  "
        f"FY [yellow]{ruleset.financial_year}[/yellow]  "
        f"asset_class=[yellow]{ruleset.asset_class}[/yellow]  "
        f"effective {ruleset.effective_from} → {ruleset.effective_to}"
    )
    console.print(
        "[dim]Verify every source citation with a qualified chartered accountant "
        "before filing. This output is not tax advice.[/dim]"
    )
    console.print()

    table = Table(
        show_header=True,
        header_style="bold",
        show_lines=True,
        expand=True,
    )
    table.add_column("Field", style="yellow", no_wrap=True, min_width=28)
    table.add_column("Value", style="green", no_wrap=True, min_width=16)
    table.add_column("From", style="dim", no_wrap=True, min_width=12)
    table.add_column("To", style="dim", no_wrap=True, min_width=12)
    table.add_column("Source", overflow="fold")

    def _to_str(v: date | None) -> str:
        return str(v) if v else "(open)"

    def _add(field_name: str, field: RuleField) -> None:  # type: ignore[type-arg]
        table.add_row(
            field_name,
            str(field.value),
            str(field.effective_from),
            _to_str(field.effective_to),
            field.source,
        )

    _add("asset_classification", ruleset.asset_classification)
    _add("long_term_threshold_months", ruleset.long_term_threshold_months)
    _add("ltcg.section", ruleset.ltcg.section)
    _add("ltcg.rate_pct (%)", ruleset.ltcg.rate_pct)
    _add("ltcg.indexation", ruleset.ltcg.indexation)
    _add("ltcg.exemption_inr (₹)", ruleset.ltcg.exemption_inr)
    _add("stcg.taxed_at", ruleset.stcg.taxed_at)
    _add("stcg.section_111a_applies", ruleset.stcg.section_111a_applies)
    _add("setoff.stcl_offsets", ruleset.setoff.stcl_offsets)
    _add("setoff.ltcl_offsets", ruleset.setoff.ltcl_offsets)
    _add("setoff.carry_forward_years", ruleset.setoff.carry_forward_years)
    _add("cess_pct (%)", ruleset.cess_pct)
    _add("wash_sale_rule", ruleset.wash_sale_rule)

    slabs = ruleset.surcharge_slabs
    for i, slab in enumerate(slabs.value):
        above = f"₹{slab.income_above_inr:,}"
        upto = f"₹{slab.income_upto_inr:,}" if slab.income_upto_inr is not None else "unlimited"
        slab_str = f"{above} – {upto}: {slab.rate_pct}%"
        if i == 0:
            table.add_row(
                "surcharge_slabs",
                slab_str,
                str(slabs.effective_from),
                _to_str(slabs.effective_to),
                slabs.source,
            )
        else:
            table.add_row("", slab_str, "", "", "")

    console.print(table)
    console.print()


if __name__ == "__main__":
    main()
