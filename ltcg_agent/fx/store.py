from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from ltcg_agent.fx.types import RateEntry


class RateStore:
    def __init__(self, csv_path: Path) -> None:
        self._csv_path = csv_path
        self._rates: dict[date, RateEntry] = {}
        if csv_path.exists():
            self._load()

    def _load(self) -> None:
        with open(self._csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                entry = RateEntry(
                    rate_date=date.fromisoformat(row["rate_date"]),
                    ttbr_paise_per_usd=int(row["ttbr_paise_per_usd"]),
                    source=row["source"],
                )
                self._rates[entry.rate_date] = entry

    def _save(self) -> None:
        self._csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["rate_date", "ttbr_paise_per_usd", "source"]
            )
            writer.writeheader()
            for entry in sorted(self._rates.values(), key=lambda e: e.rate_date):
                writer.writerow(
                    {
                        "rate_date": entry.rate_date.isoformat(),
                        "ttbr_paise_per_usd": entry.ttbr_paise_per_usd,
                        "source": entry.source,
                    }
                )

    def get(self, for_date: date) -> RateEntry | None:
        return self._rates.get(for_date)

    def set(self, entry: RateEntry) -> None:
        self._rates[entry.rate_date] = entry
        self._save()

    def last_before_or_on(self, for_date: date, max_lookback: int = 10) -> RateEntry | None:
        for delta in range(max_lookback + 1):
            entry = self._rates.get(for_date - timedelta(days=delta))
            if entry is not None:
                return entry
        return None

    def seed_from_csv(self, path: Path) -> int:
        seeded = 0
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                entry = RateEntry(
                    rate_date=date.fromisoformat(row["rate_date"]),
                    ttbr_paise_per_usd=int(row["ttbr_paise_per_usd"]),
                    source=row["source"],
                )
                if entry.rate_date not in self._rates:
                    self._rates[entry.rate_date] = entry
                    seeded += 1
        if seeded:
            self._save()
        return seeded

    def all(self) -> list[RateEntry]:
        return sorted(self._rates.values(), key=lambda e: e.rate_date)
