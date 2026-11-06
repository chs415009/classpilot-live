"""Run a lesson's test questions through the live question graph (Stage 10).

Each question goes through the same `run_question` as `POST /questions`, so its trace
records and decision-log line are the real ones (written to the run folder). The result
row adds what the report shows and the trace keeps out on purpose: the Analyst and
Guardian replies, the retrieved chunk texts, and the claims the word check rescued
(recomputed by code from the Guardian reply; no LLM call).
"""

from pathlib import Path

from classpilot import rules
from classpilot.content import Content
from classpilot.contracts import StudentQuestion
from classpilot.contracts.trace import LLMCallRecord, NodeRecord, RetrievalRecord
from classpilot.dev.lessons import LessonQuestion, LessonQuestionSet
from classpilot.live.question_graph import Deps, run_question
from classpilot.trace import utc_now, write_run


def is_match(question: LessonQuestion, action: str, reason: str | None) -> bool:
    if action != question.expected_action:
        return False
    return action == "answer" or reason in question.accepted_reasons


def run_one(question: LessonQuestion, deps: Deps, session_id: str) -> tuple[dict, object]:
    content: Content = deps.content
    student_question = StudentQuestion(
        session_id=session_id,
        event_id=question.question_id,
        lesson_id=content.lesson_id,
        anonymous_learner_id="dev-learner",
        objective_id=None,
        question_text=question.question_text,
        submitted_at=utc_now(),
    )
    details: dict = {}
    output = run_question(student_question, deps, details)
    decision = output.decision
    texts = {c["chunk_id"]: c["text"] for c in content.chunks}
    retrieved = [
        {
            "rank": r.rank,
            "chunk_id": r.chunk_id,
            "score": r.similarity_score,
            "cited": r.cited,
            "text": texts.get(r.chunk_id, ""),
        }
        for r in output.of_type(RetrievalRecord)
    ]
    rescued: list[str] = []
    if details.get("guardian"):
        check = rules.check_guardian(
            details["guardian"],
            [r["chunk_id"] for r in retrieved],
            {r["chunk_id"]: r["text"] for r in retrieved},
            deps.settings.question.guardian_rescue_coverage,
        )
        rescued = check.rescued
    calls = output.of_type(LLMCallRecord)
    citations = decision.citations or []
    row = {
        **question.model_dump(),
        "action": decision.action,
        "escalation_reason": decision.escalation_reason,
        "match": is_match(question, decision.action, decision.escalation_reason),
        "answer_text": decision.answer_text,
        "citations": citations,
        "sources_cited": [s for s in question.sources if s in citations],
        "confidence": decision.confidence,
        "deciding_node": output.run.deciding_node,
        "analyst": details.get("analyst"),
        "responder": details.get("responder"),
        "guardian": details.get("guardian"),
        "rescued": rescued,
        "llm_errors": details.get("llm_errors", []),
        "retrieved": retrieved,
        "nodes": [
            {"name": n.node_name, "status": n.status, "latency_ms": n.latency_ms}
            for n in output.of_type(NodeRecord)
        ],
        "latency_ms": output.run.latency_ms,
        "llm_calls": len(calls),
        "llm_call_errors": sum(c.error_count for c in calls),
        "prompt_versions": sorted({c.prompt_version for c in calls}),
        "models": sorted({c.model for c in calls}),
        "decision_id": decision.decision_id,
    }
    return row, output


def run_questions(
    qset: LessonQuestionSet,
    deps: Deps,
    session_id: str,
    trace_path: Path | None = None,
    log_path: Path | None = None,
    on_row=None,
) -> list[dict]:
    rows = []
    for question in qset.questions:
        row, output = run_one(question, deps, session_id)
        if trace_path is not None and log_path is not None:
            write_run(output, trace_path, log_path)
        rows.append(row)
        if on_row:
            on_row(row)
    return rows
