"""Grounded Responder: retrieve approved chunks and answer only from them."""

import json
import time
from dataclasses import dataclass

from classpilot.adapters.llm import LLMClient, LLMError, call_llm
from classpilot.adapters.retrieval import RetrievalError, RetrievedChunk, Retriever
from classpilot.nodes import NodeResult, elapsed_ms

PROMPT = """Answer the student question using ONLY the approved lesson chunks below.
Cite the chunk ids you used. If the chunks do not answer the question, say so and
give a low confidence. Then check your own answer: is every sentence supported by
the cited chunks? Report that as "grounded".

Chunks:
{chunks}

Student question: {question}

Reply with JSON only:
{{"answer_text": "...", "citations": ["chunk-.."], "confidence": 0.0-1.0, "grounded": true|false}}"""


@dataclass
class ResponderResult(NodeResult):
    retrieved: list[RetrievedChunk]
    retrieval_ms: int
    llm_called: bool = True


def run_responder(
    question_text: str, retriever: Retriever, llm: LLMClient, top_k: int, timeout_s: float
) -> ResponderResult:
    start = time.perf_counter()
    try:
        retrieved = retriever.search(question_text, top_k)
    except RetrievalError as exc:
        # No chunks means no grounded answer; the graph escalates like an LLM error.
        return ResponderResult(None, str(exc), 0, [], elapsed_ms(start), llm_called=False)
    retrieval_ms = elapsed_ms(start)

    chunk_lines = "\n".join(f"[{c.chunk_id}] {c.text}" for c in retrieved) or "(none)"
    prompt = PROMPT.format(chunks=chunk_lines, question=json.dumps(question_text))
    payload = {
        "question_text": question_text,
        "chunks": [{"chunk_id": c.chunk_id, "text": c.text, "score": c.score} for c in retrieved],
    }
    start = time.perf_counter()
    try:
        raw = call_llm(llm, "responder", prompt, payload, timeout_s)
        return ResponderResult(raw, None, elapsed_ms(start), retrieved, retrieval_ms)
    except LLMError as exc:
        return ResponderResult(None, str(exc), elapsed_ms(start), retrieved, retrieval_ms)
