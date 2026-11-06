"""LLM client interface, the timeout wrapper, and a deterministic mock.

Nodes call `call_llm(...)`, which enforces the timeout and turns every failure
into LLMError so the graph can fall back to escalation instead of hanging. The real
client is `agents.program.DSPyAgents` on the Route B engine (`adapters/cortex_engine.py`).
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Protocol

from classpilot.text import content_words, coverage, split_sentences


class LLMError(Exception):
    """Timeout, connection problem, or unusable output from the LLM."""


class MalformedReplyError(LLMError):
    """The model replied, but the reply could not be parsed into the output fields."""


class LLMClient(Protocol):
    def complete(self, task: str, inputs: dict) -> dict:
        """Return the outputs of one task (analyst, responder, guardian) as a dict.

        `inputs` is structured data (question text, objectives, chunks); the DSPy client
        formats it into the signature's fields, the mock reads it directly.
        """
        ...


def call_llm(client: LLMClient, task: str, inputs: dict, timeout_s: float) -> dict:
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(client.complete, task, inputs)
    try:
        result = future.result(timeout=timeout_s)
    except FutureTimeout:
        raise LLMError(f"{task} timed out after {timeout_s}s") from None
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f"{task} failed: {exc}") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    if not isinstance(result, dict):
        raise LLMError(f"{task} returned {type(result).__name__}, expected a JSON object")
    return result


# ---------- mock ----------

ASSIGNMENT_MARKERS = {"assignment", "homework", "hw", "graded", "solution"}
CODE_PATTERN = re.compile(r"```|\{\{|\bselect\b.+\bfrom\b", re.IGNORECASE)


class MockLLM:
    """Deterministic stand-in for Cortex, built from simple word-overlap rules.

    It also simulates one known LLM failure mode on purpose: when the approved
    chunks only partly cover a question, the mock responder "fills the gap" with
    an unsupported sentence, reports high confidence, and its self-check still
    says grounded. This gives the Guardian something real to catch in the demo.
    Mock results show how the flow behaves, not how often a real model fails.
    """

    def __init__(
        self,
        delays: dict[str, float] | None = None,
        errors: dict[str, str] | None = None,
        bad_output: set[str] | None = None,
    ):
        self.delays = delays or {}
        self.errors = errors or {}
        self.bad_output = bad_output or set()

    def complete(self, task: str, inputs: dict) -> dict:
        if task in self.delays:
            time.sleep(self.delays[task])
        if task in self.errors:
            raise LLMError(self.errors[task])
        if task in self.bad_output:
            return {"unexpected": "not the requested schema"}
        handler = {
            "analyst": self._analyst,
            "responder": self._responder,
            "guardian": self._guardian,
        }[task]
        return handler(inputs)

    @staticmethod
    def _analyst(payload: dict) -> dict:
        words = set(content_words(payload["question_text"]))
        if words & ASSIGNMENT_MARKERS:
            return {
                "category": "assignment_like",
                "objective_id": None,
                "reason": "Mentions graded work.",
            }
        best_id, best_hits = None, 0
        for objective in payload["objectives"]:
            keywords = {w for k in objective["keywords"] for w in content_words(k)}
            hits = len(words & keywords)
            if hits > best_hits:
                best_id, best_hits = objective["objective_id"], hits
        if best_id is None:
            return {
                "category": "out_of_scope",
                "objective_id": None,
                "reason": "No link to any lesson objective.",
            }
        return {
            "category": "in_scope",
            "objective_id": best_id,
            "reason": f"Matches {best_hits} keyword(s) of {best_id}.",
        }

    @staticmethod
    def _responder(payload: dict) -> dict:
        question = payload["question_text"]
        chunks = payload["chunks"]
        if not chunks:
            return {
                "answer_text": "The approved material does not cover this.",
                "citations": [],
                "confidence": 0.1,
                "grounded": True,
            }

        sentences = [
            (coverage(question, sentence), chunk["chunk_id"], sentence)
            for chunk in chunks
            for sentence in split_sentences(chunk["text"])
        ]
        sentences.sort(key=lambda item: item[0], reverse=True)
        picked = [item for item in sentences[:2] if item[0] > 0] or sentences[:1]
        answer = " ".join(sentence for _, _, sentence in picked)
        citations = sorted({chunk_id for _, chunk_id, _ in picked})

        all_text = " ".join(chunk["text"] for chunk in chunks)
        question_coverage = coverage(question, all_text)
        if question_coverage >= 0.6:
            confidence = min(0.95, 0.6 + 0.4 * question_coverage)
        elif question_coverage >= 0.3:
            # Simulated failure mode: invent a sentence about the uncovered words.
            missing = sorted(set(content_words(question)) - set(content_words(all_text)))
            answer += (
                f" For {' and '.join(missing)}, the same approach works without any extra setup."
            )
            confidence = 0.85
        else:
            confidence = question_coverage

        return {
            "answer_text": answer,
            "citations": citations,
            "confidence": round(confidence, 2),
            "grounded": True,
        }

    @staticmethod
    def _guardian(payload: dict) -> dict:
        # One claim per sentence, supported by the first cited chunk that covers it.
        answer = payload["answer_text"]
        claims = []
        for sentence in split_sentences(answer):
            support = next(
                (
                    c["chunk_id"]
                    for c in payload["cited_chunks"]
                    if coverage(sentence, c["text"]) >= 0.6
                ),
                None,
            )
            claims.append({"claim": sentence, "chunk_id": support})
        reveals = bool(CODE_PATTERN.search(answer))
        unsupported = [c["claim"] for c in claims if c["chunk_id"] is None]
        if reveals:
            reason = "Answer contains code that may solve graded work."
        elif unsupported:
            reason = f"Not supported by cited chunks: {unsupported[0]!r}"
        else:
            reason = "Every sentence is supported by the cited chunks."
        return {
            "claims": claims,
            "reveals_graded_work": reveals,
            "verdict": "fail" if reveals or unsupported or not claims else "pass",
            "reason": reason,
        }
