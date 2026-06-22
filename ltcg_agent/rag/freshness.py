from __future__ import annotations

from dataclasses import dataclass
from datetime import date

LATEST_BUDGET_DATE = date(2025, 2, 1)


@dataclass(frozen=True)
class FreshnessWarning:
    corpus_max_date: date
    rules_effective_from: date
    latest_budget_date: date
    message: str


def check_freshness(
    corpus_max_date: date,
    rules_effective_from: date,
    as_of: date | None = None,
) -> FreshnessWarning | None:
    _ = as_of
    stale_corpus = corpus_max_date < LATEST_BUDGET_DATE
    stale_rules = rules_effective_from < LATEST_BUDGET_DATE
    if not stale_corpus and not stale_rules:
        return None

    parts: list[str] = []
    if stale_corpus:
        parts.append(
            f"corpus last indexed {corpus_max_date} predates Budget 2025-26 ({LATEST_BUDGET_DATE})"
        )
    if stale_rules:
        parts.append(
            f"rules config effective from {rules_effective_from} predates Budget 2025-26"
            f" ({LATEST_BUDGET_DATE})"
        )

    message = (
        "FRESHNESS WARNING — "
        + "; ".join(parts)
        + ". Tax rates and rules may have changed since the last Union Budget."
        " Verify all figures with a Chartered Accountant before filing."
    )
    return FreshnessWarning(
        corpus_max_date=corpus_max_date,
        rules_effective_from=rules_effective_from,
        latest_budget_date=LATEST_BUDGET_DATE,
        message=message,
    )
