from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI

from ltcg_agent.rag.index import RagIndex

_SYSTEM_PROMPT = (
    "You are an Indian tax expert specialising in capital gains from foreign equity holdings. "
    "Answer ONLY from the provided Income Tax Act context. "
    "If the context does not contain enough information, say so explicitly. "
    "NEVER hallucinate section numbers, rates, or exemption limits. "
    "Always cite the section of the IT Act or CBDT circular you drew from."
)

_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM_PROMPT),
        ("human", "Context:\n{context}\n\nQuestion: {question}"),
    ]
)


class RagRetriever:
    def __init__(self, index: RagIndex, model: str, temperature: float = 0.0) -> None:
        self._index = index
        self._llm = ChatOpenAI(model=model, temperature=temperature)

    def explain(self, question: str, top_k: int = 5) -> tuple[str, list[str]]:
        retriever = self._index.store.as_retriever(search_kwargs={"k": top_k})
        source_docs = retriever.invoke(question)
        sources = [doc.metadata.get("source_url", doc.metadata.get("source", "unknown")) for doc in source_docs]

        def _format_docs(docs: list) -> str:
            return "\n\n".join(doc.page_content for doc in docs)

        chain = (
            {"context": retriever | _format_docs, "question": RunnablePassthrough()}
            | _PROMPT
            | self._llm
            | StrOutputParser()
        )
        answer = chain.invoke(question)
        return answer, sources
