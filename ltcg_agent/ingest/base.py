from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from ltcg_agent.models.instrument import Instrument
from ltcg_agent.models.lot import Lot, SaleEvent, SplitEvent
from ltcg_agent.models.money import Currency, Money
from ltcg_agent.models.portfolio import Trade


class IngestionResult(BaseModel):
    broker: str
    account_id: str
    trades: list[Trade]
    parse_warnings: list[str] = []


class BrokerAdapter(ABC):
    broker_name: str

    @abstractmethod
    def parse(self, path: Path) -> IngestionResult: ...

    @abstractmethod
    def supports(self, path: Path) -> bool: ...


class ParseResult(BaseModel):
    lots: list[Lot] = Field(default_factory=list)
    sale_events: list[SaleEvent] = Field(default_factory=list)
    split_events: list[SplitEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source: str


class ColumnMapping(BaseModel):
    ticker: str
    quantity: str
    action: str
    date: str
    price_usd: str
    lot_id: str | None = None
    name: str | None = None
    exchange: str | None = None
    split_ratio: str | None = None
    ignore_columns: frozenset[str] = Field(default_factory=frozenset)
    buy_action_value: str = "BUY"
    sell_action_value: str = "SELL"
    split_action_value: str = "SPLIT"
    date_format: str = "%Y-%m-%d"
    source_name: str = "csv"
    default_exchange: str = "NYSE"
    default_currency: Currency = Currency.USD

    model_config = {"frozen": True}

    def known_columns(self) -> frozenset[str]:
        mapped: set[str] = {
            self.ticker,
            self.quantity,
            self.action,
            self.date,
            self.price_usd,
        }
        for optional in (self.lot_id, self.name, self.exchange, self.split_ratio):
            if optional is not None:
                mapped.add(optional)
        return frozenset(mapped) | self.ignore_columns

    @property
    def required_columns(self) -> frozenset[str]:
        return frozenset({self.ticker, self.quantity, self.action, self.date, self.price_usd})


@runtime_checkable
class StatementParser(Protocol):
    def parse(self, source: Path) -> ParseResult: ...
    def supports(self, source: Path) -> bool: ...


class UnknownColumnError(ValueError):
    pass


class MissingColumnError(ValueError):
    pass


def validate_columns(headers: list[str], mapping: ColumnMapping) -> None:
    csv_cols = frozenset(headers)
    unknown = csv_cols - mapping.known_columns()
    if unknown:
        raise UnknownColumnError(
            f"CSV contains columns not declared in ColumnMapping: {sorted(unknown)}. "
            f"Add them to the mapping fields or to ignore_columns."
        )
    missing = mapping.required_columns - csv_cols
    if missing:
        raise MissingColumnError(
            f"CSV is missing required columns declared in ColumnMapping: {sorted(missing)}."
        )


def build_lot(row: dict[str, str], mapping: ColumnMapping) -> Lot:
    ticker = _require(row, mapping.ticker, "ticker").upper()
    name = _optional_str(row, mapping.name) or ticker
    exchange = _optional_str(row, mapping.exchange) or mapping.default_exchange
    instrument = Instrument(
        ticker=ticker,
        name=name,
        exchange=exchange,
        currency=mapping.default_currency,
    )
    quantity_str = _require(row, mapping.quantity, "quantity")
    quantity = int(float(quantity_str))
    price_str = _require(row, mapping.price_usd, "price_usd")
    price_cents = _parse_price_to_cents(price_str)
    raw_date = _require(row, mapping.date, "date")
    acq_date = datetime.strptime(raw_date.strip(), mapping.date_format).date()
    lot_id_val = _optional_str(row, mapping.lot_id) or str(uuid.uuid4())
    return Lot(
        lot_id=lot_id_val,
        instrument=instrument,
        quantity=quantity,
        acquisition_date=acq_date,
        acquisition_price_usd=Money(amount=price_cents, currency=Currency.USD),
        source=mapping.source_name,
    )


def build_sale_event(row: dict[str, str], mapping: ColumnMapping) -> SaleEvent:
    quantity_str = _require(row, mapping.quantity, "quantity")
    quantity = int(float(quantity_str))
    price_str = _require(row, mapping.price_usd, "price_usd")
    price_cents = _parse_price_to_cents(price_str)
    raw_date = _require(row, mapping.date, "date")
    sale_date = datetime.strptime(raw_date.strip(), mapping.date_format).date()
    lot_id_val = _optional_str(row, mapping.lot_id) or None
    return SaleEvent(
        lot_id=lot_id_val,
        quantity=quantity,
        sale_date=sale_date,
        sale_price_usd=Money(amount=price_cents, currency=Currency.USD),
        source=mapping.source_name,
    )


def build_split_event(row: dict[str, str], mapping: ColumnMapping) -> SplitEvent:
    if mapping.split_ratio is None:
        raise ValueError("ColumnMapping.split_ratio not configured; cannot parse SPLIT rows")
    ticker = _require(row, mapping.ticker, "ticker").upper()
    raw_date = _require(row, mapping.date, "date")
    split_date = datetime.strptime(raw_date.strip(), mapping.date_format).date()
    ratio_str = _optional_str(row, mapping.split_ratio) or ""
    numerator, denominator = _parse_split_ratio(ratio_str)
    lot_id_val = _optional_str(row, mapping.lot_id) or None
    return SplitEvent(
        ticker=ticker,
        split_date=split_date,
        ratio_numerator=numerator,
        ratio_denominator=denominator,
        lot_id=lot_id_val,
    )


def _require(row: dict[str, str], col: str, field_name: str) -> str:
    val = row.get(col, "").strip()
    if not val:
        raise ValueError(f"Required field '{field_name}' (column '{col}') is empty")
    return val


def _optional_str(row: dict[str, str], col: str | None) -> str:
    if col is None:
        return ""
    return row.get(col, "").strip()


def _parse_price_to_cents(price_str: str) -> int:
    cleaned = price_str.replace("$", "").replace(",", "").strip()
    return round(float(cleaned) * 100)


def _parse_split_ratio(ratio_str: str) -> tuple[int, int]:
    if ":" not in ratio_str:
        raise ValueError(
            f"Invalid split ratio {ratio_str!r}. Expected 'N:M' (e.g. '10:1', '3:2')."
        )
    parts = ratio_str.split(":", 1)
    return int(parts[0].strip()), int(parts[1].strip())
