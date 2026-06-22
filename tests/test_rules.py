from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ltcg_agent.rules.loader import (
    ForeignEquityRuleSet,
    RuleField,
    TaxRuleSet,
    load_rules,
    load_rules_for_date,
)

_MID_FY2526 = date(2025, 9, 15)
_MID_FY2425 = date(2024, 10, 1)


def _fy2526() -> ForeignEquityRuleSet:
    return load_rules_for_date(_MID_FY2526)


def test_load_rules_for_date_returns_fy2526_ruleset() -> None:
    rules = _fy2526()
    assert rules.financial_year == "2025-26"


def test_load_rules_for_date_returns_fy2526_at_boundary_start() -> None:
    rules = load_rules_for_date(date(2025, 4, 1))
    assert rules.financial_year == "2025-26"


def test_load_rules_for_date_returns_fy2526_at_boundary_end() -> None:
    rules = load_rules_for_date(date(2026, 3, 31))
    assert rules.financial_year == "2025-26"


def test_load_rules_for_date_raises_for_uncovered_date() -> None:
    with pytest.raises(ValueError, match="us_listed_equity"):
        load_rules_for_date(date(1999, 1, 1))


def test_load_rules_for_date_raises_with_date_in_message() -> None:
    target = date(1990, 6, 15)
    with pytest.raises(ValueError, match="1990-06-15"):
        load_rules_for_date(target)


def test_load_rules_for_date_asset_class_filter() -> None:
    with pytest.raises(ValueError):
        load_rules_for_date(_MID_FY2526, asset_class="nonexistent_class")


def test_asset_classification_value() -> None:
    assert _fy2526().asset_classification.value == "foreign/unlisted"


def test_asset_classification_has_source() -> None:
    assert _fy2526().asset_classification.source


def test_long_term_threshold_is_24_months() -> None:
    assert _fy2526().long_term_threshold_months.value == 24


def test_long_term_threshold_effective_from_is_finance_act_2024_date() -> None:
    assert _fy2526().long_term_threshold_months.effective_from == date(2024, 7, 23)


def test_ltcg_section_is_112() -> None:
    assert _fy2526().ltcg.section.value == "112"


def test_ltcg_section_source_mentions_112a_exclusion() -> None:
    assert "112A" in _fy2526().ltcg.section.source


def test_ltcg_rate_pct_is_12_point_5() -> None:
    assert _fy2526().ltcg.rate_pct.value == Decimal("12.5")


def test_ltcg_rate_pct_is_decimal_not_float() -> None:
    assert isinstance(_fy2526().ltcg.rate_pct.value, Decimal)


def test_ltcg_rate_pct_effective_from_is_finance_act_2024_date() -> None:
    assert _fy2526().ltcg.rate_pct.effective_from == date(2024, 7, 23)


def test_ltcg_indexation_is_false() -> None:
    assert _fy2526().ltcg.indexation.value is False


def test_ltcg_exemption_is_zero() -> None:
    assert _fy2526().ltcg.exemption_inr.value == 0


def test_ltcg_exemption_source_mentions_112a_contrast() -> None:
    source = _fy2526().ltcg.exemption_inr.source
    assert "112A" in source


def test_stcg_taxed_at_slab() -> None:
    assert _fy2526().stcg.taxed_at.value == "slab"


def test_stcg_section_111a_does_not_apply() -> None:
    assert _fy2526().stcg.section_111a_applies.value is False


def test_stcg_section_111a_source_explains_why() -> None:
    source = _fy2526().stcg.section_111a_applies.source
    assert "111A" in source


def test_stcl_offsets_include_stcg_and_ltcg() -> None:
    offsets = _fy2526().setoff.stcl_offsets.value
    assert "stcg" in offsets
    assert "ltcg" in offsets


def test_ltcl_offsets_only_ltcg() -> None:
    assert _fy2526().setoff.ltcl_offsets.value == ["ltcg"]


def test_ltcl_cannot_offset_stcg() -> None:
    assert "stcg" not in _fy2526().setoff.ltcl_offsets.value


def test_carry_forward_is_8_years() -> None:
    assert _fy2526().setoff.carry_forward_years.value == 8


def test_surcharge_slabs_present() -> None:
    assert len(_fy2526().surcharge_slabs.value) > 0


