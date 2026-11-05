"""Guardian node: independent check of the answer against the cited chunks.

It sees only the question, the answer, and the cited chunks - not the analyst's
reasoning or the responder's confidence. It lists the answer's claims and which
chunk supports each one; `rules.check_guardian` makes the pass/fail call from that.
The instructions (the strict Stage 4 rules) are in `agents/signatures.py`.
"""

import time

from classpilot.adapters.llm import LLMClient, LLMError, call_llm
from classpilot.nodes import NodeResult, elapsed_ms


def run_guardian(
    question_text: str, answer_text: str, cited_chunks: list[dict], llm: LLMClient, timeout_s: float
) -> NodeResult:
    inputs = {
        "question_text": question_text,
        "answer_text": answer_text,
        "cited_chunks": cited_chunks,
    }
    start = time.perf_counter()
    try:
        raw = call_llm(llm, "guardian", inputs, timeout_s)
        return NodeResult(raw, None, elapsed_ms(start))
    except LLMError as exc:
        return NodeResult(None, str(exc), elapsed_ms(start))
