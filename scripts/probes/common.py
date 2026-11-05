"""Shared helpers for Stage 1 probes. Probes are not product code and are not imported
by src/ or tests/. Output goes to outputs/probes/ (gitignored)."""

import json
import os
import time
from pathlib import Path
from typing import Literal

import dspy

from classpilot.adapters.snowflake import load_env
from classpilot.settings import PROJECT_ROOT

OUT_DIR = PROJECT_ROOT / "outputs" / "probes"
OBJECTIVES = [
    {
        "objective_id": "objective-01",
        "title": "Explain the purpose of the Bronze, Silver and Gold layers",
    },
    {
        "objective_id": "objective-02",
        "title": "Explain why the Bronze layer keeps raw data unchanged",
    },
    {"objective_id": "objective-03", "title": "Build dbt models with ref() and add dbt tests"},
]
QUESTION = "Why do we keep raw data in Bronze if it has errors?"


class Analyst(dspy.Signature):
    """Classify a student question for this lesson: in_scope (about the lesson objectives),
    out_of_scope (not about this lesson), or assignment_like (asks for answers to graded
    work). Link it to a learning objective id if in scope."""

    objectives: str = dspy.InputField()
    question: str = dspy.InputField()
    category: Literal["in_scope", "out_of_scope", "assignment_like"] = dspy.OutputField()
    objective_id: str | None = dspy.OutputField()
    reason: str = dspy.OutputField(desc="one sentence")


def objectives_text() -> str:
    return "\n".join(f"- {o['objective_id']}: {o['title']}" for o in OBJECTIVES)


def model_name() -> str:
    load_env()
    return os.environ.get("PROBE_MODEL", "mistral-large3")


def save(name: str, data) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str))
    return path


def timed(fn, *args, **kwargs):
    start = time.perf_counter()
    try:
        return fn(*args, **kwargs), None, round(time.perf_counter() - start, 2)
    except Exception as exc:  # probes record every failure
        return (
            None,
            f"{type(exc).__module__}.{type(exc).__name__}: {exc}",
            round(time.perf_counter() - start, 2),
        )
