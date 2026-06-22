from __future__ import annotations

from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from ltcg_agent.rag.corpus import CorpusChunk, load_corpus


class RagIndex:
    def __init__(self, store: FAISS, chunk_map: dict[str, CorpusChunk]) -> None:
        self._store = store
        self._chunk_map = chunk_map

    @classmethod
    def build(
        cls,
        chunks: list[CorpusChunk],
        embeddings: Embeddings,
    ) -> "RagIndex":
        documents = [_chunk_to_document(c) for c in chunks]
        store = FAISS.from_documents(documents, embeddings)
        chunk_map = {c.chunk_id: c for c in chunks}
        return cls(store, chunk_map)

    @classmethod
    def load_or_build(
        cls,
        index_path: Path,
        embeddings: Embeddings,
        chunks: list[CorpusChunk] | None = None,
    ) -> "RagIndex":
        corpus = chunks or load_corpus()
        chunk_map = {c.chunk_id: c for c in corpus}
        faiss_file = index_path / "index.faiss"
        if faiss_file.exists():
            store = FAISS.load_local(
                str(index_path),
                embeddings,
                allow_dangerous_deserialization=True,
            )
            return cls(store, chunk_map)
        documents = [_chunk_to_document(c) for c in corpus]
        store = FAISS.from_documents(documents, embeddings)
        index_path.mkdir(parents=True, exist_ok=True)
        store.save_local(str(index_path))
        return cls(store, chunk_map)

    @property
    def store(self) -> FAISS:
        return self._store

    def query(self, topic: str, k: int = 4) -> list[CorpusChunk]:
        docs = self._store.similarity_search(topic, k=k)
        result: list[CorpusChunk] = []
        for doc in docs:
            chunk_id = doc.metadata.get("chunk_id", "")
            if chunk_id in self._chunk_map:
                result.append(self._chunk_map[chunk_id])
        return result


def _chunk_to_document(chunk: CorpusChunk) -> Document:
    return Document(
        page_content=chunk.text,
        metadata={
            "chunk_id": chunk.chunk_id,
            "title": chunk.title,
            "section": chunk.section,
            "source_url": chunk.source_url,
            "retrieval_date": chunk.retrieval_date.isoformat(),
        },
    )
