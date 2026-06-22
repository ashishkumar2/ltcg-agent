from __future__ import annotations

from datetime import date

from ltcg_agent.engine.lot_matcher import fifo_match
from ltcg_agent.models.money import Currency, Money
from ltcg_agent.models.portfolio import Portfolio, TaxLot, Trade
from ltcg_agent.models.provenance import FxProvenance
from ltcg_agent.models.tax import GainCategory, TaxEvent, TaxSummary
from ltcg_agent.rules.loader import TaxRuleSet

_GRANDFATHERING_DATE = date(2018, 1, 31)


class TaxEngine:
    def __init__(self, rules: TaxRuleSet) -> None:
        self._rules = rules

    def process_disposal(
        self,
        sale_trade: Trade,
        portfolio: Portfolio,
        sale_ttbr_paise: int,
        fmv_31jan2018_cents: dict[str, Money] | None = None,
    ) -> tuple[list[TaxEvent], Portfolio]:
        open_lots = portfolio.open_lots_for(sale_trade.ticker)
        consumed_lots, remaining_lots = fifo_match(open_lots, sale_trade.quantity)

        events: list[TaxEvent] = []
        for lot in consumed_lots:
            events.append(
                self._build_tax_event(
                    lot=lot,
                    sale_trade=sale_trade,
                    sale_ttbr_paise=sale_ttbr_paise,
                    fmv_31jan2018_cents=fmv_31jan2018_cents or {},
                )
            )

        new_lots = [l for l in portfolio.lots if l.ticker != sale_trade.ticker]
        new_lots.extend(remaining_lots)
        return events, Portfolio(lots=new_lots)

    def _build_tax_event(
        self,
        lot: TaxLot,
        sale_trade: Trade,
        sale_ttbr_paise: int,
        fmv_31jan2018_cents: dict[str, Money],
    ) -> TaxEvent:
        holding_days = (sale_trade.trade_date - lot.acquisition_date).days
        category = self._categorise(holding_days)

        acquisition_fx = FxProvenance.convert(
            usd_cents=lot.cost_per_share_cents.amount * lot.quantity,
            ttbr_paise_per_usd=lot.acquisition_ttbr_paise,
            rate_date=lot.acquisition_date,
        )
        total_cost_inr = Money(amount=acquisition_fx.inr_paise, currency=Currency.INR)

        grandfathered = False
        grandfathered_cost_inr: Money | None = None

        if (
            category == GainCategory.LTCG
            and lot.acquisition_date < _GRANDFATHERING_DATE
            and lot.ticker in fmv_31jan2018_cents
            and self._rules.grandfathering_enabled.value
        ):
            fmv_cents = fmv_31jan2018_cents[lot.ticker]
            fmv_fx = FxProvenance.convert(
                usd_cents=fmv_cents.amount * lot.quantity,
                ttbr_paise_per_usd=sale_ttbr_paise,
                rate_date=sale_trade.trade_date,
            )
            fmv_total_inr = Money(amount=fmv_fx.inr_paise, currency=Currency.INR)
            if fmv_total_inr.amount > total_cost_inr.amount:
                grandfathered_cost_inr = fmv_total_inr
                total_cost_inr = fmv_total_inr
                grandfathered = True

        gross_proceeds_cents = sale_trade.price_cents.amount * lot.quantity
        commission_cents = sale_trade.commission_cents.amount

        disposal_fx = FxProvenance.convert(
            usd_cents=gross_proceeds_cents - commission_cents,
            ttbr_paise_per_usd=sale_ttbr_paise,
            rate_date=sale_trade.trade_date,
        )
        net_proceeds_inr = Money(amount=disposal_fx.inr_paise, currency=Currency.INR)
        gain_inr = Money(
            amount=net_proceeds_inr.amount - total_cost_inr.amount,
            currency=Currency.INR,
        )

        return TaxEvent(
            ticker=lot.ticker,
            isin=lot.isin,
            lot_id=lot.id,
            acquisition_date=lot.acquisition_date,
            disposal_date=sale_trade.trade_date,
            quantity=lot.quantity,
            cost_basis_inr=total_cost_inr,
            sale_proceeds_inr=net_proceeds_inr,
            gain_inr=gain_inr,
            category=category,
            holding_days=holding_days,
            grandfathered=grandfathered,
            grandfathered_cost_inr=grandfathered_cost_inr,
            acquisition_fx=acquisition_fx,
            disposal_fx=disposal_fx,
        )

    def _categorise(self, holding_days: int) -> GainCategory:
        threshold_days = self._rules.ltcg_holding_months.value * 30
        return GainCategory.LTCG if holding_days > threshold_days else GainCategory.STCG

    def build_summary(
        self,
        financial_year: str,
        events: list[TaxEvent],
        harvest_candidates: list = [],
        escalation_flags: list = [],
    ) -> TaxSummary:
        return TaxSummary(
            financial_year=financial_year,
            events=events,
            harvest_candidates=harvest_candidates,
            escalation_flags=escalation_flags,
        )
