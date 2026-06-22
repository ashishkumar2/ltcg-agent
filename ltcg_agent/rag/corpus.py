from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_SEED_PATH = Path(__file__).parent / "seed_corpus.jsonl"


@dataclass(frozen=True)
class CorpusChunk:
    chunk_id: str
    title: str
    section: str
    source_url: str
    retrieval_date: date
    text: str


def load_corpus(path: Path = _SEED_PATH) -> list[CorpusChunk]:
    chunks: list[CorpusChunk] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            chunks.append(
                CorpusChunk(
                    chunk_id=raw["chunk_id"],
                    title=raw["title"],
                    section=raw["section"],
                    source_url=raw["source_url"],
                    retrieval_date=date.fromisoformat(raw["retrieval_date"]),
                    text=raw["text"],
                )
            )
    return chunks
