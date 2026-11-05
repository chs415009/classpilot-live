"""Path B rules: the final validator and the checks it uses. The LLM never decides."""

from dataclasses import dataclass

from pydantic import ValidationError

from classpilot.contracts import (
    Action,
    AnalystOutput,
    EscalationReason,
    GuardianOutput,
    ResponderOutput,
)
from classpilot.text import jaccard

# ---------- Path B: student question ----------


@dataclass
class ProtectedMatch:
    score: float
    protected_id: str | None


def check_protected(question_text: str, protected_questions: list[dict]) -> ProtectedMatch:
    best = ProtectedMatch(0.0, None)
    for item in protected_questions:
        score = jaccard(question_text, item["text"])
        if score > best.score:
            best = ProtectedMatch(score, item["protected_id"])
    return best


def parse_or_none(model: type, raw: dict | None):
    if raw is None:
        return None
    try:
        return model.model_validate(raw)
    except ValidationError:
        return None


@dataclass
class GuardianCheck:
    passed: bool | None  # None when the Guardian output does not match the schema
    reason: str


def check_guardian(guardian_raw: dict | None, cited_ids: list[str]) -> GuardianCheck:
    """Pass only if the Guardian says pass AND its own claim list backs that up.

    The LLM lists claims and their supporting chunks; this rule makes the call, so a
    "pass" verdict next to an unsupported claim still fails.
    """
    output = parse_or_none(GuardianOutput, guardian_raw)
    if output is None:
        return GuardianCheck(None, "Guardian output does not match the schema.")
    if output.verdict != "pass":
        return GuardianCheck(False, output.reason)
    if output.reveals_graded_work:
        return GuardianCheck(False, "Answer gives away graded work.")
    if not output.claims:
        return GuardianCheck(False, "Guardian listed no claims to check.")
    unsupported = [c.claim for c in output.claims if c.chunk_id not in cited_ids]
    if unsupported:
        return GuardianCheck(False, f"Not supported by cited chunks: {unsupported[0]!r}")
    return GuardianCheck(True, output.reason)


def check_response(
    response: ResponderOutput, retrieved_ids: list[str], confidence_threshold: float
) -> EscalationReason | None:
    """Checks on the responder's answer that need no Guardian. Used by the validator,
    and by the graph to skip the Guardian when the answer will be escalated anyway."""
    if not response.citations or not set(response.citations) <= set(retrieved_ids):
        return "unsupported"
    if not response.grounded:
        return "unsupported"
    if response.confidence < confidence_threshold:
        return "low_confidence"
    return None


@dataclass
class ValidatorResult:
    action: Action
    escalation_reason: EscalationReason | None = None
    answer_text: str | None = None
    citations: list[str] | None = None
    confidence: float | None = None


def validate_final(
    *,
    agent_mode: int,
    early_reason: EscalationReason | None,
    analyst_raw: dict | None,
    responder_raw: dict | None,
    guardian_raw: dict | None,
    retrieved_ids: list[str],
    confidence_threshold: float,
) -> ValidatorResult:
    """The only place where the final answer/escalate decision is made."""
    if early_reason is not None:
        return ValidatorResult("escalate", early_reason)

    analysis = parse_or_none(AnalystOutput, analyst_raw)
    if analysis is None:
        return ValidatorResult("escalate", "llm_error")
    if analysis.category != "in_scope":
        return ValidatorResult("escalate", analysis.category)

    response = parse_or_none(ResponderOutput, responder_raw)
    if response is None:
        return ValidatorResult("escalate", "llm_error")

    def escalate(reason: EscalationReason) -> ValidatorResult:
        return ValidatorResult("escalate", reason, confidence=response.confidence)

    reason = check_response(response, retrieved_ids, confidence_threshold)
    if reason is not None:
        return escalate(reason)

    if agent_mode == 3:
        check = check_guardian(guardian_raw, response.citations)
        if check.passed is None:
            return escalate("llm_error")
        if not check.passed:
            return escalate("unsupported")

    return ValidatorResult(
        "answer",
        answer_text=response.answer_text,
        citations=response.citations,
        confidence=response.confidence,
    )
