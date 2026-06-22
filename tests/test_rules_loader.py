import pytest

from ltcg_agent.rules.loader import load_rules


def test_load_rules_fy2425_scalars():
    rules = load_rules("2024-25")
    assert rules.financial_year == "2024-25"
    assert rules.ltcg_rate_bps.value == 1250
    assert rules.stcg_rate_bps.value == 2000
    assert rules.ltcg_exemption_paise.value == 12_500_000
    assert rules.ltcg_holding_months.value == 24
    assert rules.grandfathering_enabled.value is True
    assert rules.min_harvest_loss_paise.value == 500_000


def test_load_rules_fy2425_sources_populated():
    rules = load_rules("2024-25")
    assert "Finance" in rules.ltcg_rate_bps.source
    assert rules.ltcg_rate_bps.effective_from is not None


def test_load_rules_fy2324_ltcg_rate():
    rules = load_rules("2023-24")
    assert rules.ltcg_rate_bps.value == 1000
    assert rules.ltcg_holding_months.value == 36


def test_load_rules_unknown_year_raises():
    with pytest.raises(FileNotFoundError):
        load_rules("1990-91")


def test_ltcg_rate_property():
    rules = load_rules("2024-25")
    assert abs(rules.ltcg_rate - 0.125) < 1e-9


def test_stcg_rate_property():
    rules = load_rules("2024-25")
    assert abs(rules.stcg_rate - 0.20) < 1e-9


def test_effective_dates_parsed():
    rules = load_rules("2024-25")
    from datetime import date
    assert rules.effective_from == date(2024, 4, 1)
    assert rules.effective_to == date(2025, 3, 31)
