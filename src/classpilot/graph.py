"""LangGraph flows for Path A (poll trigger) and Path B (student question)."""

import operator
import time
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from classpilot import rules
from classpilot.adapters.llm import LLMClient
from classpilot.adapters.retrieval import Retriever
from classpilot.content import Content
from classpilot.contracts import (
    AnalystOutput,
    Decision,
    EscalationReason,
    PollEvidence,
    ResponderOutput,
    StudentQuestion,
    Trace,
)
from classpilot.nodes import elapsed_ms
from classpilot.nodes.analyst import run_analyst
from classpilot.nodes.guardian import run_guardian
from classpilot.nodes.responder import run_responder
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


# ---------- Path A: poll trigger (rules only) ----------


class PollState(TypedDict, total=False):
    evidence: PollEvidence
    nodes_run: Annotated[list[str], operator.add]
    threshold: rules.ThresholdResult
    remediation_id: str | None
    limit_reached: bool
    outcome: rules.PollOutcome


def build_poll_graph(deps: Deps):
    poll = deps.settings.poll

    def threshold_check(state: PollState) -> dict:
        result = rules.check_poll_threshold(
            state["evidence"], poll.min_responses, poll.wrong_ratio_threshold
        )
        return {"threshold": result, "nodes_run": ["threshold_check"]}

    def misconception_lookup(state: PollState) -> dict:
        remediation_id = rules.lookup_remediation(
            deps.content.misconception_map,
            state["evidence"].question_id,
            state["threshold"].top_wrong_option,
        )
        return {"remediation_id": remediation_id, "nodes_run": ["misconception_lookup"]}

    def remediation_limit_check(state: PollState) -> dict:
        reached = rules.remediation_limit_reached(
            state["evidence"], poll.max_remediations_per_objective
        )
        return {"limit_reached": reached, "nodes_run": ["remediation_limit_check"]}

    def poll_decision(state: PollState) -> dict:
        outcome = rules.decide_poll(
            state["threshold"], state.get("remediation_id"), state.get("limit_reached", False)
        )
        return {"outcome": outcome, "nodes_run": ["poll_decision"]}

    graph = StateGraph(PollState)
    graph.add_node("threshold_check", threshold_check)
    graph.add_node("misconception_lookup", misconception_lookup)
    graph.add_node("remediation_limit_check", remediation_limit_check)
    graph.add_node("poll_decision", poll_decision)

    graph.add_edge(START, "threshold_check")
    graph.add_conditional_edges(
        "threshold_check",
        lambda s: "misconception_lookup" if s["threshold"].triggered else "poll_decision",
    )
    graph.add_conditional_edges(
        "misconception_lookup",
        lambda s: "remediation_limit_check" if s["remediation_id"] else "poll_decision",
    )
    graph.add_edge("remediation_limit_check", "poll_decision")
    graph.add_edge("poll_decision", END)
    return graph.compile()


def run_poll(evidence: PollEvidence, deps: Deps) -> tuple[Decision, Trace]:
    start = time.perf_counter()
    state = build_poll_graph(deps).invoke({"evidence": evidence, "nodes_run": []})
    total_ms = elapsed_ms(start)

    outcome: rules.PollOutcome = state["outcome"]
    decision = Decision(
        decision_id=new_decision_id(),
        session_id=evidence.session_id,
        path="poll",
        action=outcome.action,
        remediation_id=outcome.remediation_id,
        escalation_reason=outcome.escalation_reason,
    )
    trace = Trace(
        decision_id=decision.decision_id,
        input_ref=f"{evidence.question_id}@{evidence.snapshot_time}",
        agent_mode=None,
        nodes_run=state["nodes_run"],
        llm_calls=0,
        retrieved_chunk_ids=[],
        latency_ms={"total": total_ms},
        backend=deps.settings.backend,
        action=decision.action,
        created_at=utc_now(),
    )
    return decision, trace


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
    retrieved: list[dict]
    result: rules.ValidatorResult


def build_question_graph(deps: Deps, agent_mode: int):
    settings = deps.settings
    timeout_s = settings.llm.timeout_seconds

    def protected_check(state: QuestionState) -> dict:
        match = rules.check_protected(
            state["question"].question_text, deps.content.protected_questions
        )
        update = {"nodes_run": ["protected_check"]}
        if match.score >= settings.question.protected_similarity_threshold:
            update["early_reason"] = "assignment_like"
        return update

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

    def responder(state: QuestionState) -> dict:
        result = run_responder(
            state["question"].question_text,
            deps.retriever,
            deps.llm,
            settings.question.retrieval_top_k,
            timeout_s,
        )
        update = {
            "nodes_run": ["responder"],
            "llm_calls": 1 if result.llm_called else 0,
            "latency_ms": {"retrieval": result.retrieval_ms, "responder": result.latency_ms},
            "responder_raw": result.raw,
            "retrieved": [{"chunk_id": c.chunk_id, "text": c.text} for c in result.retrieved],
        }
        if result.error:
            update["early_reason"] = "llm_error"
            update["llm_errors"] = [result.error]
        return update

    def guardian(state: QuestionState) -> dict:
        response = ResponderOutput.model_validate(state["responder_raw"])
        cited = [c for c in state["retrieved"] if c["chunk_id"] in response.citations]
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
            agent_mode=agent_mode,
            early_reason=state.get("early_reason"),
            analyst_raw=state.get("analyst_raw"),
            responder_raw=state.get("responder_raw"),
            guardian_raw=state.get("guardian_raw"),
            retrieved_ids=[c["chunk_id"] for c in state.get("retrieved", [])],
            confidence_threshold=settings.question.confidence_threshold,
        )
        return {"result": result, "nodes_run": ["validator"]}

    # Routing only skips ahead to the validator; it never makes the final decision.
    def after_protected(state: QuestionState) -> str:
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
        retrieved_ids = [c["chunk_id"] for c in state.get("retrieved", [])]
        if rules.check_response(response, retrieved_ids, settings.question.confidence_threshold):
            return "validator"
        return "guardian"

    graph = StateGraph(QuestionState)
    graph.add_node("protected_check", protected_check)
    graph.add_node("analyst", analyst)
    graph.add_node("responder", responder)
    graph.add_node("validator", validator)
    graph.add_edge(START, "protected_check")
    graph.add_conditional_edges("protected_check", after_protected)
    graph.add_conditional_edges("analyst", after_analyst)
    if agent_mode == 3:
        graph.add_node("guardian", guardian)
        graph.add_conditional_edges("responder", after_responder)
        graph.add_edge("guardian", "validator")
    else:
        graph.add_edge("responder", "validator")
    graph.add_edge("validator", END)
    return graph.compile()


def run_question(
    question: StudentQuestion, deps: Deps, agent_mode: int | None = None, details: dict | None = None
) -> tuple[Decision, Trace]:
    """`details`, if given, is filled with the raw node outputs (for eval only, not the trace)."""
    mode = agent_mode or deps.settings.agent_mode
    start = time.perf_counter()
    state = build_question_graph(deps, mode).invoke(
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
        agent_mode=mode,
        nodes_run=state["nodes_run"],
        llm_calls=state["llm_calls"],
        retrieved_chunk_ids=[c["chunk_id"] for c in state.get("retrieved", [])],
        latency_ms={**state["latency_ms"], "total": total_ms},
        backend=deps.settings.backend,
        action=decision.action,
        created_at=utc_now(),
    )
    return decision, trace
