"""Guardian node: independent check of the answer against the cited chunks.

It sees only the question, the answer, and the cited chunks - not the analyst's
reasoning or the responder's confidence. It lists the answer's claims and which
chunk supports each one; `rules.check_guardian` makes the pass/fail call from that.
The instructions (the strict Stage 4 rules) are in `agents/signatures.py`.
"""

from classpilot.adapters.llm import LLMClient
from classpilot.nodes import NodeResult, RetryPolicy, call_node


def run_guardian(
    question_text: str,
    answer_text: str,
    cited_chunks: list[dict],
    llm: LLMClient,
    timeout_s: float,
    retry: RetryPolicy | None = None,
) -> NodeResult:
    inputs = {
        "question_text": question_text,
        "answer_text": answer_text,
        "cited_chunks": cited_chunks,
    }
    return call_node(llm, "guardian", inputs, timeout_s, retry)
