from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel

from ltcg_agent.engine.gains import FyAggregates, SetoffResult, classify_term
from ltcg_agent.fx.types import ConvertedAmount, RateEntry
from ltcg_agent.models.portfolio import TaxLot
from ltcg_agent.rules.loader import ForeignEquityRuleSet

_DISCLAIMER = (
    "IMPORTANT — This output is an estimate only and does not constitute tax advice. "
    "All figures must be independently verified by a qualified Chartered Accountant "
    "before filing. Tax laws and exchange rates change; computations reflect rules "
    "and rates as understood at time of generation. Verify with a CA before filing."
)

_GAAR_NOTICE = (
    "India has no statutory wash-sale rule, but GAAR (General Anti-Avoidance Rule, "
    "IT Act s.95-s.102) may apply if the dominant purpose of a loss-crystallisation "
    "and immediate repurchase is to obtain a tax benefit with no genuine change in "
    "economic position. CBDT Circular 6/2016 also targets sham/circular transactions. "
    "Flag any repurchase of the same US equity within 30 calendar days of a "
    "loss-realising sale to your CA before claiming the deduction. "
    "This report does NOT recommend any immediate rebuy."
)


class PriceSource(Protocol):
    def current_price_cents(self, ticker: str) -> int: ...
    def current_fx(self) -> RateEntry: ...


class HarvestOpportunity(BaseModel):
    lot_id: str
    ticker: str
    quantity: int
    acquisition_date: date
    as_of_date: date
    holding_days: int
    term: Literal["short", "long"]
    cost_basis_inr_paise: int
    current_value_inr_paise: int
    unrealized_loss_inr_paise: int
    current_fx: ConvertedAmount
    stcg_offset_paise: int
    ltcg_offset_paise: int
    carry_forward_stcl_paise: int
    tax_saved_paise: int

    model_config = {"frozen": True}


class CrossoverOpportunity(BaseModel):
    lot_id: str
    ticker: str
    quantity: int
    acquisition_date: date
    as_of_date: date
    holding_days: int
    crossover_date: date
    days_to_crossover: int
    cost_basis_inr_paise: int
    current_value_inr_paise: int
    unrealized_gain_inr_paise: int
    current_fx: ConvertedAmount
    stcg_tax_today_paise: int
    ltcg_tax_at_crossover_paise: int
    tax_saving_paise: int

    model_config = {"frozen": True}


class CarryForwardNote(BaseModel):
    stcl_carry_paise: int
    ltcl_carry_paise: int
    total_carry_paise: int
    carry_forward_years: int
    filing_condition: str

    model_config = {"frozen": True}


class OpportunityReport(BaseModel):
    as_of: date
    financial_year: str
    harvest_opportunities: list[HarvestOpportunity]
    crossover_opportunities: list[CrossoverOpportunity]
    carry_forward: CarryForwardNote | None
    gaar_notice: str
    disclaimer: str

    model_config = {"frozen": True}


def find_harvest_opportunities(
    lots: list[TaxLot],
    fy_agg: FyAggregates,
    as_of: date,
    price_source: PriceSource,
    stcg_marginal_rate_pct: Decimal,
    taxable_income_inr: int,
    ruleset: ForeignEquityRuleSet,
) -> list[HarvestOpportunity]:
    fx_rate = price_source.current_fx()
    surcharge_rate = _find_surcharge_rate(taxable_income_inr, ruleset)
    cess_rate = ruleset.cess_rate_decimal
    ltcg_rate_pct = ruleset.ltcg.rate_pct.value

    opportunities: list[HarvestOpportunity] = []
    for lot in lots:
        current_cents = price_source.current_price_cents(lot.ticker) * lot.quantity
        current_inr = round(current_cents * fx_rate.ttbr_paise_per_usd / 100)
        cost_inr = round(lot.cost_per_share_cents.amount * lot.quantity * lot.acquisition_ttbr_paise / 100)

        if current_inr >= cost_inr:
            continue

        loss = cost_inr - current_inr
        term = classify_term(lot.acquisition_date, as_of, ruleset)

        stcg_avail = fy_agg.stcg_paise
        ltcg_avail = fy_agg.ltcg_paise
        stcl_targets = ruleset.setoff.stcl_offsets.value

        stcg_offset = 0
        ltcg_offset = 0
        remaining = loss

        if "stcg" in stcl_targets:
            stcg_offset = min(remaining, stcg_avail)
            remaining -= stcg_offset

        if "ltcg" in stcl_targets:
            ltcg_offset = min(remaining, ltcg_avail)
            remaining -= ltcg_offset

        carry = remaining

        stcg_saved = _tax_with_sur_cess(stcg_offset, stcg_marginal_rate_pct, surcharge_rate, cess_rate)
        ltcg_saved = _tax_with_sur_cess(ltcg_offset, ltcg_rate_pct, surcharge_rate, cess_rate)
        tax_saved = stcg_saved + ltcg_saved

        current_ca = ConvertedAmount(
            usd_cents=current_cents,
            inr_paise=current_inr,
            rate=fx_rate.ttbr_paise_per_usd,
            rate_date=fx_rate.rate_date,
            source=fx_rate.source,
        )

        opportunities.append(
            HarvestOpportunity(
                lot_id=lot.id,
                ticker=lot.ticker,
                quantity=lot.quantity,
                acquisition_date=lot.acquisition_date,
                as_of_date=as_of,
                holding_days=(as_of - lot.acquisition_date).days,
                term=term,
                cost_basis_inr_paise=cost_inr,
                current_value_inr_paise=current_inr,
                unrealized_loss_inr_paise=loss,
                current_fx=current_ca,
                stcg_offset_paise=stcg_offset,
                ltcg_offset_paise=ltcg_offset,
                carry_forward_stcl_paise=carry,
                tax_saved_paise=tax_saved,
            )
        )

    return sorted(opportunities, key=lambda o: -o.tax_saved_paise)


