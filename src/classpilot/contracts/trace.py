"""Trace v2 records and the decision log (IMPLEMENTATION_NOTES 6.3).

DRAFT field names until agreed with the pipeline part (interface_questions.md Q-21).
The trace JSONL is the only source of the team's star schema: one line per record,
`record_type` says which fact it feeds. Every record carries `run_id` (= the
decision id) and `session_id` (the BATCH: one class session).

The fields removed from the data model by agreement (IMPLEMENTATION_NOTES 6.3,
"Not provided") are never written: `extra="forbid"` keeps them, and any other
unplanned field, out. The contract test checks this.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from classpilot.contracts.live import (
    Action,
    Backend,
    Decision,
    EscalationReason,
    Path,
    PollEvidence,
    StudentQuestion,
)

SCHEMA_VERSION = "v2-draft"
PROMPT_VERSION = "uncompiled-v1"  # id of the compiled DSPy program from Stage 9

NodeStatus = Literal["pass", "fail", "block", "skip"]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    run_id: str
    session_id: str
    created_at: str


class RunRecord(_Record):
    """FACT_PIPELINE_RUN: one live decision."""

    record_type: Literal["run"] = "run"
    path: Path
    lesson_id: str
    input_ref: str  # poll_id (poll) or event_id (question)
    segment_id: str | None
    misconception_id: str | None  # poll path, on explain
    remediation_id: str | None  # poll path, on explain
    final_action: Action
    escalation_reason: EscalationReason | None
    deciding_node: str
    started_at: str
    ended_at: str
    latency_ms: int
    llm_call_count: int  # counted by the graph; equals the run's llm_call records
    confidence: float | None
    backend: Backend


class NodeRecord(_Record):
    """FACT_NODE_EXECUTION: one node of the path per run (skipped nodes included)."""

    record_type: Literal["node"] = "node"
    node_seq: int  # 1-based position in the path
    node_name: str
    status: NodeStatus
    latency_ms: int
    llm_call_count: int


class LLMCallRecord(_Record):
    """FACT_LLM_CALL: one LLM call."""

    record_type: Literal["llm_call"] = "llm_call"
    call_id: str
    node_name: str
    model: str
    prompt_version: str = PROMPT_VERSION
    latency_ms: int
    retry_count: int
    error_count: int


class RetrievalRecord(_Record):
    """FACT_RETRIEVAL: one retrieved chunk."""

    record_type: Literal["retrieval"] = "retrieval"
    rank: int  # 1-based
    chunk_id: str
    similarity_score: float  # cosine in Cortex; word overlap in mock mode
    cited: bool  # cited by the responder
    query_hash: str


class ClaimRecord(_Record):
    """FACT_CLAIM_CHECK: one claim listed by the Guardian."""

    record_type: Literal["claim"] = "claim"
    claim_seq: int  # 1-based
    claim_hash: str
    supporting_chunk_id: str | None  # null = no cited chunk supports it
    supported: bool


class PollEvidenceRecord(_Record):
    """FACT_POLL_EVIDENCE: one option of one poll."""

    record_type: Literal["poll_evidence"] = "poll_evidence"
    poll_id: str
    option: str
    response_count: int
    is_correct: bool
    connected_students: int | None  # optional, pending the pipeline part


TraceRecord = (
    RunRecord | NodeRecord | LLMCallRecord | RetrievalRecord | ClaimRecord | PollEvidenceRecord
)
RECORD_MODELS: dict[str, type[_Record]] = {
    "run": RunRecord,
    "node": NodeRecord,
    "llm_call": LLMCallRecord,
    "retrieval": RetrievalRecord,
    "claim": ClaimRecord,
    "poll_evidence": PollEvidenceRecord,
}


class DecisionLogEntry(BaseModel):
    """One decision with its text, for the post-class report (draft, Q-16 / Q-20).

    The input is kept as received: the question text for Path B, the evidence for
    Path A. The decision holds the answer, citations, escalation reason, or the
    explanation text and show_slide.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    created_at: str
    lesson_id: str
    decision: Decision
    question: StudentQuestion | None = None
    poll_evidence: PollEvidence | None = None
