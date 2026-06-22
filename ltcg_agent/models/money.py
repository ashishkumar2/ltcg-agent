from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel


class Currency(StrEnum):
    INR = "INR"
    USD = "USD"


class Money(BaseModel):
    amount: int
    currency: Currency

    model_config = {"frozen": True}

    def __add__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __mul__(self, scalar: int) -> Money:
        return Money(amount=self.amount * scalar, currency=self.currency)

    def __truediv__(self, scalar: int) -> Money:
        return Money(amount=self.amount // scalar, currency=self.currency)

    def __lt__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount >= other.amount

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.amount == other.amount and self.currency == other.currency

    def __hash__(self) -> int:
        return hash((self.amount, self.currency))

    def __repr__(self) -> str:
        sign = "-" if self.amount < 0 else ""
        abs_amount = abs(self.amount)
        major = abs_amount // 100
        minor = abs_amount % 100
        symbol = "₹" if self.currency == Currency.INR else "$"
        return f"{sign}{symbol}{major}.{minor:02d}"

    def _assert_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise TypeError(
                f"Currency mismatch: {self.currency} vs {other.currency}"
            )

    @classmethod
    def zero(cls, currency: Currency) -> Money:
        return cls(amount=0, currency=currency)

    @classmethod
    def from_major_units(cls, major: float, currency: Currency) -> Money:
        return cls(amount=round(major * 100), currency=currency)

    def to_major_units(self) -> float:
        return self.amount / 100

    def convert_to_inr(self, ttbr_paise_per_usd: int) -> Money:
        if self.currency != Currency.USD:
            raise TypeError("Only USD can be converted to INR via TTBR")
        inr_paise = round(self.amount * ttbr_paise_per_usd / 100)
        return Money(amount=inr_paise, currency=Currency.INR)
