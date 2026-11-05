"""Path A: poll result -> explain or reveal. A plain function: rules only, no LLM."""

import time

from classpilot import rules
from classpilot.contracts import Decision, PollEvidence, Trace
from classpilot.contracts.manifest import Manifest
from classpilot.nodes import elapsed_ms
from classpilot.trace import new_decision_id, utc_now


class PollInputError(ValueError):
    """The poll evidence does not match the manifest (unknown poll, wrong answer key)."""


def run_poll(evidence: PollEvidence, manifest: Manifest, backend: str) -> tuple[Decision, Trace]:
    start = time.perf_counter()
    found = manifest.find_question(evidence.poll_id)
    if found is None:
        raise PollInputError(f"poll {evidence.poll_id!r} is not in lesson {manifest.lesson_id!r}")
    _, question = found
    if question.status == "dropped":
        raise PollInputError(f"poll {evidence.poll_id!r} was dropped at prep time")
    if evidence.correct_option != question.correct_option:
        raise PollInputError(
            f"poll {evidence.poll_id!r}: evidence says correct option "
            f"{evidence.correct_option!r}, manifest says {question.correct_option!r}"
        )

    params = manifest.params
    threshold = rules.check_poll_threshold(
        evidence, params.min_responses, params.wrong_ratio_threshold
    )
    nodes_run = ["threshold_check", "decide_poll"]
    outcome = rules.decide_poll(threshold)

    explanation = None
    if outcome.action == "explain":
        nodes_run.append("explanation_lookup")
        explanation = rules.lookup_explanation(manifest, question, outcome.option)
        if explanation is None:
            # Cannot happen with a validated manifest; reveal is the safe outcome.
            outcome = rules.PollOutcome("reveal")

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
    trace = Trace(
        decision_id=decision.decision_id,
        input_ref=f"{evidence.poll_id}@{evidence.snapshot_time}",
        agent_mode=None,
        nodes_run=nodes_run,
        llm_calls=0,
        retrieved_chunk_ids=[],
        latency_ms={"total": elapsed_ms(start)},
        backend=backend,
        action=decision.action,
        created_at=utc_now(),
    )
    return decision, trace
