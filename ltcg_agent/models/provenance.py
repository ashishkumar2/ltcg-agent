from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from ltcg_agent.models.money import Currency, Money


class FxProvenance(BaseModel):
    usd_cents: int
    ttbr_paise_per_usd: int
    rate_date: date
    inr_paise: int

    model_config = {"frozen": True}

    @property
    def usd(self) -> Money:
        return Money(amount=self.usd_cents, currency=Currency.USD)

    @property
    def inr(self) -> Money:
        return Money(amount=self.inr_paise, currency=Currency.INR)

    @classmethod
    def convert(
        cls,
        usd_cents: int,
        ttbr_paise_per_usd: int,
        rate_date: date,
    ) -> FxProvenance:
        inr_paise = round(usd_cents * ttbr_paise_per_usd / 100)
        return cls(
            usd_cents=usd_cents,
            ttbr_paise_per_usd=ttbr_paise_per_usd,
            rate_date=rate_date,
            inr_paise=inr_paise,
        )
