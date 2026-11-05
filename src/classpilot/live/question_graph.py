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
    ResponderOutput,
    StudentQuestion,
    Trace,
)
from classpilot.nodes import elapsed_ms
from classpilot.nodes.analyst import run_analyst
from classpilot.nodes.guardian import run_guardian
from classpilot.nodes.responder import run_responder
from classpilot.nodes.retrieval import run_retrieval
from classpilot.settings import Settings
from classpilot.trace import new_decision_id, utc_now


def merge_dicts(a: dict, b: dict) -> dict:
    return {**a, **b}


@dataclass
class Deps:
    settings: Settings
    content: Content
    llm: LLMClient | None = None
    retriever: Retriever | None = None


# ---------- Path B: student question ----------


class QuestionState(TypedDict, total=False):
    question: StudentQuestion
    nodes_run: Annotated[list[str], operator.add]
    llm_calls: Annotated[int, operator.add]
    latency_ms: Annotated[dict[str, int], merge_dicts]
    early_reason: EscalationReason | None  # set by a rule or an LLM failure
    llm_errors: Annotated[list[str], operator.add]
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
            update["llm_errors"] = [result.error]
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
            update["llm_errors"] = [result.error]
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
            update["llm_errors"] = [result.error]
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
            update["llm_errors"] = [result.error]
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
) -> tuple[Decision, Trace]:
    """`details`, if given, is filled with the raw node outputs (for eval only, not the trace)."""
    start = time.perf_counter()
    state = build_question_graph(deps).invoke(
        {"question": question, "nodes_run": [], "llm_calls": 0, "latency_ms": {}, "llm_errors": []}
    )
    total_ms = elapsed_ms(start)
    if details is not None:
        for key in ("analyst_raw", "responder_raw", "guardian_raw", "llm_errors"):
            details[key.removesuffix("_raw")] = state.get(key)

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
    trace = Trace(
        decision_id=decision.decision_id,
        input_ref=question.event_id,
        nodes_run=state["nodes_run"],
        llm_calls=state["llm_calls"],
        retrieved_chunk_ids=[c.chunk_id for c in state.get("retrieved", [])],
        latency_ms={**state["latency_ms"], "total": total_ms},
        backend=deps.settings.backend,
        action=decision.action,
        created_at=utc_now(),
    )
    return decision, trace
