"""Question Analyst node: classify the question and link it to a learning objective.
It sees the objectives and the chunks retrieved for the question (Stage 12).
The instructions are in `agents/signatures.py`."""

from classpilot.adapters.llm import LLMClient
from classpilot.nodes import NodeResult, RetryPolicy, call_node


def run_analyst(
    question_text: str,
    objectives: list[dict],
    llm: LLMClient,
    timeout_s: float,
    chunks: list[dict] | None = None,
    retry: RetryPolicy | None = None,
) -> NodeResult:
    inputs = {"question_text": question_text, "objectives": objectives, "chunks": chunks or []}
    return call_node(llm, "analyst", inputs, timeout_s, retry)
