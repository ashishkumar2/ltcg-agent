from datetime import date

from ltcg_agent.engine.escalation import EscalationDetector
from ltcg_agent.models.escalation import EscalationReason, EscalationSeverity
from ltcg_agent.models.money import Currency, Money
from ltcg_agent.models.portfolio import Portfolio, TaxLot, Trade


def _lot(ticker: str, broker: str = "schwab", acq_date: date = date(2022, 1, 1)) -> TaxLot:
    return TaxLot(
        ticker=ticker,
        acquisition_date=acq_date,
        quantity=10,
        cost_per_share_cents=Money(amount=10000, currency=Currency.USD),
        acquisition_ttbr_paise=800000,
        broker=broker,
        account_id="acc1",
    )


def _trade(ticker: str) -> Trade:
    return Trade(
        ticker=ticker,
        trade_date=date(2024, 1, 1),
        quantity=10,
        price_cents=Money(amount=15000, currency=Currency.USD),
        broker="schwab",
        account_id="acc1",
    )


def test_rsu_keyword_in_ticker_raises_escalation():
    detector = EscalationDetector()
    trades = [_trade("AMZN_RSU")]
    flags = detector.detect(trades, Portfolio())
    reasons = [f.reason for f in flags]
    assert EscalationReason.RSU_ESPP_DETECTED in reasons


def test_clean_trade_no_escalation():
    detector = EscalationDetector()
    trades = [_trade("AAPL"), _trade("MSFT")]
    flags = detector.detect(trades, Portfolio())
    assert flags == []


def test_duplicate_lot_same_ticker_same_date_two_brokers():
    detector = EscalationDetector()
    lots = [
        _lot("GOOGL", broker="schwab", acq_date=date(2022, 3, 1)),
        _lot("GOOGL", broker="ibkr", acq_date=date(2022, 3, 1)),
    ]
    flags = detector.detect([], Portfolio(lots=lots))
    reasons = [f.reason for f in flags]
    assert EscalationReason.DUPLICATE_LOT_RISK in reasons


def test_duplicate_lot_same_broker_no_escalation():
    detector = EscalationDetector()
    lots = [
        _lot("GOOGL", broker="schwab", acq_date=date(2022, 3, 1)),
        _lot("GOOGL", broker="schwab", acq_date=date(2022, 3, 1)),
    ]
    flags = detector.detect([], Portfolio(lots=lots))
    reasons = [f.reason for f in flags]
    assert EscalationReason.DUPLICATE_LOT_RISK not in reasons


def test_pre_2000_lot_raises_warning():
    detector = EscalationDetector()
    lots = [_lot("IBM", acq_date=date(1999, 6, 1))]
    flags = detector.detect([], Portfolio(lots=lots))
    reasons = [f.reason for f in flags]
    assert EscalationReason.PRE_2000_LOT in reasons
    severity = next(f.severity for f in flags if f.reason == EscalationReason.PRE_2000_LOT)
    assert severity == EscalationSeverity.WARNING
