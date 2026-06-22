from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from ltcg_agent.ingest.base import BrokerAdapter, IngestionResult
from ltcg_agent.models.money import Currency, Money
from ltcg_agent.models.portfolio import Trade


class IBKRAdapter(BrokerAdapter):
    broker_name = "ibkr"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".csv" and (
            "ibkr" in path.name.lower() or "interactivebrokers" in path.name.lower()
        )

    def parse(self, path: Path) -> IngestionResult:
        trades: list[Trade] = []
        warnings: list[str] = []
        account_id = "unknown"

        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            in_trades_section = False
            headers: list[str] = []

            for lineno, row in enumerate(reader, start=1):
                if not row:
                    continue

                section = row[0].strip()

                if section == "Statement" and len(row) > 2 and row[1].strip() == "Field Value":
                    if len(row) > 3 and row[2].strip() == "Account":
                        account_id = row[3].strip()

                if section == "Trades":
                    if row[1].strip() == "Header":
                        headers = [c.strip() for c in row]
                        in_trades_section = True
                        continue
                    if in_trades_section and row[1].strip() == "Data":
                        try:
                            record = dict(zip(headers, row))
                            asset_cat = record.get("Asset Category", "").strip()
                            if asset_cat != "Stocks":
                                continue
                            trade_date = date.fromisoformat(
                                record["Date/Time"].strip().split(",")[0].strip()
                            )
                            quantity = abs(int(float(record["Quantity"].strip())))
                            price_cents = Money(
                                amount=round(float(record["T. Price"].strip()) * 100),
                                currency=Currency.USD,
                            )
                            commission_cents = Money(
                                amount=round(abs(float(record.get("Comm/Fee", "0").strip())) * 100),
                                currency=Currency.USD,
                            )
                            trades.append(
                                Trade(
                                    ticker=record["Symbol"].strip(),
                                    isin=record.get("ISIN", "").strip() or None,
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
                    elif in_trades_section and row[1].strip() != "Data":
                        in_trades_section = False

        return IngestionResult(
            broker=self.broker_name,
            account_id=account_id,
            trades=trades,
            parse_warnings=warnings,
        )
