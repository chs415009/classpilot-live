"""Trace v2 output: build helpers and JSONL writers for trace records and the decision log.

Record shapes are in `contracts/trace.py`. Each live decision appends its trace
records to outputs/traces.jsonl (later loaded into Bronze by the pipeline) and one
entry to outputs/decision_log.jsonl (read by the post-class report).
"""

import hashlib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from classpilot.contracts import Decision
from classpilot.contracts.trace import (
    DecisionLogEntry,
    LLMCallRecord,
    NodeRecord,
    RetrievalRecord,
    RunRecord,
    TraceRecord,
)
from classpilot.settings import PROJECT_ROOT

DEFAULT_TRACE_PATH = PROJECT_ROOT / "outputs" / "traces.jsonl"
DEFAULT_DECISION_LOG_PATH = PROJECT_ROOT / "outputs" / "decision_log.jsonl"


def new_decision_id() -> str:
    return f"dec-{uuid.uuid4().hex[:8]}"


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_ms() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def short_hash(text: str) -> str:
    """Stable id for a text (query, claim) without putting the text in the trace."""
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()[:16]


@dataclass
class RunOutput:
    """What one live path call returns: the decision, its trace records, its log entry."""

    decision: Decision
    records: list[TraceRecord]
    log: DecisionLogEntry

    def of_type(self, model: type) -> list:
        return [r for r in self.records if isinstance(r, model)]

    @property
    def run(self) -> RunRecord:
        return self.of_type(RunRecord)[0]

    @property
    def nodes_run(self) -> list[str]:
        return [n.node_name for n in self.of_type(NodeRecord) if n.status != "skip"]

    @property
    def llm_calls(self) -> int:
        return len(self.of_type(LLMCallRecord))

    @property
    def retrieved_chunk_ids(self) -> list[str]:
        return [r.chunk_id for r in self.of_type(RetrievalRecord)]

    @property
    def latency_ms(self) -> dict[str, int]:
        nodes = {n.node_name: n.latency_ms for n in self.of_type(NodeRecord) if n.status != "skip"}
        return {**nodes, "total": self.run.latency_ms}

    def summary(self) -> dict:
        """Short view for the CLI and eval rows."""
        return {
            "nodes_run": self.nodes_run,
            "llm_calls": self.llm_calls,
            "retrieved_chunk_ids": self.retrieved_chunk_ids,
            "latency_ms": self.latency_ms,
        }


def write_jsonl(items: Iterable[BaseModel], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for item in items:
            f.write(item.model_dump_json() + "\n")


def write_run(
    output: RunOutput,
    trace_path: Path = DEFAULT_TRACE_PATH,
    log_path: Path = DEFAULT_DECISION_LOG_PATH,
) -> None:
    write_jsonl(output.records, trace_path)
    write_jsonl([output.log], log_path)
