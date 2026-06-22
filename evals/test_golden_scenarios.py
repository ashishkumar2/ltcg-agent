from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ltcg_agent.engine.gains import (
    FyAggregates,
    aggregate_for_fy,
    apply_setoff,
    classify_term,
    estimate_tax,
    realized_gain,
)
from ltcg_agent.fx.types import RateEntry
from ltcg_agent.models.money import Currency, Money
from ltcg_agent.models.portfolio import TaxLot, Trade
from ltcg_agent.rules.loader import load_rules_for_date


def test_golden_scenario(scenario: dict) -> None:
    ruleset_date = date.fromisoformat(scenario["ruleset_date"])
    ruleset = load_rules_for_date(ruleset_date)
    expected = scenario["expected"]
    tax_cfg = scenario["tax"]

    if scenario["type"] == "single_trade":
        _run_single_trade(scenario, ruleset, expected, tax_cfg)
    elif scenario["type"] == "setoff_only":
        _run_setoff_only(scenario, ruleset, expected, tax_cfg)
    else:
        raise ValueError(f"Unknown scenario type: {scenario['type']}")


def _run_single_trade(scenario: dict, ruleset, expected: dict, tax_cfg: dict) -> None:
    raw_lot = scenario["lot"]
    lot = TaxLot(
        ticker=raw_lot["ticker"],
        acquisition_date=date.fromisoformat(raw_lot["acquisition_date"]),
        quantity=raw_lot["quantity"],
        cost_per_share_cents=Money(amount=raw_lot["cost_per_share_cents"], currency=Currency.USD),
        acquisition_ttbr_paise=raw_lot["acquisition_ttbr_paise"],
        broker="test",
        account_id="test",
    )

    raw_sale = scenario["sale"]
    sale = Trade(
        ticker=raw_sale["ticker"],
        trade_date=date.fromisoformat(raw_sale["sale_date"]),
        quantity=raw_sale["quantity"],
        price_cents=Money(amount=raw_sale["price_cents"], currency=Currency.USD),
        commission_cents=Money(amount=raw_sale.get("commission_cents", 0), currency=Currency.USD),
        broker="test",
        account_id="test",
    )

    raw_fx = scenario["disposal_fx"]
    disposal_fx = RateEntry(
        rate_date=date.fromisoformat(raw_fx["rate_date"]),
        ttbr_paise_per_usd=raw_fx["ttbr_paise_per_usd"],
        source=raw_fx["source"],
    )

    term = classify_term(lot.acquisition_date, sale.trade_date, ruleset)
    assert (sale.trade_date - lot.acquisition_date).days == expected["holding_days"], (
        f"holding_days mismatch: got {(sale.trade_date - lot.acquisition_date).days}"
    )
    assert term == expected["term"]

    gain = realized_gain(lot, sale, disposal_fx, ruleset)
    assert gain.holding_days == expected["holding_days"]
    assert gain.term == expected["term"]
    assert gain.gain_inr_paise == expected["gain_inr_paise"]
    assert gain.acquisition_fx.inr_paise > 0
    assert gain.disposal_fx.source == raw_fx["source"]

    agg = aggregate_for_fy([gain], ruleset)
    assert agg.stcg_paise == expected["stcg_paise"]
    assert agg.ltcg_paise == expected["ltcg_paise"]
    assert agg.stcl_paise == expected["stcl_paise"]
    assert agg.ltcl_paise == expected["ltcl_paise"]

    setoff = apply_setoff(agg, ruleset)
    assert setoff.net_stcg_paise == expected["net_stcg_paise"]
    assert setoff.net_ltcg_paise == expected["net_ltcg_paise"]
    assert setoff.carry_forward_stcl_paise == expected["carry_forward_stcl_paise"]
    assert setoff.carry_forward_ltcl_paise == expected["carry_forward_ltcl_paise"]

    tax = estimate_tax(
        net_ltcg_paise=setoff.net_ltcg_paise,
        net_stcg_paise=setoff.net_stcg_paise,
        stcg_marginal_rate_pct=Decimal(tax_cfg["stcg_marginal_rate_pct"]),
        taxable_income_inr=tax_cfg["taxable_income_inr"],
        regime=tax_cfg["regime"],
        ruleset=ruleset,
    )
    assert tax.ltcg_tax_paise == expected["ltcg_tax_paise"]
    assert tax.stcg_tax_paise == expected["stcg_tax_paise"]
    assert tax.surcharge_paise == expected["surcharge_paise"]
    assert tax.cess_paise == expected["cess_paise"]
    assert tax.total_tax_paise == expected["total_tax_paise"]


def _run_setoff_only(scenario: dict, ruleset, expected: dict, tax_cfg: dict) -> None:
    raw_agg = scenario["aggregates"]
    agg = FyAggregates(
        stcg_paise=raw_agg["stcg_paise"],
        ltcg_paise=raw_agg["ltcg_paise"],
        stcl_paise=raw_agg["stcl_paise"],
        ltcl_paise=raw_agg["ltcl_paise"],
    )

    setoff = apply_setoff(agg, ruleset)
    assert setoff.net_stcg_paise == expected["net_stcg_paise"]
    assert setoff.net_ltcg_paise == expected["net_ltcg_paise"]
    assert setoff.carry_forward_stcl_paise == expected["carry_forward_stcl_paise"]
    assert setoff.carry_forward_ltcl_paise == expected["carry_forward_ltcl_paise"]

    tax = estimate_tax(
        net_ltcg_paise=setoff.net_ltcg_paise,
        net_stcg_paise=setoff.net_stcg_paise,
        stcg_marginal_rate_pct=Decimal(tax_cfg["stcg_marginal_rate_pct"]),
        taxable_income_inr=tax_cfg["taxable_income_inr"],
        regime=tax_cfg["regime"],
        ruleset=ruleset,
    )
    assert tax.ltcg_tax_paise == expected["ltcg_tax_paise"]
    assert tax.stcg_tax_paise == expected["stcg_tax_paise"]
    assert tax.surcharge_paise == expected["surcharge_paise"]
    assert tax.cess_paise == expected["cess_paise"]
    assert tax.total_tax_paise == expected["total_tax_paise"]
