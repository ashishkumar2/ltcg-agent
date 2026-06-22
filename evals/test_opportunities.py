from __future__ import annotations

# Hand-computed golden tests for engine/opportunities.py
# Every expected value below is derived from first principles with the math shown.

from datetime import date
from decimal import Decimal

import pytest

from ltcg_agent.engine.gains import FyAggregates, SetoffResult, apply_setoff
from ltcg_agent.engine.opportunities import (
    CarryForwardNote,
    HarvestOpportunity,
    CrossoverOpportunity,
    build_opportunity_report,
    find_carry_forward,
    find_crossover_opportunities,
    find_harvest_opportunities,
)
from ltcg_agent.fx.types import RateEntry
from ltcg_agent.models.money import Currency, Money
from ltcg_agent.models.portfolio import TaxLot
from ltcg_agent.rules.loader import load_rules_for_date


def _ruleset(d: date = date(2025, 9, 15)):
    return load_rules_for_date(d)


def _lot(ticker, quantity, acquisition_date, cost_per_share_cents, acquisition_ttbr_paise):
    return TaxLot(
        ticker=ticker,
        acquisition_date=acquisition_date,
        quantity=quantity,
        cost_per_share_cents=Money(amount=cost_per_share_cents, currency=Currency.USD),
        acquisition_ttbr_paise=acquisition_ttbr_paise,
        broker="test",
        account_id="acc1",
    )


def _fx_rate(paise, d):
    return RateEntry(rate_date=d, ttbr_paise_per_usd=paise, source="test_source")


class _FixedPriceSource:
    def __init__(self, prices, fx):
        self._prices = prices
        self._fx = fx

    def current_price_cents(self, ticker):
        return self._prices[ticker]

    def current_fx(self):
        return self._fx


# Scenario A: harvest_stcg_offset
#
# Lot: 10 AAPL bought 2025-09-01 at $100 (10000 cents), TTBR 8400 paise
# as_of: 2026-01-15; holding_days = 30+31+30+31+14 = 136 days < 720 -> SHORT
#
# cost_basis_inr = round(100000 * 8400 / 100)  = 8_400_000 paise
# current_value  = round(85000 * 8600 / 100)   = 7_310_000 paise
#   (85000 = 8500 cents/share x 10 shares)
# unrealized_loss = 8_400_000 - 7_310_000       = 1_090_000 paise
#
# FY aggregates: STCG = 2_000_000, LTCG = 0
# stcg_offset = min(1_090_000, 2_000_000) = 1_090_000; ltcg_offset = 0; carry = 0
#
# Tax saved (income Rs 80L = 8_000_000 INR -> surcharge 10%, cess 4%):
#   stcg_base = round(1_090_000 x 30/100) = 327_000
#   stcg_sur  = round(327_000 x 10/100)   = 32_700
#   stcg_cess = round(359_700 x 4/100)    = 14_388
#   tax_saved = 374_088

_AS_OF_HARVEST = date(2026, 1, 15)
_HARVEST_LOT = _lot("AAPL", 10, date(2025, 9, 1), 10000, 8400)
_HARVEST_PRICES = _FixedPriceSource({"AAPL": 8500}, _fx_rate(8600, _AS_OF_HARVEST))
_HARVEST_AGG = FyAggregates(stcg_paise=2_000_000, ltcg_paise=0, stcl_paise=0, ltcl_paise=0)


