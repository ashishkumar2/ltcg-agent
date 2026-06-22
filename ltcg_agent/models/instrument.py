from __future__ import annotations

from pydantic import BaseModel, field_validator

from ltcg_agent.models.money import Currency


class Instrument(BaseModel):
    ticker: str
    name: str
    exchange: str
    currency: Currency

    model_config = {"frozen": True}

    @field_validator("ticker")
    @classmethod
    def _ticker_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("ticker must not be empty")
        return v.strip().upper()

    @field_validator("exchange")
    @classmethod
    def _exchange_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("exchange must not be empty")
        return v.strip().upper()
