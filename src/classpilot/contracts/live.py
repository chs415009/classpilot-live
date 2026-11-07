"""Live-path contracts: poll evidence, student question, decision.

DRAFT v2 shapes (interface_questions.md Q-14, Q-15, Q-19) until the team agrees.
Field names follow the team README where one exists. Unused fields are None
(serialized as null).
"""

from typing import Literal

from pydantic import BaseModel, Field

Path = Literal["poll", "question"]
Action = Literal["explain", "reveal", "answer", "escalate"]
EscalationReason = Literal[
    "out_of_scope",
    "low_confidence",
    "unsupported",
    "llm_error",
]
Backend = Literal["mock", "cortex"]


# ---------- inputs ----------


class PollEvidence(BaseModel):
    session_id: str
    lesson_id: str  # selects the manifest (decided, Q-14)
    poll_id: str  # manifest question id of the poll that ran
    objective_id: str
    question_id: str
    snapshot_time: str
    connected_students: int
    answers_received: int
    option_counts: dict[str, int]
    correct_option: str


class StudentQuestion(BaseModel):
    session_id: str
    event_id: str
    lesson_id: str  # retrieval filter (draft, Q-19)
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
    # poll path
    poll_id: str | None = None
    option: str | None = None  # the wrong option explained
    misconception_id: str | None = None
    remediation_id: str | None = None
    remediation_text: str | None = None
    show_slide: str | None = None
    correct_option: str | None = None  # revealed after explain, or on reveal
    # question path
    answer_text: str | None = None
    citations: list[str] | None = None
    escalation_reason: EscalationReason | None = None
    confidence: float | None = None


# ---------- LLM node outputs (checked by the final validator) ----------


class AnalystOutput(BaseModel):
    category: Literal["in_scope", "out_of_scope"]
    objective_id: str | None = None
    reason: str


class ResponderOutput(BaseModel):
    answer_text: str
    citations: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    grounded: bool  # responder's own self-check (checked before the Guardian runs)


class GuardianClaim(BaseModel):
    claim: str
    chunk_id: str | None  # cited chunk that states the claim; None = not supported


class GuardianOutput(BaseModel):
    claims: list[GuardianClaim]
    verdict: Literal["pass", "fail"]
    reason: str
