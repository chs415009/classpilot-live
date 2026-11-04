"""Guardian (3-agent mode): independent check of the answer against the cited chunks.

It sees only the question, the answer, and the cited chunks - not the analyst's
reasoning or the responder's confidence. It lists the answer's claims and which
chunk supports each one; `rules.check_guardian` makes the pass/fail call from that.
"""

import json
import time

from classpilot.adapters.llm import LLMClient, LLMError, call_llm
from classpilot.nodes import NodeResult, elapsed_ms

PROMPT = """You review an answer before a student sees it. Be strict: if you are not sure
a claim is supported, treat it as not supported.

1. List every factual claim in the answer. A sentence can hold more than one claim;
   list each one. For each claim, give the id of the cited chunk that directly states
   it, or null if no cited chunk states it.
   - Only the cited chunks count. Do not use your own knowledge.
   - A claim that is true in general but not stated in the cited chunks is not supported.
   - A chunk that only names a term, without explaining it, does not support an
     explanation of that term.
   - Sentences that only say what the chunks do not cover are not claims; leave them out.
2. Set reveals_graded_work to true if the answer gives finished code or SQL, or a
   complete solution to an assignment, homework or quiz-style task (for example the
   exact tests to add to a specific model).
3. verdict is "pass" only if every claim has a chunk id and reveals_graded_work is false.

Cited chunks:
{chunks}

Student question: {question}
Answer: {answer}

Reply with JSON only:
{{"claims": [{{"claim": "...", "chunk_id": "chunk-.. or null"}}], "reveals_graded_work": true|false, "verdict": "pass|fail", "reason": "<one sentence>"}}"""


def run_guardian(
    question_text: str, answer_text: str, cited_chunks: list[dict], llm: LLMClient, timeout_s: float
) -> NodeResult:
    chunk_lines = "\n".join(f"[{c['chunk_id']}] {c['text']}" for c in cited_chunks) or "(none)"
    prompt = PROMPT.format(
        chunks=chunk_lines, question=json.dumps(question_text), answer=json.dumps(answer_text)
    )
    payload = {
        "question_text": question_text,
        "answer_text": answer_text,
        "cited_chunks": cited_chunks,
    }
    start = time.perf_counter()
    try:
        raw = call_llm(llm, "guardian", prompt, payload, timeout_s)
        return NodeResult(raw, None, elapsed_ms(start))
    except LLMError as exc:
        return NodeResult(None, str(exc), elapsed_ms(start))
