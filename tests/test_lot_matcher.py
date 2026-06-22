import pytest
from datetime import date

from ltcg_agent.engine.lot_matcher import fifo_match
from ltcg_agent.models.money import Currency, Money
from ltcg_agent.models.portfolio import TaxLot


def _make_lot(qty: int, days_ago: int) -> TaxLot:
    from datetime import timedelta
    acq = date(2022, 1, 1) + timedelta(days=days_ago)
    return TaxLot(
        ticker="AAPL",
        acquisition_date=acq,
        quantity=qty,
        cost_per_share_cents=Money(amount=15000, currency=Currency.USD),
        acquisition_ttbr_paise=8300_00,
        broker="schwab",
        account_id="acc1",
    )


def test_fifo_match_exact_quantity():
    lots = [_make_lot(10, 100), _make_lot(5, 200)]
    consumed, remaining = fifo_match(lots, 10)
    assert sum(l.quantity for l in consumed) == 10
    assert sum(l.quantity for l in remaining) == 5


def test_fifo_match_partial_lot():
    lots = [_make_lot(20, 100)]
    consumed, remaining = fifo_match(lots, 7)
    assert consumed[0].quantity == 7
    assert remaining[0].quantity == 13


def test_fifo_match_across_multiple_lots():
    lots = [_make_lot(5, 10), _make_lot(5, 20), _make_lot(5, 30)]
    consumed, remaining = fifo_match(lots, 12)
    assert sum(l.quantity for l in consumed) == 12
    assert sum(l.quantity for l in remaining) == 3


def test_fifo_match_insufficient_lots_raises():
    lots = [_make_lot(3, 10)]
    with pytest.raises(ValueError, match="Insufficient lots"):
        fifo_match(lots, 10)


def test_fifo_match_uses_chronological_order():
    old = _make_lot(5, 300)
    new = _make_lot(5, 100)
    consumed, _ = fifo_match([new, old], 5)
    assert consumed[0].acquisition_date == old.acquisition_date
