from datetime import date

import pytest

from ltcg_agent.engine.ltcg import TaxEngine
from ltcg_agent.models.money import Currency, Money
from ltcg_agent.models.portfolio import Portfolio, TaxLot, Trade
from ltcg_agent.models.tax import GainCategory
from ltcg_agent.rules.loader import RuleField, TaxRuleSet


def _rf(value, src: str = "test") -> RuleField:
    return RuleField(value=value, effective_from=date(2024, 4, 1), source=src)


def _rules() -> TaxRuleSet:
    return TaxRuleSet(
        financial_year="2024-25",
        effective_from=date(2024, 4, 1),
        effective_to=date(2025, 3, 31),
        ltcg_rate_bps=_rf(1250),
        stcg_rate_bps=_rf(2000),
        ltcg_exemption_paise=_rf(12_500_000),
        ltcg_holding_months=_rf(24),
        grandfathering_enabled=_rf(True),
        min_harvest_loss_paise=_rf(500_000),
    )


def _lot(qty: int, acq_date: date, cost_cents: int = 10000) -> TaxLot:
    return TaxLot(
        ticker="AAPL",
        acquisition_date=acq_date,
        quantity=qty,
        cost_per_share_cents=Money(amount=cost_cents, currency=Currency.USD),
        acquisition_ttbr_paise=7500_00,
        broker="schwab",
        account_id="acc1",
    )


def _sale(qty: int, sale_date: date, price_cents: int = 20000) -> Trade:
    return Trade(
        ticker="AAPL",
        trade_date=sale_date,
        quantity=qty,
        price_cents=Money(amount=price_cents, currency=Currency.USD),
        broker="schwab",
        account_id="acc1",
    )


def test_process_disposal_ltcg_after_24_months():
    engine = TaxEngine(_rules())
    lot = _lot(10, date(2020, 1, 1))
    portfolio = Portfolio(lots=[lot])
    sale = _sale(10, date(2022, 2, 1))
    events, updated = engine.process_disposal(sale, portfolio, sale_ttbr_paise=8000_00)
    assert len(events) == 1
    assert events[0].category == GainCategory.LTCG
    assert len(updated.lots) == 0


def test_process_disposal_stcg_within_24_months():
    engine = TaxEngine(_rules())
    lot = _lot(5, date(2023, 1, 1))
    portfolio = Portfolio(lots=[lot])
    sale = _sale(5, date(2024, 6, 1))
    events, _ = engine.process_disposal(sale, portfolio, sale_ttbr_paise=8400_00)
    assert events[0].category == GainCategory.STCG


def test_process_disposal_gain_calculation():
    engine = TaxEngine(_rules())
    lot = _lot(1, date(2019, 1, 1), cost_cents=10000)
    portfolio = Portfolio(lots=[lot])
    sale = _sale(1, date(2022, 1, 1), price_cents=20000)
    events, _ = engine.process_disposal(sale, portfolio, sale_ttbr_paise=8000_00)
    e = events[0]
    assert e.sale_proceeds_inr.amount > e.cost_basis_inr.amount
    assert not e.is_loss


def test_process_disposal_loss():
    engine = TaxEngine(_rules())
    lot = _lot(1, date(2023, 1, 1), cost_cents=20000)
    portfolio = Portfolio(lots=[lot])
    sale = _sale(1, date(2024, 6, 1), price_cents=10000)
    events, _ = engine.process_disposal(sale, portfolio, sale_ttbr_paise=8400_00)
    assert events[0].is_loss


def test_grandfathering_elevates_cost_basis():
    engine = TaxEngine(_rules())
    lot = _lot(1, date(2017, 6, 1), cost_cents=5000)
    portfolio = Portfolio(lots=[lot])
    sale = _sale(1, date(2022, 1, 1), price_cents=30000)
    fmv = {"AAPL": Money(amount=20000, currency=Currency.USD)}
    events, _ = engine.process_disposal(
        sale, portfolio, sale_ttbr_paise=8000_00, fmv_31jan2018_cents=fmv
    )
    assert events[0].grandfathered is True
    assert events[0].cost_basis_inr.amount > lot.total_cost_inr.amount


def test_tax_event_has_fx_provenance():
    engine = TaxEngine(_rules())
    lot = _lot(2, date(2020, 6, 1), cost_cents=15000)
    portfolio = Portfolio(lots=[lot])
    sale = _sale(2, date(2023, 6, 1), price_cents=25000)
    events, _ = engine.process_disposal(sale, portfolio, sale_ttbr_paise=8300_00)
    e = events[0]
    assert e.acquisition_fx.ttbr_paise_per_usd == 7500_00
    assert e.acquisition_fx.rate_date == date(2020, 6, 1)
    assert e.disposal_fx.ttbr_paise_per_usd == 8300_00
    assert e.disposal_fx.rate_date == date(2023, 6, 1)


def test_fx_provenance_formula_correct():
    engine = TaxEngine(_rules())
    lot = _lot(1, date(2020, 1, 1), cost_cents=10000)
    portfolio = Portfolio(lots=[lot])
    sale = _sale(1, date(2023, 1, 1), price_cents=20000)
    ttbr = 8000_00
    events, _ = engine.process_disposal(sale, portfolio, sale_ttbr_paise=ttbr)
    e = events[0]
    expected_cost_paise = round(10000 * 8000_00 / 100)
    assert e.acquisition_fx.inr_paise == expected_cost_paise
