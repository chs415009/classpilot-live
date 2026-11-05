"""Retrieval node: search the lesson's chunks (filtered by lesson_id). No LLM."""

import time
from dataclasses import dataclass

from classpilot.adapters.retrieval import RetrievalError, RetrievedChunk, Retriever
from classpilot.nodes import elapsed_ms


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    error: str | None
    latency_ms: int


def run_retrieval(retriever: Retriever, query: str, top_k: int, lesson_id: str) -> RetrievalResult:
    start = time.perf_counter()
    try:
        chunks = retriever.search(query, top_k, lesson_id)
    except RetrievalError as exc:
        return RetrievalResult([], str(exc), elapsed_ms(start))
    return RetrievalResult(chunks, None, elapsed_ms(start))
