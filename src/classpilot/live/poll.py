"""Path A: poll result -> explain or reveal. A plain function: rules only, no LLM."""

import time

from classpilot import rules
from classpilot.contracts import Decision, PollEvidence
from classpilot.contracts.manifest import Manifest
from classpilot.contracts.trace import (
    DecisionLogEntry,
    NodeRecord,
    NodeStatus,
    PollEvidenceRecord,
    RunRecord,
)
from classpilot.nodes import elapsed_ms
from classpilot.trace import RunOutput, new_decision_id, utc_now, utc_now_ms

POLL_NODES = ["threshold_check", "decide_poll", "explanation_lookup"]


class PollInputError(ValueError):
    """The poll evidence does not match the manifest (other lesson, unknown poll, wrong key)."""


def run_poll(evidence: PollEvidence, manifest: Manifest, backend: str) -> RunOutput:
    started_at, start = utc_now_ms(), time.perf_counter()
    if evidence.lesson_id != manifest.lesson_id:
        raise PollInputError(
            f"evidence is for lesson {evidence.lesson_id!r}, manifest is {manifest.lesson_id!r}"
        )
    found = manifest.find_question(evidence.poll_id)
    if found is None:
        raise PollInputError(f"poll {evidence.poll_id!r} is not in lesson {manifest.lesson_id!r}")
    segment, question = found
    if question.status == "dropped":
        raise PollInputError(f"poll {evidence.poll_id!r} was dropped at prep time")
    if evidence.correct_option != question.correct_option:
        raise PollInputError(
            f"poll {evidence.poll_id!r}: evidence says correct option "
            f"{evidence.correct_option!r}, manifest says {question.correct_option!r}"
        )

    statuses: dict[str, NodeStatus] = dict.fromkeys(POLL_NODES, "skip")
    latency: dict[str, int] = dict.fromkeys(POLL_NODES, 0)

    t = time.perf_counter()
    params = manifest.params
    threshold = rules.check_poll_threshold(
        evidence, params.min_responses, params.wrong_ratio_threshold
    )
    statuses["threshold_check"], latency["threshold_check"] = "pass", elapsed_ms(t)

    t = time.perf_counter()
    outcome = rules.decide_poll(threshold)
    statuses["decide_poll"], latency["decide_poll"] = "pass", elapsed_ms(t)
    deciding_node = "decide_poll"

    explanation = None
    if outcome.action == "explain":
        t = time.perf_counter()
        explanation = rules.lookup_explanation(manifest, question, outcome.option)
        statuses["explanation_lookup"] = "pass" if explanation else "fail"
        latency["explanation_lookup"] = elapsed_ms(t)
        if explanation is None:
            # Cannot happen with a validated manifest; reveal is the safe outcome.
            outcome, deciding_node = rules.PollOutcome("reveal"), "explanation_lookup"

    decision = Decision(
        decision_id=new_decision_id(),
        session_id=evidence.session_id,
        path="poll",
        action=outcome.action,
        poll_id=evidence.poll_id,
        option=outcome.option,
        misconception_id=explanation.misconception_id if explanation else None,
        remediation_id=explanation.remediation_id if explanation else None,
        remediation_text=explanation.text if explanation else None,
        show_slide=explanation.show_slide if explanation else None,
        correct_option=question.correct_option,
    )

    created_at = utc_now()
    base = {
        "run_id": decision.decision_id,
        "session_id": evidence.session_id,
        "created_at": created_at,
    }
    records = [
        RunRecord(
            **base,
            path="poll",
            lesson_id=manifest.lesson_id,
            input_ref=evidence.poll_id,
            segment_id=segment.segment_id,
            misconception_id=decision.misconception_id,
            remediation_id=decision.remediation_id,
            final_action=decision.action,
            escalation_reason=None,
            deciding_node=deciding_node,
            started_at=started_at,
            ended_at=utc_now_ms(),
            latency_ms=elapsed_ms(start),
            llm_call_count=0,
            confidence=None,
            backend=backend,
        )
    ]
    records += [
        NodeRecord(
            **base,
            node_seq=i,
            node_name=name,
            status=statuses[name],
            latency_ms=latency[name],
            llm_call_count=0,
        )
        for i, name in enumerate(POLL_NODES, start=1)
    ]
    records += [
        PollEvidenceRecord(
            **base,
            poll_id=evidence.poll_id,
            option=option,
            response_count=evidence.option_counts.get(option, 0),
            is_correct=option == question.correct_option,
            connected_students=evidence.connected_students,
        )
        for option in sorted(set(question.options) | set(evidence.option_counts))
    ]
    log = DecisionLogEntry(
        created_at=created_at,
        lesson_id=manifest.lesson_id,
        decision=decision,
        poll_evidence=evidence,
    )
    return RunOutput(decision, records, log)
