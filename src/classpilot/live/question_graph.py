"""Path B (student question) as a LangGraph flow:
retrieval -> analyst -> responder -> guardian -> validator. Path A is `live/poll.py`.

Stage 12: retrieval runs first, so the Analyst judges scope from the lesson material
(slides and readings), not only from the objective titles. The Guardian has its own
timeout, capped by what is left of the per-question deadline."""

import operator
import time
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from classpilot import rules
from classpilot.adapters.llm import LLMClient
from classpilot.adapters.retrieval import RetrievedChunk, Retriever
from classpilot.content import Content
from classpilot.contracts import (
    AnalystOutput,
    Decision,
    EscalationReason,
    GuardianOutput,
    ResponderOutput,
    StudentQuestion,
)
from classpilot.contracts.trace import (
    PROMPT_VERSION,
    ClaimRecord,
    DecisionLogEntry,
    LLMCallRecord,
    NodeRecord,
    NodeStatus,
    RetrievalRecord,
    RunRecord,
)
from classpilot.nodes import RetryPolicy, elapsed_ms
from classpilot.nodes.analyst import run_analyst
from classpilot.nodes.guardian import run_guardian
from classpilot.nodes.responder import run_responder
from classpilot.nodes.retrieval import run_retrieval
from classpilot.settings import Settings
from classpilot.trace import RunOutput, new_decision_id, short_hash, utc_now, utc_now_ms

QUESTION_NODES = ["retrieval", "analyst", "responder", "guardian", "validator"]
LLM_NODES = {"analyst", "responder", "guardian"}


def merge_dicts(a: dict, b: dict) -> dict:
    return {**a, **b}


@dataclass
class Deps:
    settings: Settings
    content: Content
    llm: LLMClient | None = None
    retriever: Retriever | None = None


class QuestionState(TypedDict, total=False):
    question: StudentQuestion
    started: float  # time.perf_counter() when the question entered the graph
    nodes_run: Annotated[list[str], operator.add]
    llm_calls: Annotated[int, operator.add]
    latency_ms: Annotated[dict[str, int], merge_dicts]
    early_reason: EscalationReason | None  # set by a rule or an LLM failure
    errors: Annotated[dict[str, str], merge_dicts]  # node -> error message
    retries: Annotated[dict[str, int], merge_dicts]  # node -> repeated calls (malformed)
    analyst_raw: dict | None
    responder_raw: dict | None
    guardian_raw: dict | None
    retrieved: list[RetrievedChunk]
    result: rules.ValidatorResult


