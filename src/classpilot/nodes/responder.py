"""Grounded Responder node: answer only from the retrieved lesson chunks.
The instructions are in `agents/signatures.py`."""

import time

from classpilot.adapters.llm import LLMClient, LLMError, call_llm
from classpilot.adapters.retrieval import RetrievedChunk
from classpilot.nodes import NodeResult, elapsed_ms


def run_responder(
    question_text: str, retrieved: list[RetrievedChunk], llm: LLMClient, timeout_s: float
) -> NodeResult:
    inputs = {
        "question_text": question_text,
        "chunks": [{"chunk_id": c.chunk_id, "text": c.text, "score": c.score} for c in retrieved],
    }
    start = time.perf_counter()
    try:
        raw = call_llm(llm, "responder", inputs, timeout_s)
        return NodeResult(raw, None, elapsed_ms(start))
    except LLMError as exc:
        return NodeResult(None, str(exc), elapsed_ms(start))
