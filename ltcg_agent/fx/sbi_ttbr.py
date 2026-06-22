from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from ltcg_agent.fx.store import RateStore
from ltcg_agent.fx.types import ConvertedAmount, MissingRateError, RateEntry

_SEED_CSV = Path(__file__).parent / "data" / "seed_rates.csv"
_MAX_LOOKBACK_DAYS = 10
_DEFAULT_STORE_PATH = Path.home() / ".ltcg_agent" / "ttbr_rates.csv"
_SBI_TTBR_URL = "https://www.sbi.co.in/web/sbi-in-the-news/forex-rates"
_TTBR_PATTERN = re.compile(r"TT\s+Buying.*?(\d{2,3}\.\d{2})", re.IGNORECASE | re.DOTALL)


class TTBRClient:
    def __init__(self, store: RateStore | None = None) -> None:
        if store is not None:
            self._store = store
        else:
            self._store = RateStore(_DEFAULT_STORE_PATH)
            if not _DEFAULT_STORE_PATH.exists() and _SEED_CSV.exists():
                self._store.seed_from_csv(_SEED_CSV)

    def get_rate(self, for_date: date) -> RateEntry:
        entry = self._store.last_before_or_on(for_date, _MAX_LOOKBACK_DAYS)
        if entry is None:
            raise MissingRateError(for_date, _MAX_LOOKBACK_DAYS)
        return entry

    def convert(self, usd_cents: int, for_date: date) -> ConvertedAmount:
        entry = self.get_rate(for_date)
        inr_paise = round(usd_cents * entry.ttbr_paise_per_usd / 100)
        return ConvertedAmount(
            usd_cents=usd_cents,
            inr_paise=inr_paise,
            rate=entry.ttbr_paise_per_usd,
            rate_date=entry.rate_date,
            source=entry.source,
        )

    def refresh(self, from_date: date, to_date: date) -> int:
        stored = 0
        current = from_date
        while current <= to_date:
            if self._store.get(current) is None:
                try:
                    rate_paise = _scrape_sbi_ttbr(current)
                    self._store.set(
                        RateEntry(
                            rate_date=current,
                            ttbr_paise_per_usd=rate_paise,
                            source="sbi_web",
                        )
                    )
                    stored += 1
                except Exception:
                    pass
            current += timedelta(days=1)
        return stored


def _scrape_sbi_ttbr(for_date: date) -> int:
    import httpx

    with httpx.Client(timeout=10.0) as client:
        response = client.get(
            _SBI_TTBR_URL,
            params={"date": for_date.strftime("%d/%m/%Y")},
        )
        response.raise_for_status()

    match = _TTBR_PATTERN.search(response.text)
    if not match:
        raise ValueError(f"Could not parse TTBR from SBI page for {for_date}")
    return round(float(match.group(1)) * 100)
