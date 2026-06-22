from __future__ import annotations

from datetime import date

from ltcg_agent.models.money import Currency, Money
from ltcg_agent.models.portfolio import Portfolio, TaxLot
from ltcg_agent.models.tax import GainCategory, HarvestCandidate
from ltcg_agent.rules.loader import TaxRuleSet


class HarvestingEngine:
    def __init__(self, rules: TaxRuleSet) -> None:
        self._rules = rules

    def find_candidates(
        self,
        portfolio: Portfolio,
        current_prices: dict[str, Money],
        current_ttbr_paise: int,
        as_of: date,
    ) -> list[HarvestCandidate]:
        candidates: list[HarvestCandidate] = []

        for lot in portfolio.lots:
            current_price = current_prices.get(lot.ticker)
            if current_price is None:
                continue

            current_price_inr = current_price.convert_to_inr(current_ttbr_paise)
            cost_inr = lot.cost_per_share_cents.convert_to_inr(lot.acquisition_ttbr_paise)

            if current_price_inr.amount >= cost_inr.amount:
                continue

            loss_per_share = Money(
                amount=cost_inr.amount - current_price_inr.amount,
                currency=Currency.INR,
            )
            total_loss = loss_per_share * lot.quantity

            if total_loss.amount < self._rules.min_harvest_loss_paise.value:
                continue

            holding_days = (as_of - lot.acquisition_date).days
            threshold = self._rules.ltcg_holding_months.value * 30
            category = GainCategory.LTCG if holding_days > threshold else GainCategory.STCG

            candidates.append(
                HarvestCandidate(
                    ticker=lot.ticker,
                    lot_id=lot.id,
                    acquisition_date=lot.acquisition_date,
                    quantity=lot.quantity,
                    current_price_cents=current_price,
                    current_ttbr_paise=current_ttbr_paise,
                    unrealised_loss_inr=total_loss,
                    category=category,
                )
            )

        return sorted(candidates, key=lambda c: -c.unrealised_loss_inr.amount)