def test_surcharge_slabs_sorted_ascending_by_income() -> None:
    slabs = _fy2526().surcharge_slabs.value
    thresholds = [s.income_above_inr for s in slabs]
    assert thresholds == sorted(thresholds)


def test_surcharge_slabs_first_slab_starts_at_zero() -> None:
    assert _fy2526().surcharge_slabs.value[0].income_above_inr == 0


def test_surcharge_slabs_first_slab_zero_rate() -> None:
    assert _fy2526().surcharge_slabs.value[0].rate_pct == Decimal("0")


def test_surcharge_slabs_last_slab_has_no_upper_bound() -> None:
    last = _fy2526().surcharge_slabs.value[-1]
    assert last.income_upto_inr is None


def test_surcharge_slabs_rate_is_decimal() -> None:
    for slab in _fy2526().surcharge_slabs.value:
        assert isinstance(slab.rate_pct, Decimal)


def test_surcharge_source_mentions_gaar_or_cap() -> None:
    source = _fy2526().surcharge_slabs.source.lower()
    assert "112" in source


def test_cess_pct_is_4() -> None:
    assert _fy2526().cess_pct.value == Decimal("4")


def test_cess_pct_is_decimal_not_float() -> None:
    assert isinstance(_fy2526().cess_pct.value, Decimal)


def test_cess_effective_from_is_finance_act_2018() -> None:
    assert _fy2526().cess_pct.effective_from == date(2018, 4, 1)


def test_wash_sale_rule_is_false() -> None:
    assert _fy2526().wash_sale_rule.value is False


def test_wash_sale_source_mentions_gaar() -> None:
    assert "GAAR" in _fy2526().wash_sale_rule.source


def test_wash_sale_source_flags_rapid_rebuy() -> None:
    source = _fy2526().wash_sale_rule.source.lower()
    assert "rebuy" in source or "repurchase" in source


def test_all_rule_fields_have_non_empty_source() -> None:
    rules = _fy2526()
    fields: list[RuleField] = [  # type: ignore[type-arg]
        rules.asset_classification,
        rules.long_term_threshold_months,
        rules.ltcg.section,
        rules.ltcg.rate_pct,
        rules.ltcg.indexation,
        rules.ltcg.exemption_inr,
        rules.stcg.taxed_at,
        rules.stcg.section_111a_applies,
        rules.setoff.stcl_offsets,
        rules.setoff.ltcl_offsets,
        rules.setoff.carry_forward_years,
        rules.surcharge_slabs,
        rules.cess_pct,
        rules.wash_sale_rule,
    ]
    for field in fields:
        assert field.source.strip(), f"Empty source on {field}"


def test_all_rule_fields_have_effective_from() -> None:
    rules = _fy2526()
    fields: list[RuleField] = [  # type: ignore[type-arg]
        rules.asset_classification,
        rules.long_term_threshold_months,
        rules.ltcg.section,
        rules.ltcg.rate_pct,
        rules.ltcg.indexation,
        rules.ltcg.exemption_inr,
        rules.stcg.taxed_at,
        rules.stcg.section_111a_applies,
        rules.setoff.stcl_offsets,
        rules.setoff.ltcl_offsets,
        rules.setoff.carry_forward_years,
        rules.surcharge_slabs,
        rules.cess_pct,
        rules.wash_sale_rule,
    ]
    for field in fields:
        assert field.effective_from is not None, f"Missing effective_from on {field}"


def test_foreign_equity_ruleset_is_frozen() -> None:
    rules = _fy2526()
    with pytest.raises(Exception):
        rules.financial_year = "tampered"  # type: ignore[misc]


def test_ltcg_rate_decimal_property() -> None:
    rules = _fy2526()
    assert rules.ltcg_rate_decimal == Decimal("12.5") / Decimal("100")


def test_cess_rate_decimal_property() -> None:
    rules = _fy2526()
    assert rules.cess_rate_decimal == Decimal("4") / Decimal("100")


def test_old_load_rules_still_works_for_fy2425() -> None:
    rules = load_rules("2024-25")
    assert isinstance(rules, TaxRuleSet)
    assert rules.financial_year == "2024-25"


def test_old_load_rules_still_works_for_fy2324() -> None:
    rules = load_rules("2023-24")
    assert isinstance(rules, TaxRuleSet)
    assert rules.financial_year == "2023-24"


def test_old_load_rules_raises_for_missing_fy() -> None:
    with pytest.raises(FileNotFoundError):
        load_rules("1999-00")
