from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ltcg_agent.ingest.base import ColumnMapping, ParseResult
from ltcg_agent.ingest.csv_adapter import _rows_to_parse_result

_SYSTEM_PROMPT = (
    "You are a financial data extraction assistant. "
    "Extract all brokerage transactions from the provided statement.\n\n"
    "Output ONLY a JSON object with a single key 'rows' containing an array. "
    "Each element must have exactly these fields:\n"
    "  action      — one of: BUY, SELL, SPLIT\n"
    "  ticker      — stock symbol (e.g. AAPL)\n"
    "  date        — ISO-8601 string YYYY-MM-DD\n"
    "  quantity    — integer shares as a string (empty string for SPLIT rows)\n"
    "  price_usd   — price per share as decimal string without $ (empty for SPLIT rows)\n"
    "  name        — company name or empty string\n"
    "  exchange    — exchange name or empty string\n"
    "  lot_id      — lot identifier if present or empty string\n"
    "  split_ratio — ratio string like '10:1' for SPLIT rows, empty otherwise\n\n"
    "Rules:\n"
    "  - Include ONLY transactions. Skip summaries, fees, and metadata rows.\n"
    "  - Never guess or interpolate data absent from the statement.\n"
    "  - All dates in YYYY-MM-DD format.\n"
    "  - Prices are decimal strings (no currency symbols, no commas).\n"
    "  - Split ratios in N:M format (e.g. 10:1 means 10 new shares per 1 old share).\n"
    "  - Output valid JSON and nothing else — no markdown, no explanation."
)


class _LLMExtractedRows(BaseModel):
    rows: list[dict[str, str]]


class NormalizationError(ValueError):
    pass


class LLMStatementNormalizer:
    def __init__(self, client: Any, model: str = "gpt-4o") -> None:
        self._client = client
        self._model = model

    def normalize(self, raw_text: str, mapping: ColumnMapping) -> ParseResult:
        llm_rows = self._call_llm(raw_text)
        csv_rows = [_llm_row_to_csv_row(r, mapping) for r in llm_rows]
        return _rows_to_parse_result(csv_rows, mapping)

    def normalize_file(self, source: Path, mapping: ColumnMapping) -> ParseResult:
        return self.normalize(source.read_text(encoding="utf-8"), mapping)

    def _call_llm(self, raw_text: str) -> list[dict[str, str]]:
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": raw_text},
            ],
        )
        content = response.choices[0].message.content
        try:
            parsed = json.loads(content)
            validated = _LLMExtractedRows.model_validate(parsed)
            return validated.rows
        except (json.JSONDecodeError, ValidationError) as exc:
            raise NormalizationError(
                f"LLM returned malformed JSON that failed schema validation: {exc}"
            ) from exc


def _llm_row_to_csv_row(llm_row: dict[str, str], mapping: ColumnMapping) -> dict[str, str]:
    row: dict[str, str] = {
        mapping.ticker: llm_row.get("ticker", ""),
        mapping.action: llm_row.get("action", ""),
        mapping.date: llm_row.get("date", ""),
        mapping.quantity: llm_row.get("quantity", ""),
        mapping.price_usd: llm_row.get("price_usd", ""),
    }
    if mapping.name:
        row[mapping.name] = llm_row.get("name", "")
    if mapping.exchange:
        row[mapping.exchange] = llm_row.get("exchange", "")
    if mapping.lot_id:
        row[mapping.lot_id] = llm_row.get("lot_id", "")
    if mapping.split_ratio:
        row[mapping.split_ratio] = llm_row.get("split_ratio", "")
    return row
