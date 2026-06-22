from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ltcg_agent.ingest.base import ColumnMapping, MissingColumnError, UnknownColumnError
from ltcg_agent.ingest.csv_adapter import CsvStatementAdapter
from ltcg_agent.models.lot import Lot, SaleEvent, SplitEvent
from ltcg_agent.models.money import Currency

_FIXTURES = Path(__file__).parent / "fixtures"

_MAPPING = ColumnMapping(
    ticker="Symbol",
    quantity="Quantity",
    action="Action",
    date="Date",
    price_usd="Price (USD)",
    lot_id="LotID",
    name="Name",
    exchange="Exchange",
    split_ratio="SplitRatio",
    buy_action_value="BUY",
    sell_action_value="SELL",
    split_action_value="SPLIT",
    date_format="%Y-%m-%d",
    source_name="fixture",
    ignore_columns=frozenset(),
)


def _adapter() -> CsvStatementAdapter:
    return CsvStatementAdapter(_MAPPING)


def _parse() -> tuple[list[Lot], list[SaleEvent], list[SplitEvent]]:
    result = _adapter().parse(_FIXTURES / "statement.csv")
    return result.lots, result.sale_events, result.split_events


def test_multiple_lots_same_ticker_produces_two_aapl_lots():
    lots, _, _ = _parse()
    aapl_lots = [l for l in lots if l.instrument.ticker == "AAPL"]
    assert len(aapl_lots) == 2


def test_multiple_lots_same_ticker_different_lot_ids():
    lots, _, _ = _parse()
    aapl_lots = [l for l in lots if l.instrument.ticker == "AAPL"]
    ids = {l.lot_id for l in aapl_lots}
    assert ids == {"LOT-AAPL-001", "LOT-AAPL-002"}


def test_multiple_lots_same_ticker_different_acquisition_dates():
    lots, _, _ = _parse()
    aapl_lots = sorted(
        [l for l in lots if l.instrument.ticker == "AAPL"],
        key=lambda l: l.acquisition_date,
    )
    assert aapl_lots[0].acquisition_date == date(2021, 1, 15)
    assert aapl_lots[1].acquisition_date == date(2021, 6, 20)


def test_lot_acquisition_price_stored_as_integer_cents():
    lots, _, _ = _parse()
    aapl_first = next(l for l in lots if l.lot_id == "LOT-AAPL-001")
    assert aapl_first.acquisition_price_usd.amount == 13205
    assert aapl_first.acquisition_price_usd.currency == Currency.USD


def test_lot_quantity_is_integer():
    lots, _, _ = _parse()
    aapl_first = next(l for l in lots if l.lot_id == "LOT-AAPL-001")
    assert aapl_first.quantity == 10
    assert isinstance(aapl_first.quantity, int)


def test_lot_has_no_gain_field():
    lots, _, _ = _parse()
    assert not hasattr(lots[0], "gain")
    assert not hasattr(lots[0], "gain_usd")
    assert not hasattr(lots[0], "gain_inr")


def test_partial_sale_creates_one_sale_event_with_correct_quantity():
    _, sales, _ = _parse()
    assert len(sales) == 1
    assert sales[0].quantity == 7


def test_partial_sale_references_correct_lot():
    _, sales, _ = _parse()
    assert sales[0].lot_id == "LOT-AAPL-001"


def test_partial_sale_price_stored_as_cents():
    _, sales, _ = _parse()
    assert sales[0].sale_price_usd.amount == 18930
    assert sales[0].sale_price_usd.currency == Currency.USD


def test_partial_sale_has_no_gain_field():
    _, sales, _ = _parse()
    assert not hasattr(sales[0], "gain")
    assert not hasattr(sales[0], "gain_usd")


def test_stock_split_creates_one_split_event():
    _, _, splits = _parse()
    nvda_splits = [s for s in splits if s.ticker == "NVDA"]
    assert len(nvda_splits) == 1


def test_stock_split_ratio_parsed_correctly():
    _, _, splits = _parse()
    nvda = next(s for s in splits if s.ticker == "NVDA")
    assert nvda.ratio_numerator == 10
    assert nvda.ratio_denominator == 1


def test_stock_split_date_parsed_correctly():
    _, _, splits = _parse()
    nvda = next(s for s in splits if s.ticker == "NVDA")
    assert nvda.split_date == date(2022, 9, 14)


def test_stock_split_lot_id_preserved():
    _, _, splits = _parse()
    nvda = next(s for s in splits if s.ticker == "NVDA")
    assert nvda.lot_id == "LOT-NVDA-001"


def test_split_apply_to_lot_adjusts_quantity_and_price():
    lots, _, splits = _parse()
    nvda_lot = next(l for l in lots if l.instrument.ticker == "NVDA")
    nvda_split = next(s for s in splits if s.ticker == "NVDA")
    adjusted = nvda_split.apply_to_lot(nvda_lot)
    assert adjusted.quantity == 300
    assert adjusted.acquisition_price_usd.amount == 2250


def test_total_lots_parsed():
    lots, _, _ = _parse()
    assert len(lots) == 3


def test_parse_produces_no_warnings_for_clean_fixture():
    result = _adapter().parse(_FIXTURES / "statement.csv")
    assert result.warnings == []


def test_unknown_column_raises_unknown_column_error():
    with pytest.raises(UnknownColumnError, match="UnknownColumn"):
        _adapter().parse(_FIXTURES / "statement_extra_col.csv")


def test_missing_required_column_raises_missing_column_error():
    with pytest.raises(MissingColumnError):
        _adapter().parse(_FIXTURES / "statement_missing_col.csv")


def test_instrument_ticker_uppercased():
    lots, _, _ = _parse()
    for lot in lots:
        assert lot.instrument.ticker == lot.instrument.ticker.upper()


def test_instrument_exchange_set_from_csv():
    lots, _, _ = _parse()
    for lot in lots:
        assert lot.instrument.exchange == "NASDAQ"


def test_source_name_set_from_mapping():
    lots, sales, _ = _parse()
    assert all(l.source == "fixture" for l in lots)
    assert all(s.source == "fixture" for s in sales)


def test_statement_parser_protocol_satisfied():
    from ltcg_agent.ingest.base import StatementParser
    adapter = _adapter()
    assert isinstance(adapter, StatementParser)


def test_column_mapping_known_columns_includes_all_mapped():
    known = _MAPPING.known_columns()
    assert "Symbol" in known
    assert "Quantity" in known
    assert "Action" in known
    assert "Date" in known
    assert "Price (USD)" in known
    assert "LotID" in known
    assert "SplitRatio" in known


def test_column_mapping_rejects_unknown_column_not_in_ignore():
    strict_mapping = ColumnMapping(
        ticker="Symbol",
        quantity="Quantity",
        action="Action",
        date="Date",
        price_usd="Price (USD)",
        ignore_columns=frozenset(),
    )
    adapter = CsvStatementAdapter(strict_mapping)
    with pytest.raises(UnknownColumnError):
        adapter.parse(_FIXTURES / "statement.csv")


def test_column_mapping_accepts_unknown_column_when_ignored():
    lenient_mapping = ColumnMapping(
        ticker="Symbol",
        quantity="Quantity",
        action="Action",
        date="Date",
        price_usd="Price (USD)",
        lot_id="LotID",
        name="Name",
        exchange="Exchange",
        split_ratio="SplitRatio",
        ignore_columns=frozenset({"UnknownColumn"}),
    )
    adapter = CsvStatementAdapter(lenient_mapping)
    result = adapter.parse(_FIXTURES / "statement_extra_col.csv")
    assert len(result.lots) == 1
