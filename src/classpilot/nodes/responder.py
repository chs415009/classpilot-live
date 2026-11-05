"""Grounded Responder: answer only from the retrieved lesson chunks."""

import json
import time

from classpilot.adapters.llm import LLMClient, LLMError, call_llm
from classpilot.adapters.retrieval import RetrievedChunk
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


def run_responder(
    question_text: str, retrieved: list[RetrievedChunk], llm: LLMClient, timeout_s: float
) -> NodeResult:
    chunk_lines = "\n".join(f"[{c.chunk_id}] {c.text}" for c in retrieved) or "(none)"
    prompt = PROMPT.format(chunks=chunk_lines, question=json.dumps(question_text))
    payload = {
        "question_text": question_text,
        "chunks": [{"chunk_id": c.chunk_id, "text": c.text, "score": c.score} for c in retrieved],
    }
    start = time.perf_counter()
    try:
        raw = call_llm(llm, "responder", prompt, payload, timeout_s)
        return NodeResult(raw, None, elapsed_ms(start))
    except LLMError as exc:
        return NodeResult(None, str(exc), elapsed_ms(start))
