"""LLM nodes. Each one returns raw JSON; the final validator decides what to do with it."""

import time
from dataclasses import dataclass


@dataclass
class NodeResult:
    raw: dict | None  # LLM JSON output, unchecked
    error: str | None  # set when the LLM call failed or timed out
    latency_ms: int


def elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
