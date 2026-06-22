from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field

from ltcg_agent.models.money import Currency, Money


class Trade(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticker: str
    isin: str | None = None
    trade_date: date
    quantity: int
    price_cents: Money
    commission_cents: Money = Field(default_factory=lambda: Money.zero(Currency.USD))
    broker: str
    account_id: str

    model_config = {"frozen": True}

    @property
    def gross_value(self) -> Money:
        return self.price_cents * self.quantity

    @property
    def net_value(self) -> Money:
        return self.gross_value + self.commission_cents


class TaxLot(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticker: str
    isin: str | None = None
    acquisition_date: date
    quantity: int
    cost_per_share_cents: Money
    acquisition_ttbr_paise: int
    broker: str
    account_id: str
    source_trade_id: str | None = None

    model_config = {"frozen": True}

    @property
    def total_cost_usd(self) -> Money:
        return self.cost_per_share_cents * self.quantity

    @property
    def total_cost_inr(self) -> Money:
        return self.total_cost_usd.convert_to_inr(self.acquisition_ttbr_paise)

    def split(self, quantity: int) -> tuple[TaxLot, TaxLot | None]:
        if quantity >= self.quantity:
            return self, None
        used = TaxLot(
            ticker=self.ticker,
            isin=self.isin,
            acquisition_date=self.acquisition_date,
            quantity=quantity,
            cost_per_share_cents=self.cost_per_share_cents,
            acquisition_ttbr_paise=self.acquisition_ttbr_paise,
            broker=self.broker,
            account_id=self.account_id,
            source_trade_id=self.source_trade_id,
        )
        remainder = TaxLot(
            ticker=self.ticker,
            isin=self.isin,
            acquisition_date=self.acquisition_date,
            quantity=self.quantity - quantity,
            cost_per_share_cents=self.cost_per_share_cents,
            acquisition_ttbr_paise=self.acquisition_ttbr_paise,
            broker=self.broker,
            account_id=self.account_id,
            source_trade_id=self.source_trade_id,
        )
        return used, remainder


class Portfolio(BaseModel):
    lots: list[TaxLot] = Field(default_factory=list)

    def open_lots_for(self, ticker: str) -> list[TaxLot]:
        return [lot for lot in self.lots if lot.ticker == ticker]

    def total_quantity(self, ticker: str) -> int:
        return sum(lot.quantity for lot in self.open_lots_for(ticker))
