from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ltcg_agent.fx.sbi_ttbr import TTBRClient
from ltcg_agent.fx.store import RateStore
from ltcg_agent.fx.types import ConvertedAmount, MissingRateError, RateEntry

_SEED_CSV = Path(__file__).parent.parent / "ltcg_agent" / "fx" / "data" / "seed_rates.csv"


def _make_store(tmp_path: Path, entries: dict[date, int]) -> RateStore:
    store = RateStore(tmp_path / "rates.csv")
    for d, rate in entries.items():
        store._rates[d] = RateEntry(rate_date=d, ttbr_paise_per_usd=rate, source="test")
    return store


def _client(tmp_path: Path, entries: dict[date, int]) -> TTBRClient:
    return TTBRClient(store=_make_store(tmp_path, entries))


def test_get_rate_on_published_day_returns_exact_entry(tmp_path: Path) -> None:
    target = date(2024, 3, 15)
    client = _client(tmp_path, {target: 8350})
    entry = client.get_rate(target)
    assert entry.rate_date == target
    assert entry.ttbr_paise_per_usd == 8350


def test_get_rate_holiday_falls_back_to_last_published(tmp_path: Path) -> None:
    friday = date(2024, 3, 15)
    saturday = date(2024, 3, 16)
    client = _client(tmp_path, {friday: 8350})
    entry = client.get_rate(saturday)
    assert entry.rate_date == friday
    assert entry.ttbr_paise_per_usd == 8350


def test_get_rate_returns_published_date_not_requested_date(tmp_path: Path) -> None:
    friday = date(2024, 3, 15)
    sunday = date(2024, 3, 17)
    client = _client(tmp_path, {friday: 8350})
    entry = client.get_rate(sunday)
    assert entry.rate_date == friday
    assert entry.rate_date != sunday


def test_get_rate_within_max_lookback_window_succeeds(tmp_path: Path) -> None:
    published = date(2024, 3, 5)
    requested = date(2024, 3, 15)
    client = _client(tmp_path, {published: 8300})
    entry = client.get_rate(requested)
    assert entry.rate_date == published


def test_get_rate_beyond_max_lookback_raises_missing_rate_error(tmp_path: Path) -> None:
    published = date(2024, 3, 4)
    requested = date(2024, 3, 15)
    client = _client(tmp_path, {published: 8300})
    with pytest.raises(MissingRateError) as exc_info:
        client.get_rate(requested)
    assert exc_info.value.requested_date == requested


def test_get_rate_empty_store_raises_missing_rate_error(tmp_path: Path) -> None:
    client = _client(tmp_path, {})
    with pytest.raises(MissingRateError):
        client.get_rate(date(2024, 3, 15))


def test_missing_rate_error_message_includes_requested_date(tmp_path: Path) -> None:
    target = date(2024, 1, 1)
    client = _client(tmp_path, {})
    with pytest.raises(MissingRateError) as exc_info:
        client.get_rate(target)
    assert "2024-01-01" in str(exc_info.value)


def test_missing_rate_error_exposes_requested_date_attribute(tmp_path: Path) -> None:
    target = date(2024, 6, 1)
    client = _client(tmp_path, {})
    with pytest.raises(MissingRateError) as exc_info:
        client.get_rate(target)
    assert exc_info.value.requested_date == target


def test_convert_returns_converted_amount_instance(tmp_path: Path) -> None:
    target = date(2024, 3, 15)
    client = _client(tmp_path, {target: 8350})
    result = client.convert(10000, target)
    assert isinstance(result, ConvertedAmount)


def test_convert_formula_usd_cents_times_rate_divided_by_100(tmp_path: Path) -> None:
    target = date(2024, 3, 15)
    rate = 8350
    usd_cents = 15000
    client = _client(tmp_path, {target: rate})
    result = client.convert(usd_cents, target)
    assert result.inr_paise == round(usd_cents * rate / 100)


def test_convert_preserves_usd_cents_in_result(tmp_path: Path) -> None:
    target = date(2024, 3, 15)
    usd_cents = 13205
    client = _client(tmp_path, {target: 8350})
    result = client.convert(usd_cents, target)
    assert result.usd_cents == usd_cents


def test_convert_rate_equals_entry_ttbr(tmp_path: Path) -> None:
    target = date(2024, 3, 15)
    client = _client(tmp_path, {target: 8350})
    result = client.convert(10000, target)
    assert result.rate == 8350