def find_crossover_opportunities(
    lots: list[TaxLot],
    as_of: date,
    price_source: PriceSource,
    stcg_marginal_rate_pct: Decimal,
    taxable_income_inr: int,
    ruleset: ForeignEquityRuleSet,
    window_days: int = 60,
) -> list[CrossoverOpportunity]:
    fx_rate = price_source.current_fx()
    surcharge_rate = _find_surcharge_rate(taxable_income_inr, ruleset)
    cess_rate = ruleset.cess_rate_decimal
    ltcg_rate_pct = ruleset.ltcg.rate_pct.value
    threshold_days = ruleset.long_term_threshold_months.value * 30

    opportunities: list[CrossoverOpportunity] = []
    for lot in lots:
        holding_days = (as_of - lot.acquisition_date).days
        if holding_days > threshold_days:
            continue

        crossover_date = lot.acquisition_date + timedelta(days=threshold_days + 1)
        days_to_crossover = (crossover_date - as_of).days
        if days_to_crossover <= 0 or days_to_crossover > window_days:
            continue

        current_cents = price_source.current_price_cents(lot.ticker) * lot.quantity
        current_inr = round(current_cents * fx_rate.ttbr_paise_per_usd / 100)
        cost_inr = round(lot.cost_per_share_cents.amount * lot.quantity * lot.acquisition_ttbr_paise / 100)

        unrealized_gain = current_inr - cost_inr
        if unrealized_gain <= 0:
            continue

        stcg_tax = _tax_with_sur_cess(unrealized_gain, stcg_marginal_rate_pct, surcharge_rate, cess_rate)
        ltcg_tax = _tax_with_sur_cess(unrealized_gain, ltcg_rate_pct, surcharge_rate, cess_rate)
        saving = stcg_tax - ltcg_tax

        current_ca = ConvertedAmount(
            usd_cents=current_cents,
            inr_paise=current_inr,
            rate=fx_rate.ttbr_paise_per_usd,
            rate_date=fx_rate.rate_date,
            source=fx_rate.source,
        )

        opportunities.append(
            CrossoverOpportunity(
                lot_id=lot.id,
                ticker=lot.ticker,
                quantity=lot.quantity,
                acquisition_date=lot.acquisition_date,
                as_of_date=as_of,
                holding_days=holding_days,
                crossover_date=crossover_date,
                days_to_crossover=days_to_crossover,
                cost_basis_inr_paise=cost_inr,
                current_value_inr_paise=current_inr,
                unrealized_gain_inr_paise=unrealized_gain,
                current_fx=current_ca,
                stcg_tax_today_paise=stcg_tax,
                ltcg_tax_at_crossover_paise=ltcg_tax,
                tax_saving_paise=saving,
            )
        )

    return sorted(opportunities, key=lambda o: -o.tax_saving_paise)


def find_carry_forward(
    setoff: SetoffResult,
    ruleset: ForeignEquityRuleSet,
) -> CarryForwardNote | None:
    total = setoff.carry_forward_stcl_paise + setoff.carry_forward_ltcl_paise
    if total == 0:
        return None
    return CarryForwardNote(
        stcl_carry_paise=setoff.carry_forward_stcl_paise,
        ltcl_carry_paise=setoff.carry_forward_ltcl_paise,
        total_carry_paise=total,
        carry_forward_years=ruleset.setoff.carry_forward_years.value,
        filing_condition=ruleset.setoff.carry_forward_years.source,
    )


def build_opportunity_report(
    lots: list[TaxLot],
    fy_agg: FyAggregates,
    setoff: SetoffResult,
    as_of: date,
    price_source: PriceSource,
    stcg_marginal_rate_pct: Decimal,
    taxable_income_inr: int,
    regime: str,
    ruleset: ForeignEquityRuleSet,
) -> OpportunityReport:
    harvest = find_harvest_opportunities(
        lots, fy_agg, as_of, price_source, stcg_marginal_rate_pct, taxable_income_inr, ruleset
    )
    crossover = find_crossover_opportunities(
        lots, as_of, price_source, stcg_marginal_rate_pct, taxable_income_inr, ruleset
    )
    carry = find_carry_forward(setoff, ruleset)

    return OpportunityReport(
        as_of=as_of,
        financial_year=ruleset.financial_year,
        harvest_opportunities=harvest,
        crossover_opportunities=crossover,
        carry_forward=carry,
        gaar_notice=_GAAR_NOTICE,
        disclaimer=_DISCLAIMER,
    )


def _tax_with_sur_cess(
    amount_paise: int,
    rate_pct: Decimal,
    surcharge_rate: Decimal,
    cess_rate: Decimal,
) -> int:
    base = round(Decimal(amount_paise) * rate_pct / Decimal("100"))
    sur = round(Decimal(base) * surcharge_rate / Decimal("100"))
    cess = round(Decimal(base + sur) * cess_rate)
    return base + sur + cess


def _find_surcharge_rate(taxable_income_inr: int, ruleset: ForeignEquityRuleSet) -> Decimal:
    rate = Decimal("0")
    for slab in ruleset.surcharge_slabs.value:
        if taxable_income_inr > slab.income_above_inr:
            rate = slab.rate_pct
    return rate
