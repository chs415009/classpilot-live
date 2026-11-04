"""Pydantic models for the data contracts in CLAUDE.md.

Field names match the team README so they line up with the front end and the
data pipeline. Unused fields are None (serialized as null).
"""

from typing import Literal

from pydantic import BaseModel, Field

Path = Literal["poll", "question"]
Action = Literal["continue", "reteach", "answer", "escalate"]
EscalationReason = Literal[
    "out_of_scope",
    "assignment_like",
    "low_confidence",
    "unsupported",
    "llm_error",
    "no_mapping",
    "remediation_limit",
]
Backend = Literal["mock", "cortex"]


# ---------- inputs ----------


class PollEvidence(BaseModel):
    session_id: str
    objective_id: str
    question_id: str
    snapshot_time: str
    connected_students: int
    answers_received: int
    option_counts: dict[str, int]
    correct_option: str
    remediations_used: dict[str, int] = Field(default_factory=dict)


class StudentQuestion(BaseModel):
    session_id: str
    event_id: str
    anonymous_learner_id: str
    objective_id: str | None = None
    question_text: str
    submitted_at: str


# ---------- outputs ----------


class Decision(BaseModel):
    decision_id: str
    session_id: str
    path: Path
    action: Action
    remediation_id: str | None = None
    answer_text: str | None = None
    citations: list[str] | None = None
    escalation_reason: EscalationReason | None = None
    confidence: float | None = None


class Trace(BaseModel):
    decision_id: str
    input_ref: str
    agent_mode: int | None  # None for the poll path (no agents involved)
    nodes_run: list[str]
    llm_calls: int
    retrieved_chunk_ids: list[str]
    latency_ms: dict[str, int]
    backend: Backend
    action: Action
    created_at: str


# ---------- LLM node outputs (checked by the final validator) ----------


class AnalystOutput(BaseModel):
    category: Literal["in_scope", "out_of_scope", "assignment_like"]
    objective_id: str | None = None
    reason: str


class ResponderOutput(BaseModel):
    answer_text: str
    citations: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    grounded: bool  # responder's own self-check (used in 2-agent mode)


class GuardianClaim(BaseModel):
    claim: str
    chunk_id: str | None  # cited chunk that states the claim; None = not supported


class GuardianOutput(BaseModel):
    claims: list[GuardianClaim]
    reveals_graded_work: bool
    verdict: Literal["pass", "fail"]
    reason: str
