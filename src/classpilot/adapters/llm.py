"""LLM client interface, a deterministic mock, and Cortex AI_COMPLETE.

Nodes call `call_llm(...)`, which enforces the timeout and turns every failure
into LLMError so the graph can fall back to escalation instead of hanging.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Protocol

from classpilot.settings import Settings
from classpilot.text import content_words, coverage, split_sentences


class LLMError(Exception):
    """Timeout, connection problem, or unusable output from the LLM."""


class LLMClient(Protocol):
    def complete_json(self, task: str, prompt: str, payload: dict) -> dict:
        """Return the model's JSON answer for one task (analyst, responder, guardian).

        `prompt` is the full text a real model would see. `payload` carries the
        same information as structured data, so the mock can work without parsing.
        """
        ...


def call_llm(client: LLMClient, task: str, prompt: str, payload: dict, timeout_s: float) -> dict:
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(client.complete_json, task, prompt, payload)
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

    def complete_json(self, task: str, prompt: str, payload: dict) -> dict:
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
        return handler(payload)

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


# ---------- Cortex ----------


# JSON schemas for AI_COMPLETE structured output, one per task. They mirror the
# pydantic models in contracts.py. Cortex ignores range keywords (minimum/maximum),
# so the final validator still checks ranges.
_STRING = {"type": "string"}
TASK_SCHEMAS = {
    "analyst": {
        "category": {"type": "string", "enum": ["in_scope", "out_of_scope", "assignment_like"]},
        "objective_id": {"type": ["string", "null"]},
        "reason": _STRING,
    },
    "responder": {
        "answer_text": _STRING,
        "citations": {"type": "array", "items": _STRING},
        "confidence": {"type": "number"},
        "grounded": {"type": "boolean"},
    },
    "guardian": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"claim": _STRING, "chunk_id": {"type": ["string", "null"]}},
                "required": ["claim", "chunk_id"],
                "additionalProperties": False,
            },
        },
        "reveals_graded_work": {"type": "boolean"},
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "reason": _STRING,
    },
}

COMPLETE_SQL = (
    "SELECT AI_COMPLETE("
    "model => %s, prompt => %s, "
    "model_parameters => {'temperature': 0, 'max_tokens': 1024}, "
    "response_format => PARSE_JSON(%s), "
    "return_error_details => TRUE)"
)


def response_format(task: str) -> dict:
    properties = TASK_SCHEMAS[task]
    return {
        "type": "json",
        "schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


class CortexLLM:
    """Calls Snowflake Cortex AI_COMPLETE through the Python connector.

    The model, prompt, and schema are bind variables. The query timeout cancels the
    call on the Snowflake side, so a timed-out call does not keep running.
    `payload` is only used by the mock and is ignored here.
    """

    def __init__(self, settings: Settings, connection=None):
        if not settings.llm.model:
            raise ValueError("Set llm.model in config/settings.yaml for BACKEND=cortex.")
        self.model = settings.llm.model
        self.timeout_s = settings.llm.timeout_seconds
        if connection is None:
            from classpilot.adapters.snowflake import shared_connection

            connection = shared_connection()
        self.connection = connection

    def complete_json(self, task: str, prompt: str, payload: dict) -> dict:
        params = (self.model, prompt, json.dumps(response_format(task)))
        cursor = self.connection.cursor()
        try:
            row = cursor.execute(
                COMPLETE_SQL, params, timeout=max(1, int(self.timeout_s))
            ).fetchone()
        except Exception as exc:
            raise LLMError(f"{task}: Cortex call failed: {exc}") from exc
        finally:
            cursor.close()

        result = json.loads(row[0]) if row and row[0] is not None else None
        if not isinstance(result, dict):
            raise LLMError(f"{task}: Cortex returned no result")
        if result.get("error"):
            raise LLMError(f"{task}: Cortex error: {result['error']}")
        value = result.get("value")
        if not isinstance(value, dict):
            raise LLMError(f"{task}: Cortex returned no JSON object")
        return value
