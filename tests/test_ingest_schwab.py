from pathlib import Path

from ltcg_agent.ingest.schwab import SchwabAdapter


_FIXTURE = Path(__file__).parent / "fixtures" / "schwab_sample.csv"


def test_schwab_parse_trade_count():
    adapter = SchwabAdapter()
    result = adapter.parse(_FIXTURE)
    assert len(result.trades) == 4


def test_schwab_parse_buy_trade():
    adapter = SchwabAdapter()
    result = adapter.parse(_FIXTURE)
    buys = [t for t in result.trades if t.quantity > 0]
    assert len(buys) == 3
    aapl_buy = next(t for t in buys if t.ticker == "AAPL")
    assert aapl_buy.price_cents.amount == 15000
    assert aapl_buy.quantity == 10


def test_schwab_parse_sell_trade():
    adapter = SchwabAdapter()
    result = adapter.parse(_FIXTURE)
    sells = [t for t in result.trades if t.quantity < 0]
    assert len(sells) == 1
    assert sells[0].ticker == "AAPL"


def test_schwab_parse_no_warnings():
    adapter = SchwabAdapter()
    result = adapter.parse(_FIXTURE)
    assert result.parse_warnings == []


def test_schwab_supports_recognises_file():
    adapter = SchwabAdapter()
    assert adapter.supports(Path("schwab_2024.csv"))
    assert not adapter.supports(Path("ibkr_report.csv"))
