from __future__ import annotations

from datetime import date

from ltcg_agent.models.escalation import EscalationFlag, EscalationReason, EscalationSeverity
from ltcg_agent.models.portfolio import Portfolio, Trade

_RSU_ESPP_KEYWORDS = frozenset({"RSU", "ESPP", "ISO", "NSO", "VEST", "RESTRICTED"})
_PRE_2000_CUTOFF = date(2000, 4, 1)


class EscalationDetector:
    def detect(
        self,
        trades: list[Trade],
        portfolio: Portfolio,
    ) -> list[EscalationFlag]:
        flags: list[EscalationFlag] = []
        flags.extend(_check_rsu_espp(trades))
        flags.extend(_check_duplicate_lots(portfolio))
        flags.extend(_check_pre_2000_lots(portfolio))
        return flags


def _check_rsu_espp(trades: list[Trade]) -> list[EscalationFlag]:
    flagged: set[str] = set()
    for trade in trades:
        upper = trade.ticker.upper()
        if any(kw in upper for kw in _RSU_ESPP_KEYWORDS):
            flagged.add(trade.ticker)
    if not flagged:
        return []
    return [
        EscalationFlag(
            reason=EscalationReason.RSU_ESPP_DETECTED,
            severity=EscalationSeverity.ESCALATE,
            detail=(
                f"Tickers matching RSU/ESPP/ISO patterns detected: {sorted(flagged)}. "
                "Tax treatment of equity compensation differs from outright purchases — "
                "perquisite tax on vest date and cost basis rules require CA review."
            ),
        )
    ]


def _check_duplicate_lots(portfolio: Portfolio) -> list[EscalationFlag]:
    seen: dict[tuple[str, date], set[str]] = {}
    for lot in portfolio.lots:
        key = (lot.ticker, lot.acquisition_date)
        seen.setdefault(key, set()).add(lot.broker)

    duplicates = [
        f"{ticker} on {acq_date} ({', '.join(sorted(brokers))})"
        for (ticker, acq_date), brokers in seen.items()
        if len(brokers) > 1
    ]
    if not duplicates:
        return []
    return [
        EscalationFlag(
            reason=EscalationReason.DUPLICATE_LOT_RISK,
            severity=EscalationSeverity.ESCALATE,
            detail=(
                f"Same ticker acquired on the same date across multiple brokers — "
                f"risk of double-counted lots: {'; '.join(duplicates)}. Verify statements."
            ),
        )
    ]


def _check_pre_2000_lots(portfolio: Portfolio) -> list[EscalationFlag]:
    pre_2000 = [l for l in portfolio.lots if l.acquisition_date < _PRE_2000_CUTOFF]
    if not pre_2000:
        return []
    tickers = sorted({l.ticker for l in pre_2000})
    return [
        EscalationFlag(
            reason=EscalationReason.PRE_2000_LOT,
            severity=EscalationSeverity.WARNING,
            detail=(
                f"Lots acquired before 1 April 2000 detected ({tickers}). "
                "Indexed cost and FMV provisions from that era require manual verification."
            ),
        )
    ]