def build_question_graph(deps: Deps):
    settings = deps.settings
    timeout_s = settings.llm.timeout_seconds
    q = settings.question

    def retry_policy(state: QuestionState) -> RetryPolicy:
        def seconds_left() -> float:
            return q.deadline_seconds - (time.perf_counter() - state["started"])

        return RetryPolicy(q.malformed_retries, q.min_retry_seconds, seconds_left)

    def llm_update(name: str, result, raw_key: str) -> dict:
        update = {
            "nodes_run": [name],
            "llm_calls": 1 + result.retries,
            "latency_ms": {name: result.latency_ms},
            "retries": {name: result.retries},
            raw_key: result.raw,
        }
        if result.error:
            update["early_reason"] = "llm_error"
            update["errors"] = {name: result.error}
        return update

    def analyst(state: QuestionState) -> dict:
        shown = [
            {"chunk_id": c.chunk_id, "text": c.text[: q.analyst_chunk_chars]}
            for c in state.get("retrieved", [])
        ]
        result = run_analyst(
            state["question"].question_text,
            deps.content.objectives,
            deps.llm,
            timeout_s,
            shown,
            retry_policy(state),
        )
        return llm_update("analyst", result, "analyst_raw")

    def retrieval(state: QuestionState) -> dict:
        question = state["question"]
        result = run_retrieval(
            deps.retriever,
            question.question_text,
            settings.question.retrieval_top_k,
            question.lesson_id,
        )
        update = {
            "nodes_run": ["retrieval"],
            "latency_ms": {"retrieval": result.latency_ms},
            "retrieved": result.chunks,
        }
        if result.error:
            # No chunks means no grounded answer; escalate like an LLM error.
            update["early_reason"] = "llm_error"
            update["errors"] = {"retrieval": result.error}
        return update

    def responder(state: QuestionState) -> dict:
        result = run_responder(
            state["question"].question_text,
            state["retrieved"],
            deps.llm,
            timeout_s,
            retry_policy(state),
        )
        return llm_update("responder", result, "responder_raw")

    def guardian(state: QuestionState) -> dict:
        response = ResponderOutput.model_validate(state["responder_raw"])
        # Stage 9 (user decision): the Guardian sees every retrieved chunk, cited first,
        # so true content the Responder forgot to cite is not a failure.
        ordered = sorted(state["retrieved"], key=lambda c: c.chunk_id not in response.citations)
        shown = [{"chunk_id": c.chunk_id, "text": c.text} for c in ordered]
        result = run_guardian(
            state["question"].question_text,
            response.answer_text,
            shown,
            deps.llm,
            guardian_timeout(q.guardian_timeout_seconds, q.deadline_seconds, state["started"]),
            retry_policy(state),
        )
        return llm_update("guardian", result, "guardian_raw")

    def validator(state: QuestionState) -> dict:
        result = rules.validate_final(
            early_reason=state.get("early_reason"),
            analyst_raw=state.get("analyst_raw"),
            responder_raw=state.get("responder_raw"),
            guardian_raw=state.get("guardian_raw"),
            retrieved_ids=[c.chunk_id for c in state.get("retrieved", [])],
            confidence_threshold=settings.question.confidence_threshold,
            retrieved_texts={c.chunk_id: c.text for c in state.get("retrieved", [])},
            rescue_coverage=settings.question.guardian_rescue_coverage,
        )
        return {"result": result, "nodes_run": ["validator"]}

    # Routing only skips ahead to the validator; it never makes the final decision.
    def after_retrieval(state: QuestionState) -> str:
        return "validator" if state.get("early_reason") else "analyst"

    def after_analyst(state: QuestionState) -> str:
        analysis = rules.parse_or_none(AnalystOutput, state.get("analyst_raw"))
        if state.get("early_reason") or analysis is None or analysis.category != "in_scope":
            return "validator"
        return "responder"

    def after_responder(state: QuestionState) -> str:
        # Skip the Guardian when the validator will escalate no matter what it says.
        response = rules.parse_or_none(ResponderOutput, state.get("responder_raw"))
        if state.get("early_reason") or response is None:
            return "validator"
        retrieved_ids = [c.chunk_id for c in state.get("retrieved", [])]
        if rules.check_response(response, retrieved_ids, settings.question.confidence_threshold):
            return "validator"
        return "guardian"

    graph = StateGraph(QuestionState)
    for name, node in [
        ("analyst", analyst),
        ("retrieval", retrieval),
        ("responder", responder),
        ("guardian", guardian),
        ("validator", validator),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "retrieval")
    graph.add_conditional_edges("retrieval", after_retrieval)
    graph.add_conditional_edges("analyst", after_analyst)
    graph.add_conditional_edges("responder", after_responder)
    graph.add_edge("guardian", "validator")
    graph.add_edge("validator", END)
    return graph.compile()


MIN_GUARDIAN_SECONDS = 1.0


def guardian_timeout(own_s: float, deadline_s: float, started: float) -> float:
    """The Guardian's own timeout, capped by what is left of the question's deadline.
    At least MIN_GUARDIAN_SECONDS, so a call is never made with no time at all (the
    Analyst and Responder timeouts leave the Guardian about 10 s in the worst case)."""
    left = deadline_s - (time.perf_counter() - started)
    return max(MIN_GUARDIAN_SECONDS, min(own_s, left))


def run_question(
    question: StudentQuestion,
    deps: Deps,
    details: dict | None = None,
) -> RunOutput:
    """`details`, if given, is filled with the raw node outputs (for eval only, not the trace)."""
    started_at, start = utc_now_ms(), time.perf_counter()
    state = build_question_graph(deps).invoke(
        {
            "question": question,
            "started": start,
            "nodes_run": [],
            "llm_calls": 0,
            "latency_ms": {},
            "errors": {},
            "retries": {},
        }
    )
    total_ms = elapsed_ms(start)
    if details is not None:
        for key in ("analyst_raw", "responder_raw", "guardian_raw"):
            details[key.removesuffix("_raw")] = state.get(key)
        details["llm_errors"] = list(state["errors"].values())

    result: rules.ValidatorResult = state["result"]
    decision = Decision(
        decision_id=new_decision_id(),
        session_id=question.session_id,
        path="question",
        action=result.action,
        answer_text=result.answer_text,
        citations=result.citations,
        escalation_reason=result.escalation_reason,
        confidence=result.confidence,
    )
    created_at = utc_now()
    records = question_records(
        state,
        decision,
        deps.settings,
        created_at,
        started_at,
        utc_now_ms(),
        total_ms,
        prompt_version=getattr(deps.llm, "prompt_version", PROMPT_VERSION),
    )
    log = DecisionLogEntry(
        created_at=created_at, lesson_id=question.lesson_id, decision=decision, question=question
    )
    return RunOutput(decision, records, log)


