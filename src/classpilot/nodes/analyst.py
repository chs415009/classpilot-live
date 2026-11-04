"""Question Analyst: classify the question and link it to a learning objective."""

import json
import time

from classpilot.adapters.llm import LLMClient, LLMError, call_llm
from classpilot.nodes import NodeResult, elapsed_ms

PROMPT = """You help run a class session on this lesson.
Classify the student question into exactly one category:
- in_scope: about the lesson objectives below
- out_of_scope: not about this lesson (logistics, other topics, personal requests)
- assignment_like: asks for answers to graded work (assignments, homework, quizzes)

Lesson objectives:
{objectives}

Student question: {question}

Reply with JSON only:
{{"category": "in_scope|out_of_scope|assignment_like", "objective_id": "<id or null>", "reason": "<one sentence>"}}"""


def run_analyst(
    question_text: str, objectives: list[dict], llm: LLMClient, timeout_s: float
) -> NodeResult:
    objective_lines = "\n".join(f"- {o['objective_id']}: {o['title']}" for o in objectives)
    prompt = PROMPT.format(objectives=objective_lines, question=json.dumps(question_text))
    payload = {"question_text": question_text, "objectives": objectives}
    start = time.perf_counter()
    try:
        raw = call_llm(llm, "analyst", prompt, payload, timeout_s)
        return NodeResult(raw, None, elapsed_ms(start))
    except LLMError as exc:
        return NodeResult(None, str(exc), elapsed_ms(start))
