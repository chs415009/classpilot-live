"""Question Analyst node: classify the question and link it to a learning objective.
The instructions are in `agents/signatures.py`."""

import time

from classpilot.adapters.llm import LLMClient, LLMError, call_llm
from classpilot.nodes import NodeResult, elapsed_ms


def run_analyst(
    question_text: str, objectives: list[dict], llm: LLMClient, timeout_s: float
) -> NodeResult:
    inputs = {"question_text": question_text, "objectives": objectives}
    start = time.perf_counter()
    try:
        raw = call_llm(llm, "analyst", inputs, timeout_s)
        return NodeResult(raw, None, elapsed_ms(start))
    except LLMError as exc:
        return NodeResult(None, str(exc), elapsed_ms(start))
