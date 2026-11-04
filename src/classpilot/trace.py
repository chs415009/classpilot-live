"""Write one JSONL trace record per decision (later loaded into Bronze by the pipeline)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from classpilot.contracts import Trace
from classpilot.settings import PROJECT_ROOT

DEFAULT_TRACE_PATH = PROJECT_ROOT / "outputs" / "traces.jsonl"


def new_decision_id() -> str:
    return f"dec-{uuid.uuid4().hex[:8]}"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_trace(trace: Trace, path: Path = DEFAULT_TRACE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(trace.model_dump_json() + "\n")
