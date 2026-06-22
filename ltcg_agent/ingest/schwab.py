from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from ltcg_agent.ingest.base import BrokerAdapter, IngestionResult
from ltcg_agent.models.money import Currency, Money
from ltcg_agent.models.portfolio import Trade

_DATE_FORMAT = "%m/%d/%Y"


class SchwabAdapter(BrokerAdapter):
    broker_name = "schwab"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".csv" and "schwab" in path.name.lower()

    def parse(self, path: Path) -> IngestionResult:
        trades: list[Trade] = []
        warnings: list[str] = []
        account_id = path.stem.split("_")[0] if "_" in path.stem else "unknown"

        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for lineno, row in enumerate(reader, start=2):
                action = row.get("Action", "").strip()
                if action not in ("Buy", "Sell"):
                    continue
                try:
                    trade_date = date.fromisoformat(
                        _reformat_date(row["Date"].strip())
                    )
                    ticker = row["Symbol"].strip()
                    raw_qty = int(float(row["Quantity"].strip()))
                    quantity = raw_qty if action == "Buy" else -raw_qty
                    price_cents = Money(
                        amount=_parse_dollars_to_cents(row["Price"].strip()),
                        currency=Currency.USD,
                    )
                    commission_cents = Money(
                        amount=_parse_dollars_to_cents(row.get("Fees & Comm", "0").strip()),
                        currency=Currency.USD,
                    )
                    trades.append(
                        Trade(
                            ticker=ticker,
                            trade_date=trade_date,
                            quantity=quantity,
                            price_cents=price_cents,
                            commission_cents=commission_cents,
                            broker=self.broker_name,
                            account_id=account_id,
                        )
                    )
                except (KeyError, ValueError) as exc:
                    warnings.append(f"Line {lineno}: skipped — {exc}")

        return IngestionResult(
            broker=self.broker_name,
            account_id=account_id,
            trades=trades,
            parse_warnings=warnings,
        )


def _reformat_date(raw: str) -> str:
    from datetime import datetime
    return datetime.strptime(raw, _DATE_FORMAT).strftime("%Y-%m-%d")


def _parse_dollars_to_cents(raw: str) -> int:
    cleaned = raw.replace("$", "").replace(",", "").strip()
    if not cleaned or cleaned == "--":
        return 0
    return round(float(cleaned) * 100)
