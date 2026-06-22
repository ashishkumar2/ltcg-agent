from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field, model_validator

from ltcg_agent.models.instrument import Instrument
from ltcg_agent.models.money import Currency, Money


class Lot(BaseModel):
    lot_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    instrument: Instrument
    quantity: int
    acquisition_date: date
    acquisition_price_usd: Money
    source: str

    model_config = {"frozen": True}

    @model_validator(mode="after")
    def _positive_quantity(self) -> Lot:
        if self.quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {self.quantity}")
        if self.acquisition_price_usd.currency != Currency.USD:
            raise ValueError("acquisition_price_usd must be in USD")
        if self.acquisition_price_usd.amount <= 0:
            raise ValueError("acquisition_price_usd must be positive")
        return self

    @property
    def total_cost_usd(self) -> Money:
        return Money(
            amount=self.acquisition_price_usd.amount * self.quantity,
            currency=Currency.USD,
        )


class SaleEvent(BaseModel):
    lot_id: str | None
    quantity: int
    sale_date: date
    sale_price_usd: Money
    source: str

    model_config = {"frozen": True}

    @model_validator(mode="after")
    def _positive_quantity(self) -> SaleEvent:
        if self.quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {self.quantity}")
        if self.sale_price_usd.currency != Currency.USD:
            raise ValueError("sale_price_usd must be in USD")
        if self.sale_price_usd.amount <= 0:
            raise ValueError("sale_price_usd must be positive")
        return self

    @property
    def total_proceeds_usd(self) -> Money:
        return Money(
            amount=self.sale_price_usd.amount * self.quantity,
            currency=Currency.USD,
        )


class SplitEvent(BaseModel):
    ticker: str
    split_date: date
    ratio_numerator: int
    ratio_denominator: int
    lot_id: str | None = None

    model_config = {"frozen": True}

    @model_validator(mode="after")
    def _valid_ratio(self) -> SplitEvent:
        if self.ratio_numerator <= 0 or self.ratio_denominator <= 0:
            raise ValueError(
                f"Split ratio components must be positive: "
                f"{self.ratio_numerator}:{self.ratio_denominator}"
            )
        return self

    @property
    def adjusted_quantity(self) -> int:
        def _gcd(a: int, b: int) -> int:
            while b:
                a, b = b, a % b
            return a

        return self.ratio_numerator // _gcd(self.ratio_numerator, self.ratio_denominator)

    @property
    def adjusted_price_numerator(self) -> int:
        return self.ratio_denominator

    @property
    def adjusted_price_denominator(self) -> int:
        return self.ratio_numerator

    def apply_to_lot(self, lot: Lot) -> Lot:
        new_qty = lot.quantity * self.ratio_numerator // self.ratio_denominator
        new_price_cents = (
            lot.acquisition_price_usd.amount
            * self.ratio_denominator
            // self.ratio_numerator
        )
        return Lot(
            lot_id=lot.lot_id,
            instrument=lot.instrument,
            quantity=new_qty,
            acquisition_date=lot.acquisition_date,
            acquisition_price_usd=Money(
                amount=new_price_cents, currency=Currency.USD
            ),
            source=lot.source,
        )


class Holding(BaseModel):
    lots: list[Lot] = Field(default_factory=list)

    def for_ticker(self, ticker: str) -> list[Lot]:
        return [l for l in self.lots if l.instrument.ticker == ticker.upper()]

    def total_quantity(self, ticker: str) -> int:
        return sum(l.quantity for l in self.for_ticker(ticker))


class RealizedTrade(BaseModel):
    lot: Lot
    sale: SaleEvent
    quantity_matched: int
    gain_usd: Money
    holding_days: int

    model_config = {"frozen": True}

    @property
    def is_loss(self) -> bool:
        return self.gain_usd.amount < 0
