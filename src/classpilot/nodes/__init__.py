"""LLM nodes. Each one returns raw JSON; the final validator decides what to do with it."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from classpilot.adapters.llm import LLMClient, LLMError, MalformedReplyError, call_llm


@dataclass
class NodeResult:
    raw: dict | None  # LLM JSON output, unchecked
    error: str | None  # set when the LLM call failed or timed out
    latency_ms: int
    retries: int = 0  # calls repeated after a malformed reply (Stage 12)


@dataclass
class RetryPolicy:
    """Stage 12: a malformed reply (the model answered, but the output fields could not
    be parsed) is asked again up to `max_retries` times, only while `seconds_left()` is
    at least `min_seconds`; the repeat's timeout is capped by what is left. Timeouts and
    other errors are never repeated."""

    max_retries: int
    min_seconds: float
    seconds_left: Callable[[], float]


def elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def call_node(
    llm: LLMClient,
    task: str,
    inputs: dict,
    timeout_s: float,
    retry: RetryPolicy | None = None,
) -> NodeResult:
    start, retries = time.perf_counter(), 0
    while True:
        try:
            return NodeResult(
                call_llm(llm, task, inputs, timeout_s), None, elapsed_ms(start), retries
            )
        except MalformedReplyError as exc:
            left = retry.seconds_left() if retry else 0.0
            if retry is None or retries >= retry.max_retries or left < retry.min_seconds:
                return NodeResult(None, str(exc), elapsed_ms(start), retries)
            retries += 1
            timeout_s = min(timeout_s, left)
        except LLMError as exc:
            return NodeResult(None, str(exc), elapsed_ms(start), retries)