def test_convert_source_propagated_from_rate_entry(tmp_path: Path) -> None:
    target = date(2024, 3, 15)
    client = _client(tmp_path, {target: 8350})
    result = client.convert(10000, target)
    assert result.source == "test"


def test_convert_rate_date_is_published_date_not_requested(tmp_path: Path) -> None:
    friday = date(2024, 3, 15)
    saturday = date(2024, 3, 16)
    client = _client(tmp_path, {friday: 8350})
    result = client.convert(10000, saturday)
    assert result.rate_date == friday
    assert result.rate_date != saturday


def test_convert_missing_rate_raises_missing_rate_error(tmp_path: Path) -> None:
    client = _client(tmp_path, {})
    with pytest.raises(MissingRateError):
        client.convert(10000, date(2024, 3, 15))


def test_store_seed_from_csv_loads_all_rows(tmp_path: Path) -> None:
    store = RateStore(tmp_path / "rates.csv")
    count = store.seed_from_csv(_SEED_CSV)
    assert count > 0
    assert len(store.all()) == count


def test_store_seed_from_csv_does_not_overwrite_existing(tmp_path: Path) -> None:
    d = date(2024, 1, 1)
    store = RateStore(tmp_path / "rates.csv")
    store._rates[d] = RateEntry(rate_date=d, ttbr_paise_per_usd=9999, source="existing")
    store.seed_from_csv(_SEED_CSV)
    assert store.get(d) is not None
    assert store.get(d).ttbr_paise_per_usd == 9999  # type: ignore[union-attr]


def test_store_seed_from_csv_returns_count_of_new_entries(tmp_path: Path) -> None:
    d = date(2024, 1, 1)
    store = RateStore(tmp_path / "rates.csv")
    store._rates[d] = RateEntry(rate_date=d, ttbr_paise_per_usd=9999, source="existing")
    count = store.seed_from_csv(_SEED_CSV)
    total = len(store.all())
    assert count == total - 1


def test_store_all_returns_entries_sorted_ascending_by_date(tmp_path: Path) -> None:
    store = _make_store(
        tmp_path,
        {
            date(2024, 3, 15): 8350,
            date(2024, 1, 1): 8300,
            date(2024, 6, 1): 8400,
        },
    )
    dates = [e.rate_date for e in store.all()]
    assert dates == sorted(dates)


def test_store_persists_entry_across_reload(tmp_path: Path) -> None:
    csv_path = tmp_path / "rates.csv"
    store1 = RateStore(csv_path)
    store1.set(RateEntry(rate_date=date(2024, 3, 15), ttbr_paise_per_usd=8350, source="test"))

    store2 = RateStore(csv_path)
    entry = store2.get(date(2024, 3, 15))
    assert entry is not None
    assert entry.ttbr_paise_per_usd == 8350
    assert entry.source == "test"


def test_store_set_overwrites_existing_date(tmp_path: Path) -> None:
    csv_path = tmp_path / "rates.csv"
    d = date(2024, 3, 15)
    store = RateStore(csv_path)
    store.set(RateEntry(rate_date=d, ttbr_paise_per_usd=8300, source="v1"))
    store.set(RateEntry(rate_date=d, ttbr_paise_per_usd=8350, source="v2"))
    assert store.get(d).ttbr_paise_per_usd == 8350  # type: ignore[union-attr]


def test_seed_csv_parses_without_error(tmp_path: Path) -> None:
    store = RateStore(tmp_path / "rates.csv")
    count = store.seed_from_csv(_SEED_CSV)
    assert count > 0


def test_seed_csv_covers_grandfathering_date(tmp_path: Path) -> None:
    store = RateStore(tmp_path / "rates.csv")
    store.seed_from_csv(_SEED_CSV)
    entry = store.last_before_or_on(date(2018, 1, 31))
    assert entry is not None
    assert entry.rate_date == date(2018, 1, 31)


def test_seed_csv_covers_fixture_acquisition_dates(tmp_path: Path) -> None:
    store = RateStore(tmp_path / "rates.csv")
    store.seed_from_csv(_SEED_CSV)
    for target in [date(2021, 1, 15), date(2021, 6, 20), date(2022, 3, 10)]:
        entry = store.last_before_or_on(target)
        assert entry is not None, f"No rate found for {target}"
