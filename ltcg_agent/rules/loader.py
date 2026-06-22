from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Generic, TypeVar

import yaml
from pydantic import BaseModel

_RULES_DIR = Path(__file__).parent / "configs"

T = TypeVar("T")


class RuleField(BaseModel, Generic[T]):
    value: T
    effective_from: date
    effective_to: date | None = None
    source: str

    model_config = {"frozen": True}


class TaxRuleSet(BaseModel):
    financial_year: str
    effective_from: date
    effective_to: date
    ltcg_rate_bps: RuleField[int]
    stcg_rate_bps: RuleField[int]
    ltcg_exemption_paise: RuleField[int]
    ltcg_holding_months: RuleField[int]
    grandfathering_enabled: RuleField[bool]
    min_harvest_loss_paise: RuleField[int]

    model_config = {"frozen": True}

    @property
    def ltcg_rate(self) -> float:
        return self.ltcg_rate_bps.value / 10000

    @property
    def stcg_rate(self) -> float:
        return self.stcg_rate_bps.value / 10000


class SurchargeSlab(BaseModel):
    income_above_inr: int
    income_upto_inr: int | None
    rate_pct: Decimal

    model_config = {"frozen": True}


class LtcgRules(BaseModel):
    section: RuleField[str]
    rate_pct: RuleField[Decimal]
    indexation: RuleField[bool]
    exemption_inr: RuleField[int]

    model_config = {"frozen": True}


class StcgRules(BaseModel):
    taxed_at: RuleField[str]
    section_111a_applies: RuleField[bool]

    model_config = {"frozen": True}


class SetOffRules(BaseModel):
    stcl_offsets: RuleField[list[str]]
    ltcl_offsets: RuleField[list[str]]
    carry_forward_years: RuleField[int]

    model_config = {"frozen": True}


class ForeignEquityRuleSet(BaseModel):
    financial_year: str
    asset_class: str
    effective_from: date
    effective_to: date
    asset_classification: RuleField[str]
    long_term_threshold_months: RuleField[int]
    ltcg: LtcgRules
    stcg: StcgRules
    setoff: SetOffRules
    surcharge_slabs: RuleField[list[SurchargeSlab]]
    cess_pct: RuleField[Decimal]
    wash_sale_rule: RuleField[bool]

    model_config = {"frozen": True}

    @property
    def ltcg_rate_decimal(self) -> Decimal:
        return self.ltcg.rate_pct.value / Decimal("100")

    @property
    def cess_rate_decimal(self) -> Decimal:
        return self.cess_pct.value / Decimal("100")


def load_rules(financial_year: str) -> TaxRuleSet:
    slug = financial_year.replace("-", "").replace("/", "")[2:]
    config_path = _RULES_DIR / f"fy{slug}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"No tax rule config for FY {financial_year} at {config_path}"
        )
    with config_path.open() as fh:
        raw = yaml.safe_load(fh)
    fields = raw["fields"]
    return TaxRuleSet(
        financial_year=raw["financial_year"],
        effective_from=date.fromisoformat(raw["effective_from"]),
        effective_to=date.fromisoformat(raw["effective_to"]),
        ltcg_rate_bps=_parse_field(fields["ltcg_rate_bps"], int),
        stcg_rate_bps=_parse_field(fields["stcg_rate_bps"], int),
        ltcg_exemption_paise=_parse_field(fields["ltcg_exemption_paise"], int),
        ltcg_holding_months=_parse_field(fields["ltcg_holding_months"], int),
        grandfathering_enabled=_parse_field(fields["grandfathering_enabled"], bool),
        min_harvest_loss_paise=_parse_field(fields["min_harvest_loss_paise"], int),
    )


def load_rules_for_date(d: date, asset_class: str = "us_listed_equity") -> ForeignEquityRuleSet:
    candidates = []
    for config_path in sorted(_RULES_DIR.glob("*.yaml")):
        with config_path.open() as fh:
            raw = yaml.safe_load(fh)
        if raw.get("asset_class") != asset_class:
            continue
        eff_from = date.fromisoformat(raw["effective_from"])
        eff_to = date.fromisoformat(raw["effective_to"])
        if eff_from <= d <= eff_to:
            candidates.append((config_path, raw))
    if not candidates:
        available = [p.name for p in _RULES_DIR.glob("*.yaml")]
        raise ValueError(
            f"No {asset_class} rule config covers {d}. "
            f"Available configs: {available}"
        )
    if len(candidates) > 1:
        names = [str(p) for p, _ in candidates]
        raise ValueError(
            f"Overlapping {asset_class} rule configs for {d}: {names}"
        )
    _, raw = candidates[0]
    return _parse_foreign_equity_ruleset(raw)


def _parse_foreign_equity_ruleset(raw: dict[str, Any]) -> ForeignEquityRuleSet:
    fields = raw["fields"]
    return ForeignEquityRuleSet(
        financial_year=raw["financial_year"],
        asset_class=raw["asset_class"],
        effective_from=date.fromisoformat(raw["effective_from"]),
        effective_to=date.fromisoformat(raw["effective_to"]),
        asset_classification=_parse_field(fields["asset_classification"], str),
        long_term_threshold_months=_parse_field(fields["long_term_threshold_months"], int),
        ltcg=LtcgRules(
            section=_parse_field(fields["ltcg"]["section"], str),
            rate_pct=_parse_field(fields["ltcg"]["rate_pct"], Decimal),
            indexation=_parse_field(fields["ltcg"]["indexation"], bool),
            exemption_inr=_parse_field(fields["ltcg"]["exemption_inr"], int),
        ),
        stcg=StcgRules(
            taxed_at=_parse_field(fields["stcg"]["taxed_at"], str),
            section_111a_applies=_parse_field(fields["stcg"]["section_111a_applies"], bool),
        ),
        setoff=SetOffRules(
            stcl_offsets=_parse_field(fields["setoff"]["stcl_offsets"], list),
            ltcl_offsets=_parse_field(fields["setoff"]["ltcl_offsets"], list),
            carry_forward_years=_parse_field(fields["setoff"]["carry_forward_years"], int),
        ),
        surcharge_slabs=_parse_surcharge_slabs(fields["surcharge_slabs"]),
        cess_pct=_parse_field(fields["cess_pct"], Decimal),
        wash_sale_rule=_parse_field(fields["wash_sale_rule"], bool),
    )


def _parse_surcharge_slabs(raw: dict[str, Any]) -> RuleField[list[SurchargeSlab]]:
    slabs = [
        SurchargeSlab(
            income_above_inr=int(s["income_above_inr"]),
            income_upto_inr=int(s["income_upto_inr"]) if s.get("income_upto_inr") is not None else None,
            rate_pct=Decimal(str(s["rate_pct"])),
        )
        for s in raw["value"]
    ]
    return RuleField(
        value=slabs,
        effective_from=date.fromisoformat(raw["effective_from"]),
        effective_to=date.fromisoformat(raw["effective_to"]) if raw.get("effective_to") else None,
        source=raw["source"],
    )


def _parse_field(raw: dict[str, Any], value_type: type) -> RuleField:  # type: ignore[type-arg]
    raw_value = raw["value"]
    if value_type is Decimal:
        value: Any = Decimal(str(raw_value))
    else:
        value = value_type(raw_value)
    return RuleField(
        value=value,
        effective_from=date.fromisoformat(raw["effective_from"]),
        effective_to=date.fromisoformat(raw["effective_to"]) if raw.get("effective_to") else None,
        source=raw["source"],
    )
