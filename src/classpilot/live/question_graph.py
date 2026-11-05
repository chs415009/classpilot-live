"""Path B (student question) as a LangGraph flow:
analyst -> retrieval -> responder -> guardian -> validator. Path A is `live/poll.py`."""

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
    ClaimRecord,
    DecisionLogEntry,
    LLMCallRecord,
    NodeRecord,
    NodeStatus,
    RetrievalRecord,
    RunRecord,
)
from classpilot.nodes import elapsed_ms
from classpilot.nodes.analyst import run_analyst
from classpilot.nodes.guardian import run_guardian
from classpilot.nodes.responder import run_responder
from classpilot.nodes.retrieval import run_retrieval
from classpilot.settings import Settings
from classpilot.trace import RunOutput, new_decision_id, short_hash, utc_now, utc_now_ms

QUESTION_NODES = ["analyst", "retrieval", "responder", "guardian", "validator"]
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
    nodes_run: Annotated[list[str], operator.add]
    llm_calls: Annotated[int, operator.add]
    latency_ms: Annotated[dict[str, int], merge_dicts]
    early_reason: EscalationReason | None  # set by a rule or an LLM failure
    errors: Annotated[dict[str, str], merge_dicts]  # node -> error message
    analyst_raw: dict | None
    responder_raw: dict | None
    guardian_raw: dict | None
    retrieved: list[RetrievedChunk]
    result: rules.ValidatorResult


def build_question_graph(deps: Deps):
    settings = deps.settings
    timeout_s = settings.llm.timeout_seconds

    def analyst(state: QuestionState) -> dict:
        result = run_analyst(
            state["question"].question_text, deps.content.objectives, deps.llm, timeout_s
        )
        update = {
            "nodes_run": ["analyst"],
            "llm_calls": 1,
            "latency_ms": {"analyst": result.latency_ms},
            "analyst_raw": result.raw,
        }
        if result.error:
            update["early_reason"] = "llm_error"
            update["errors"] = {"analyst": result.error}
        return update

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
            state["question"].question_text, state["retrieved"], deps.llm, timeout_s
        )
        update = {
            "nodes_run": ["responder"],
            "llm_calls": 1,
            "latency_ms": {"responder": result.latency_ms},
            "responder_raw": result.raw,
        }
        if result.error:
            update["early_reason"] = "llm_error"
            update["errors"] = {"responder": result.error}
        return update

    def guardian(state: QuestionState) -> dict:
        response = ResponderOutput.model_validate(state["responder_raw"])
        cited = [
            {"chunk_id": c.chunk_id, "text": c.text}
            for c in state["retrieved"]
            if c.chunk_id in response.citations
        ]
        result = run_guardian(
            state["question"].question_text, response.answer_text, cited, deps.llm, timeout_s
        )
        update = {
            "nodes_run": ["guardian"],
            "llm_calls": 1,
            "latency_ms": {"guardian": result.latency_ms},
            "guardian_raw": result.raw,
        }
        if result.error:
            update["early_reason"] = "llm_error"
            update["errors"] = {"guardian": result.error}
        return update

    def validator(state: QuestionState) -> dict:
        result = rules.validate_final(
            early_reason=state.get("early_reason"),
            analyst_raw=state.get("analyst_raw"),
            responder_raw=state.get("responder_raw"),
            guardian_raw=state.get("guardian_raw"),
            retrieved_ids=[c.chunk_id for c in state.get("retrieved", [])],
            confidence_threshold=settings.question.confidence_threshold,
        )
        return {"result": result, "nodes_run": ["validator"]}

    # Routing only skips ahead to the validator; it never makes the final decision.
    def after_analyst(state: QuestionState) -> str:
        analysis = rules.parse_or_none(AnalystOutput, state.get("analyst_raw"))
        if state.get("early_reason") or analysis is None or analysis.category != "in_scope":
            return "validator"
        return "retrieval"

    def after_retrieval(state: QuestionState) -> str:
        return "validator" if state.get("early_reason") else "responder"

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
    graph.add_edge(START, "analyst")
    graph.add_conditional_edges("analyst", after_analyst)
    graph.add_conditional_edges("retrieval", after_retrieval)
    graph.add_conditional_edges("responder", after_responder)
    graph.add_edge("guardian", "validator")
    graph.add_edge("validator", END)
    return graph.compile()


def run_question(
    question: StudentQuestion,
    deps: Deps,
    details: dict | None = None,
) -> RunOutput:
    """`details`, if given, is filled with the raw node outputs (for eval only, not the trace)."""
    started_at, start = utc_now_ms(), time.perf_counter()
    state = build_question_graph(deps).invoke(
        {"question": question, "nodes_run": [], "llm_calls": 0, "latency_ms": {}, "errors": {}}
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
        state, decision, deps.settings, created_at, started_at, utc_now_ms(), total_ms
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
) -> list:
    """Trace v2 records for one question. Node statuses are read back from the state
    with the same rules the graph used; nothing here changes the decision."""
    question = state["question"]
    ran, errors, latency = set(state["nodes_run"]), state["errors"], state["latency_ms"]
    analysis = rules.parse_or_none(AnalystOutput, state.get("analyst_raw"))
    response = rules.parse_or_none(ResponderOutput, state.get("responder_raw"))
    guardian = rules.parse_or_none(GuardianOutput, state.get("guardian_raw"))
    citations = response.citations if response else []

    status: dict[str, NodeStatus] = {}
    if "analyst" in errors or analysis is None:
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
        check = rules.check_guardian(state.get("guardian_raw"), citations)
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
        llm_calls = 1 if name in LLM_NODES and name in ran else 0
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
                    latency_ms=latency.get(name, 0),
                    retry_count=0,
                    error_count=1 if name in errors else 0,
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
