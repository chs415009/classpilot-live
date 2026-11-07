"""Grounded Responder node: answer only from the retrieved lesson chunks.
The instructions are in `agents/signatures.py`."""

from classpilot.adapters.llm import LLMClient
from classpilot.adapters.retrieval import RetrievedChunk
from classpilot.nodes import NodeResult, RetryPolicy, call_node


def run_responder(
    question_text: str,
    retrieved: list[RetrievedChunk],
    llm: LLMClient,
    timeout_s: float,
    retry: RetryPolicy | None = None,
) -> NodeResult:
    inputs = {
        "question_text": question_text,
        "chunks": [{"chunk_id": c.chunk_id, "text": c.text, "score": c.score} for c in retrieved],
    }
    return call_node(llm, "responder", inputs, timeout_s, retry)
