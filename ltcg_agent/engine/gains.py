from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from ltcg_agent.fx.types import ConvertedAmount, RateEntry
from ltcg_agent.models.portfolio import TaxLot, Trade
from ltcg_agent.rules.loader import ForeignEquityRuleSet

_DISCLAIMER = (
    "IMPORTANT — This output is an estimate only and does not constitute tax advice. "
    "All figures must be independently verified by a qualified Chartered Accountant "
    "before filing. Tax laws and exchange rates change; computations reflect rules "
    "and rates as understood at time of generation. Verify with a CA before filing."
)


class RealizedGain(BaseModel):
    lot_id: str
    ticker: str
    quantity: int
    acquisition_date: date
    disposal_date: date
    holding_days: int
    term: Literal["short", "long"]
    cost_basis_inr_paise: int
    proceeds_inr_paise: int
    gain_inr_paise: int
    acquisition_fx: ConvertedAmount
    disposal_fx: ConvertedAmount

    model_config = {"frozen": True}

    @property
    def is_loss(self) -> bool:
        return self.gain_inr_paise < 0


class FyAggregates(BaseModel):
    stcg_paise: int = 0
    ltcg_paise: int = 0
    stcl_paise: int = 0
    ltcl_paise: int = 0
    gains: list[RealizedGain] = []

    model_config = {"frozen": True}


class SetoffResult(BaseModel):
    net_stcg_paise: int
    net_ltcg_paise: int
    carry_forward_stcl_paise: int
    carry_forward_ltcl_paise: int

    model_config = {"frozen": True}


class TaxEstimate(BaseModel):
    ltcg_tax_paise: int
    stcg_tax_paise: int
    surcharge_paise: int
    cess_paise: int
    total_tax_paise: int
    effective_rate_bps: int
    regime: str
    disclaimer: str = _DISCLAIMER

    model_config = {"frozen": True}


def classify_term(
    acquisition_date: date,
    sale_date: date,
    ruleset: ForeignEquityRuleSet,
) -> Literal["short", "long"]:
    holding_days = (sale_date - acquisition_date).days
    threshold_days = ruleset.long_term_threshold_months.value * 30
    return "long" if holding_days > threshold_days else "short"


def realized_gain(
    lot: TaxLot,
    sale: Trade,
    disposal_fx: RateEntry,
    ruleset: ForeignEquityRuleSet,
) -> RealizedGain:
    quantity = lot.quantity
    acq_usd_cents = lot.cost_per_share_cents.amount * quantity
    acq_inr_paise = round(acq_usd_cents * lot.acquisition_ttbr_paise / 100)
    acquisition_ca = ConvertedAmount(
        usd_cents=acq_usd_cents,
        inr_paise=acq_inr_paise,
        rate=lot.acquisition_ttbr_paise,
        rate_date=lot.acquisition_date,
        source="lot_record",
    )

    net_usd_cents = sale.price_cents.amount * quantity - sale.commission_cents.amount
    disp_inr_paise = round(net_usd_cents * disposal_fx.ttbr_paise_per_usd / 100)
    disposal_ca = ConvertedAmount(
        usd_cents=net_usd_cents,
        inr_paise=disp_inr_paise,
        rate=disposal_fx.ttbr_paise_per_usd,
        rate_date=disposal_fx.rate_date,
        source=disposal_fx.source,
    )

    term = classify_term(lot.acquisition_date, sale.trade_date, ruleset)
    holding_days = (sale.trade_date - lot.acquisition_date).days

    return RealizedGain(
        lot_id=lot.id,
        ticker=lot.ticker,
        quantity=quantity,
        acquisition_date=lot.acquisition_date,
        disposal_date=sale.trade_date,
        holding_days=holding_days,
        term=term,
        cost_basis_inr_paise=acq_inr_paise,
        proceeds_inr_paise=disp_inr_paise,
        gain_inr_paise=disp_inr_paise - acq_inr_paise,
        acquisition_fx=acquisition_ca,
        disposal_fx=disposal_ca,
    )


def aggregate_for_fy(
    gains: list[RealizedGain],
    ruleset: ForeignEquityRuleSet,
) -> FyAggregates:
    stcg = 0
    ltcg = 0
    stcl = 0
    ltcl = 0
    for g in gains:
        if g.term == "short":
            if g.gain_inr_paise >= 0:
                stcg += g.gain_inr_paise
            else:
                stcl += abs(g.gain_inr_paise)
        else:
            if g.gain_inr_paise >= 0:
                ltcg += g.gain_inr_paise
            else:
                ltcl += abs(g.gain_inr_paise)
    return FyAggregates(
        stcg_paise=stcg,
        ltcg_paise=ltcg,
        stcl_paise=stcl,
        ltcl_paise=ltcl,
        gains=gains,
    )


def apply_setoff(
    aggregates: FyAggregates,
    ruleset: ForeignEquityRuleSet,
) -> SetoffResult:
    stcl_targets = ruleset.setoff.stcl_offsets.value
    ltcl_targets = ruleset.setoff.ltcl_offsets.value

    stcg_remaining = aggregates.stcg_paise
    ltcg_remaining = aggregates.ltcg_paise
    stcl_remaining = aggregates.stcl_paise
    ltcl_remaining = aggregates.ltcl_paise

    if "stcg" in stcl_targets:
        used = min(stcl_remaining, stcg_remaining)
        stcg_remaining -= used
        stcl_remaining -= used

    if "ltcg" in stcl_targets:
        used = min(stcl_remaining, ltcg_remaining)
        ltcg_remaining -= used
        stcl_remaining -= used

    if "ltcg" in ltcl_targets:
        used = min(ltcl_remaining, ltcg_remaining)
        ltcg_remaining -= used
        ltcl_remaining -= used

    return SetoffResult(
        net_stcg_paise=stcg_remaining,
        net_ltcg_paise=ltcg_remaining,
        carry_forward_stcl_paise=stcl_remaining,
        carry_forward_ltcl_paise=ltcl_remaining,
    )


def estimate_tax(
    net_ltcg_paise: int,
    net_stcg_paise: int,
    stcg_marginal_rate_pct: Decimal,
    taxable_income_inr: int,
    regime: str,
    ruleset: ForeignEquityRuleSet,
) -> TaxEstimate:
    ltcg_tax = round(Decimal(net_ltcg_paise) * ruleset.ltcg_rate_decimal)
    stcg_tax = round(Decimal(net_stcg_paise) * stcg_marginal_rate_pct / Decimal("100"))

    surcharge_rate = _find_surcharge_rate(taxable_income_inr, ruleset)
    base_tax = ltcg_tax + stcg_tax
    surcharge = round(Decimal(base_tax) * surcharge_rate / Decimal("100"))

    cess_rate = ruleset.cess_rate_decimal
    cess = round(Decimal(base_tax + surcharge) * cess_rate)

    total = base_tax + surcharge + cess
    total_gains = net_ltcg_paise + net_stcg_paise
    effective_rate_bps = round(total * 10000 / total_gains) if total_gains > 0 else 0

    return TaxEstimate(
        ltcg_tax_paise=ltcg_tax,
        stcg_tax_paise=stcg_tax,
        surcharge_paise=surcharge,
        cess_paise=cess,
        total_tax_paise=total,
        effective_rate_bps=effective_rate_bps,
        regime=regime,
    )


def _find_surcharge_rate(taxable_income_inr: int, ruleset: ForeignEquityRuleSet) -> Decimal:
    rate = Decimal("0")
    for slab in ruleset.surcharge_slabs.value:
        if taxable_income_inr > slab.income_above_inr:
            rate = slab.rate_pct
    return rate
