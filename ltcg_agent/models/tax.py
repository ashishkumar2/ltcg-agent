from __future__ import annotations

import uuid
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

from ltcg_agent.models.escalation import EscalationFlag
from ltcg_agent.models.money import Currency, Money
from ltcg_agent.models.provenance import FxProvenance

_DISCLAIMER = (
    "IMPORTANT — This output is an estimate only and does not constitute tax advice. "
    "All figures must be independently verified by a qualified Chartered Accountant "
    "before filing any return. Tax laws and exchange rates change; the computations "
    "here reflect rules and rates as understood at the time of generation. "
    "Verify with a chartered accountant before filing."
)


class GainCategory(StrEnum):
    LTCG = "LTCG"
    STCG = "STCG"


class TaxEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticker: str
    isin: str | None = None
    lot_id: str
    acquisition_date: date
    disposal_date: date
    quantity: int
    cost_basis_inr: Money
    sale_proceeds_inr: Money
    gain_inr: Money
    category: GainCategory
    holding_days: int
    grandfathered: bool = False
    grandfathered_cost_inr: Money | None = None
    acquisition_fx: FxProvenance
    disposal_fx: FxProvenance

    model_config = {"frozen": True}

    @property
    def is_loss(self) -> bool:
        return self.gain_inr.amount < 0

    @property
    def net_gain_inr(self) -> Money:
        return self.gain_inr


class HarvestCandidate(BaseModel):
    ticker: str
    lot_id: str
    acquisition_date: date
    quantity: int
    current_price_cents: Money
    current_ttbr_paise: int
    unrealised_loss_inr: Money
    category: GainCategory

    model_config = {"frozen": True}


class TaxSummary(BaseModel):
    financial_year: str
    events: list[TaxEvent] = Field(default_factory=list)
    harvest_candidates: list[HarvestCandidate] = Field(default_factory=list)
    escalation_flags: list[EscalationFlag] = Field(default_factory=list)
    disclaimer: str = _DISCLAIMER

    @property
    def total_ltcg(self) -> Money:
        return sum(
            (e.gain_inr for e in self.events if e.category == GainCategory.LTCG and not e.is_loss),
            start=Money.zero(Currency.INR),
        )

    @property
    def total_stcg(self) -> Money:
        return sum(
            (e.gain_inr for e in self.events if e.category == GainCategory.STCG and not e.is_loss),
            start=Money.zero(Currency.INR),
        )

    @property
    def total_ltcl(self) -> Money:
        return sum(
            (Money(amount=abs(e.gain_inr.amount), currency=Currency.INR)
             for e in self.events if e.category == GainCategory.LTCG and e.is_loss),
            start=Money.zero(Currency.INR),
        )

    @property
    def total_stcl(self) -> Money:
        return sum(
            (Money(amount=abs(e.gain_inr.amount), currency=Currency.INR)
             for e in self.events if e.category == GainCategory.STCG and e.is_loss),
            start=Money.zero(Currency.INR),
        )

    @property
    def must_escalate(self) -> bool:
        from ltcg_agent.models.escalation import EscalationSeverity
        return any(f.severity == EscalationSeverity.ESCALATE for f in self.escalation_flags)