def question_records(
    state: QuestionState,
    decision: Decision,
    settings: Settings,
    created_at: str,
    started_at: str,
    ended_at: str,
    total_ms: int,
    prompt_version: str = PROMPT_VERSION,
) -> list:
    """Trace v2 records for one question. Node statuses are read back from the state
    with the same rules the graph used; nothing here changes the decision."""
    question = state["question"]
    ran, errors, latency = set(state["nodes_run"]), state["errors"], state["latency_ms"]
    retries = state.get("retries", {})
    analysis = rules.parse_or_none(AnalystOutput, state.get("analyst_raw"))
    response = rules.parse_or_none(ResponderOutput, state.get("responder_raw"))
    guardian = rules.parse_or_none(GuardianOutput, state.get("guardian_raw"))
    citations = response.citations if response else []

    status: dict[str, NodeStatus] = {}
    if "analyst" not in ran:
        status["analyst"] = "skip"  # retrieval failed first (Stage 12 order)
    elif "analyst" in errors or analysis is None:
        status["analyst"] = "fail"
    else:
        status["analyst"] = "pass" if analysis.category == "in_scope" else "block"
    status["retrieval"] = (
        "skip" if "retrieval" not in ran else "fail" if "retrieval" in errors else "pass"
    )
    if "responder" not in ran:
        status["responder"] = "skip"
    elif "responder" in errors or response is None:
        status["responder"] = "fail"
    else:
        retrieved_ids = [c.chunk_id for c in state.get("retrieved", [])]
        reason = rules.check_response(
            response, retrieved_ids, settings.question.confidence_threshold
        )
        status["responder"] = "block" if reason else "pass"
    if "guardian" not in ran:
        status["guardian"] = "skip"
    else:
        retrieved = state.get("retrieved", [])
        check = rules.check_guardian(
            state.get("guardian_raw"),
            [c.chunk_id for c in retrieved],
            {c.chunk_id: c.text for c in retrieved},
            settings.question.guardian_rescue_coverage,
        )
        if "guardian" in errors or check.passed is None:
            status["guardian"] = "fail"
        else:
            status["guardian"] = "pass" if check.passed else "block"
    status["validator"] = "pass"

    deciding_node = "validator"
    if decision.action == "escalate":
        deciding_node = next(
            (n for n in QUESTION_NODES if status[n] in ("fail", "block")), "validator"
        )
    segment_id = question.objective_id
    if analysis is not None and analysis.category == "in_scope" and analysis.objective_id:
        segment_id = analysis.objective_id

    base = {
        "run_id": decision.decision_id,
        "session_id": question.session_id,
        "created_at": created_at,
    }
    model = settings.llm.model if settings.backend == "cortex" else "mock"
    records: list = [
        RunRecord(
            **base,
            path="question",
            lesson_id=question.lesson_id,
            input_ref=question.event_id,
            segment_id=segment_id,
            misconception_id=None,
            remediation_id=None,
            final_action=decision.action,
            escalation_reason=decision.escalation_reason,
            deciding_node=deciding_node,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=total_ms,
            llm_call_count=state["llm_calls"],
            confidence=decision.confidence,
            backend=settings.backend,
        )
    ]
    for seq, name in enumerate(QUESTION_NODES, start=1):
        llm_calls = 1 + retries.get(name, 0) if name in LLM_NODES and name in ran else 0
        records.append(
            NodeRecord(
                **base,
                node_seq=seq,
                node_name=name,
                status=status[name],
                latency_ms=latency.get(name, 0),
                llm_call_count=llm_calls,
            )
        )
        if llm_calls:
            records.append(
                LLMCallRecord(
                    **base,
                    call_id=f"{decision.decision_id}-{name}",
                    node_name=name,
                    model=model or "unknown",
                    prompt_version=prompt_version,
                    latency_ms=latency.get(name, 0),
                    retry_count=retries.get(name, 0),
                    error_count=retries.get(name, 0) + (1 if name in errors else 0),
                )
            )
    query_hash = short_hash(question.question_text)
    records += [
        RetrievalRecord(
            **base,
            rank=rank,
            chunk_id=chunk.chunk_id,
            similarity_score=chunk.score,
            cited=chunk.chunk_id in citations,
            query_hash=query_hash,
        )
        for rank, chunk in enumerate(state.get("retrieved", []), start=1)
    ]
    if guardian is not None:
        records += [
            ClaimRecord(
                **base,
                claim_seq=seq,
                claim_hash=short_hash(claim.claim),
                supporting_chunk_id=claim.chunk_id,
                supported=claim.chunk_id is not None and claim.chunk_id in citations,
            )
            for seq, claim in enumerate(guardian.claims, start=1)
        ]
    return records
