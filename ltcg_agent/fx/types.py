from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class RateEntry(BaseModel):
    rate_date: date
    ttbr_paise_per_usd: int
    source: str

    model_config = {"frozen": True}


class ConvertedAmount(BaseModel):
    usd_cents: int
    inr_paise: int
    rate: int
    rate_date: date
    source: str

    model_config = {"frozen": True}


class MissingRateError(Exception):
    def __init__(self, requested_date: date, max_lookback_days: int) -> None:
        self.requested_date = requested_date
        self.max_lookback_days = max_lookback_days
        super().__init__(
            f"No SBI TTBR rate found for {requested_date} or the "
            f"{max_lookback_days} preceding days. "
            f"Populate via TTBRClient.refresh() or seed ltcg_agent/fx/data/seed_rates.csv."
        )
