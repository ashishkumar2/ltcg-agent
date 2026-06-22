from __future__ import annotations

import csv
from pathlib import Path

from ltcg_agent.ingest.base import (
    ColumnMapping,
    MissingColumnError,
    ParseResult,
    UnknownColumnError,
    build_lot,
    build_sale_event,
    build_split_event,
    validate_columns,
)


class CsvStatementAdapter:
    def __init__(self, mapping: ColumnMapping) -> None:
        self._mapping = mapping

    def supports(self, source: Path) -> bool:
        return source.suffix.lower() == ".csv"

    def parse(self, source: Path) -> ParseResult:
        with source.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            headers = list(reader.fieldnames or [])
            validate_columns(headers, self._mapping)
            rows = list(reader)
        return _rows_to_parse_result(rows, self._mapping)


def _rows_to_parse_result(
    rows: list[dict[str, str]],
    mapping: ColumnMapping,
) -> ParseResult:
    lots = []
    sale_events = []
    split_events = []
    warnings: list[str] = []

    for lineno, row in enumerate(rows, start=2):
        action = row.get(mapping.action, "").strip().upper()
        expected_buy = mapping.buy_action_value.upper()
        expected_sell = mapping.sell_action_value.upper()
        expected_split = mapping.split_action_value.upper()
        try:
            if action == expected_buy:
                lots.append(build_lot(row, mapping))
            elif action == expected_sell:
                sale_events.append(build_sale_event(row, mapping))
            elif action == expected_split:
                split_events.append(build_split_event(row, mapping))
            else:
                warnings.append(
                    f"Row {lineno}: unknown action {action!r}, skipped"
                )
        except (ValueError, KeyError) as exc:
            warnings.append(f"Row {lineno}: {exc}")

    return ParseResult(
        lots=lots,
        sale_events=sale_events,
        split_events=split_events,
        warnings=warnings,
        source=mapping.source_name,
    )