def test_harvest_lot_identified_as_opportunity():
    ops = find_harvest_opportunities(
        [_HARVEST_LOT], _HARVEST_AGG, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert len(ops) == 1


def test_harvest_term_is_short():
    ops = find_harvest_opportunities(
        [_HARVEST_LOT], _HARVEST_AGG, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert ops[0].term == "short"


def test_harvest_holding_days():
    ops = find_harvest_opportunities(
        [_HARVEST_LOT], _HARVEST_AGG, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert ops[0].holding_days == 136


def test_harvest_cost_basis():
    ops = find_harvest_opportunities(
        [_HARVEST_LOT], _HARVEST_AGG, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert ops[0].cost_basis_inr_paise == 8_400_000


def test_harvest_current_value():
    ops = find_harvest_opportunities(
        [_HARVEST_LOT], _HARVEST_AGG, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert ops[0].current_value_inr_paise == 7_310_000


def test_harvest_unrealized_loss():
    ops = find_harvest_opportunities(
        [_HARVEST_LOT], _HARVEST_AGG, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert ops[0].unrealized_loss_inr_paise == 1_090_000


def test_harvest_stcg_offset():
    ops = find_harvest_opportunities(
        [_HARVEST_LOT], _HARVEST_AGG, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert ops[0].stcg_offset_paise == 1_090_000


def test_harvest_ltcg_offset_zero():
    ops = find_harvest_opportunities(
        [_HARVEST_LOT], _HARVEST_AGG, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert ops[0].ltcg_offset_paise == 0


def test_harvest_carry_forward_zero():
    ops = find_harvest_opportunities(
        [_HARVEST_LOT], _HARVEST_AGG, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert ops[0].carry_forward_stcl_paise == 0


def test_harvest_tax_saved():
    ops = find_harvest_opportunities(
        [_HARVEST_LOT], _HARVEST_AGG, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert ops[0].tax_saved_paise == 374_088


def test_harvest_fx_trail():
    ops = find_harvest_opportunities(
        [_HARVEST_LOT], _HARVEST_AGG, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert ops[0].current_fx.source == "test_source"
    assert ops[0].current_fx.rate == 8600
    assert ops[0].current_fx.inr_paise == 7_310_000


def test_harvest_profit_lot_excluded():
    prices = _FixedPriceSource({"AAPL": 12000}, _fx_rate(8600, _AS_OF_HARVEST))
    ops = find_harvest_opportunities(
        [_HARVEST_LOT], _HARVEST_AGG, _AS_OF_HARVEST,
        prices, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert ops == []


def test_harvest_ranked_by_tax_saved_desc():
    lot1 = _lot("AAPL", 10, date(2025, 9, 1), 10000, 8400)
    lot2 = _lot("NVDA", 5, date(2025, 10, 1), 20000, 8500)
    # NVDA: cost=round(20000*5*8500/100)=8_500_000; current=round(85000*8600/100)=7_310_000 -> loss=1_190_000
    prices = _FixedPriceSource(
        {"AAPL": 8500, "NVDA": 17000},
        _fx_rate(8600, _AS_OF_HARVEST),
    )
    agg = FyAggregates(stcg_paise=5_000_000, ltcg_paise=0)
    ops = find_harvest_opportunities(
        [lot1, lot2], agg, _AS_OF_HARVEST, prices, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert len(ops) == 2
    assert ops[0].tax_saved_paise >= ops[1].tax_saved_paise


def test_harvest_loss_exceeds_gains_produces_carry_forward():
    agg = FyAggregates(stcg_paise=500_000, ltcg_paise=0)
    ops = find_harvest_opportunities(
        [_HARVEST_LOT], agg, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert ops[0].stcg_offset_paise == 500_000
    assert ops[0].carry_forward_stcl_paise == 590_000


def test_harvest_stcl_also_offsets_ltcg():
    agg = FyAggregates(stcg_paise=300_000, ltcg_paise=500_000)
    ops = find_harvest_opportunities(
        [_HARVEST_LOT], agg, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_HARVEST),
    )
    assert ops[0].stcg_offset_paise == 300_000
    assert ops[0].ltcg_offset_paise == 500_000
    assert ops[0].carry_forward_stcl_paise == 290_000


# Scenario B: crossover_ltcg_saves
#
# Lot: 20 NVDA bought 2024-02-15 at $150 (15000 cents), TTBR 8300 paise
# as_of: 2026-01-15; holding_days = 366 + 334 = 700 days < 720 -> SHORT
# crossover_date = date(2024,2,15) + timedelta(721) = date(2026,2,5)
# days_to_crossover = 21  (within 60-day window)
#
# cost_basis = round(300_000 * 8300 / 100)  = 24_900_000
# current    = round(400_000 * 8600 / 100)  = 34_400_000
# gain       = 9_500_000
#
# STCG today: base=2_850_000 sur=285_000 cess=125_400 total=3_260_400
# LTCG cross: base=1_187_500 sur=118_750 cess=52_250  total=1_358_500
# saving = 1_901_900

_AS_OF_CROSS = date(2026, 1, 15)
_CROSS_LOT = _lot("NVDA", 20, date(2024, 2, 15), 15000, 8300)
_CROSS_PRICES = _FixedPriceSource({"NVDA": 20000}, _fx_rate(8600, _AS_OF_CROSS))


def test_crossover_lot_in_window():
    ops = find_crossover_opportunities(
        [_CROSS_LOT], _AS_OF_CROSS, _CROSS_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_CROSS),
    )
    assert len(ops) == 1


def test_crossover_holding_days():
    ops = find_crossover_opportunities(
        [_CROSS_LOT], _AS_OF_CROSS, _CROSS_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_CROSS),
    )
    assert ops[0].holding_days == 700


def test_crossover_crossover_date():
    from datetime import timedelta
    expected = date(2024, 2, 15) + timedelta(days=721)
    ops = find_crossover_opportunities(
        [_CROSS_LOT], _AS_OF_CROSS, _CROSS_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_CROSS),
    )
    assert ops[0].crossover_date == expected


def test_crossover_days_to_crossover():
    ops = find_crossover_opportunities(
        [_CROSS_LOT], _AS_OF_CROSS, _CROSS_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_CROSS),
    )
    assert ops[0].days_to_crossover == 21


def test_crossover_cost_basis():
    ops = find_crossover_opportunities(
        [_CROSS_LOT], _AS_OF_CROSS, _CROSS_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_CROSS),
    )
    assert ops[0].cost_basis_inr_paise == 24_900_000


def test_crossover_current_value():
    ops = find_crossover_opportunities(
        [_CROSS_LOT], _AS_OF_CROSS, _CROSS_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_CROSS),
    )
    assert ops[0].current_value_inr_paise == 34_400_000


def test_crossover_unrealized_gain():
    ops = find_crossover_opportunities(
        [_CROSS_LOT], _AS_OF_CROSS, _CROSS_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_CROSS),
    )
    assert ops[0].unrealized_gain_inr_paise == 9_500_000


def test_crossover_stcg_tax_today():
    ops = find_crossover_opportunities(
        [_CROSS_LOT], _AS_OF_CROSS, _CROSS_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_CROSS),
    )
    assert ops[0].stcg_tax_today_paise == 3_260_400


def test_crossover_ltcg_tax():
    ops = find_crossover_opportunities(
        [_CROSS_LOT], _AS_OF_CROSS, _CROSS_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_CROSS),
    )
    assert ops[0].ltcg_tax_at_crossover_paise == 1_358_500


def test_crossover_tax_saving():
    ops = find_crossover_opportunities(
        [_CROSS_LOT], _AS_OF_CROSS, _CROSS_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_CROSS),
    )
    assert ops[0].tax_saving_paise == 1_901_900


def test_crossover_fx_trail():
    ops = find_crossover_opportunities(
        [_CROSS_LOT], _AS_OF_CROSS, _CROSS_PRICES, Decimal("30"), 8_000_000, _ruleset(_AS_OF_CROSS),
    )
    assert ops[0].current_fx.rate == 8600
    assert ops[0].current_fx.inr_paise == 34_400_000
    assert ops[0].current_fx.source == "test_source"


def test_crossover_already_long_term_excluded():
    # 2024-02-15 + 726 days = within FY2526 and already long-term (> 720 days)
    as_of = date(2026, 2, 10)
    lot = _lot("NVDA", 20, date(2024, 2, 15), 15000, 8300)
    prices = _FixedPriceSource({"NVDA": 20000}, _fx_rate(8700, as_of))
    ops = find_crossover_opportunities([lot], as_of, prices, Decimal("30"), 8_000_000, _ruleset(as_of))
    assert ops == []


def test_crossover_outside_window_excluded():
    lot = _lot("MSFT", 10, date(2025, 1, 15), 10000, 8400)
    prices = _FixedPriceSource({"MSFT": 15000}, _fx_rate(8600, _AS_OF_CROSS))
    ops = find_crossover_opportunities([lot], _AS_OF_CROSS, prices, Decimal("30"), 8_000_000, _ruleset(_AS_OF_CROSS))
    assert ops == []


def test_crossover_loss_lot_excluded():
    prices = _FixedPriceSource({"NVDA": 10000}, _fx_rate(8600, _AS_OF_CROSS))
    ops = find_crossover_opportunities(
        [_CROSS_LOT], _AS_OF_CROSS, prices, Decimal("30"), 8_000_000, _ruleset(_AS_OF_CROSS),
    )
    assert ops == []


def test_crossover_ranked_by_tax_saving_desc():
    lot1 = _lot("NVDA", 20, date(2024, 2, 15), 15000, 8300)
    lot2 = _lot("AAPL", 5, date(2024, 3, 1), 15000, 8300)
    prices = _FixedPriceSource({"NVDA": 20000, "AAPL": 20000}, _fx_rate(8600, _AS_OF_CROSS))
    ops = find_crossover_opportunities([lot1, lot2], _AS_OF_CROSS, prices, Decimal("30"), 8_000_000, _ruleset(_AS_OF_CROSS))
    assert len(ops) >= 1
    for i in range(len(ops) - 1):
        assert ops[i].tax_saving_paise >= ops[i + 1].tax_saving_paise


# Scenario C: carry_forward

def test_carry_forward_when_losses_exceed_gains():
    rs = _ruleset()
    agg = FyAggregates(stcg_paise=0, ltcg_paise=0, stcl_paise=3_000_000, ltcl_paise=1_500_000)
    setoff = apply_setoff(agg, rs)
    note = find_carry_forward(setoff, rs)
    assert note is not None
    assert note.stcl_carry_paise == 3_000_000
    assert note.ltcl_carry_paise == 1_500_000
    assert note.total_carry_paise == 4_500_000


def test_carry_forward_years_from_ruleset():
    rs = _ruleset()
    setoff = SetoffResult(
        net_stcg_paise=0, net_ltcg_paise=0,
        carry_forward_stcl_paise=1_000_000, carry_forward_ltcl_paise=0,
    )
    note = find_carry_forward(setoff, rs)
    assert note is not None
    assert note.carry_forward_years == 8


def test_carry_forward_filing_condition_mentions_139():
    rs = _ruleset()
    setoff = SetoffResult(
        net_stcg_paise=0, net_ltcg_paise=0,
        carry_forward_stcl_paise=500_000, carry_forward_ltcl_paise=0,
    )
    note = find_carry_forward(setoff, rs)
    assert note is not None
    assert "139" in note.filing_condition


def test_carry_forward_none_when_no_losses():
    rs = _ruleset()
    setoff = SetoffResult(
        net_stcg_paise=1_000_000, net_ltcg_paise=500_000,
        carry_forward_stcl_paise=0, carry_forward_ltcl_paise=0,
    )
    assert find_carry_forward(setoff, rs) is None


# Scenario D: full report

def test_report_gaar_notice_present():
    rs = _ruleset(_AS_OF_HARVEST)
    agg = FyAggregates(stcg_paise=2_000_000)
    setoff = apply_setoff(agg, rs)
    report = build_opportunity_report(
        [_HARVEST_LOT], agg, setoff, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, "old", rs,
    )
    assert "GAAR" in report.gaar_notice
    assert "30 calendar days" in report.gaar_notice


def test_report_disclaimer_present():
    rs = _ruleset(_AS_OF_HARVEST)
    agg = FyAggregates(stcg_paise=2_000_000)
    setoff = apply_setoff(agg, rs)
    report = build_opportunity_report(
        [_HARVEST_LOT], agg, setoff, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, "old", rs,
    )
    assert "Chartered Accountant" in report.disclaimer


def test_report_financial_year_from_ruleset():
    rs = _ruleset(_AS_OF_HARVEST)
    agg = FyAggregates()
    setoff = apply_setoff(agg, rs)
    report = build_opportunity_report(
        [], agg, setoff, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, "old", rs,
    )
    assert report.financial_year == "2025-26"


def test_report_no_carry_forward_when_no_losses():
    rs = _ruleset(_AS_OF_HARVEST)
    agg = FyAggregates(stcg_paise=1_000_000)
    setoff = apply_setoff(agg, rs)
    report = build_opportunity_report(
        [], agg, setoff, _AS_OF_HARVEST,
        _HARVEST_PRICES, Decimal("30"), 8_000_000, "old", rs,
    )
    assert report.carry_forward is None
