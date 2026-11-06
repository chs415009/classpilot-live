"""Path B rules: the final validator and the checks it uses. The LLM never decides."""

from dataclasses import dataclass, field

from pydantic import ValidationError

from classpilot.contracts import (
    Action,
    AnalystOutput,
    EscalationReason,
    GuardianOutput,
    ResponderOutput,
)
from classpilot.rules.support import fail_verdict_explained_by, rescued_by_words


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
    rescued: list[str] = field(default_factory=list)  # claims passed by the word check


def check_guardian(
    guardian_raw: dict | None,
    chunk_ids: list[str],
    chunk_texts: dict[str, str] | None = None,
    rescue_coverage: float | None = None,
) -> GuardianCheck:
    """Pass only if the Guardian says pass AND its own claim list backs that up.

    The LLM lists claims and their supporting chunks; this rule makes the call, so a
    "pass" verdict next to an unsupported claim still fails. `chunk_ids` are the chunks
    the Guardian saw (Stage 9: every retrieved chunk, not only the cited ones). With
    `chunk_texts` and `rescue_coverage`, a claim the Guardian left without a chunk
    passes if code finds its words in one of those chunks (`rescued_by_words`). A "fail"
    verdict stands unless its reason names only rescued claims
    (`fail_verdict_explained_by`).
    """
    output = parse_or_none(GuardianOutput, guardian_raw)
    if output is None:
        return GuardianCheck(None, "Guardian output does not match the schema.")
    if output.reveals_graded_work:
        return GuardianCheck(False, "Answer gives away graded work.")
    if not output.claims:
        return GuardianCheck(False, "Guardian listed no claims to check.")
    texts = [chunk_texts[i] for i in chunk_ids if chunk_texts and i in chunk_texts]
    unsupported, rescued = [], []
    for c in output.claims:
        if c.chunk_id in chunk_ids:
            continue
        if rescue_coverage is not None and rescued_by_words(c.claim, texts, rescue_coverage):
            rescued.append(c.claim)
        else:
            unsupported.append(c.claim)
    if unsupported:
        return GuardianCheck(False, f"Not supported by the chunks: {unsupported[0]!r}", rescued)
    others = [c.claim for c in output.claims if c.claim not in rescued]
    if output.verdict != "pass" and not fail_verdict_explained_by(output.reason, rescued, others):
        return GuardianCheck(False, output.reason, rescued)
    return GuardianCheck(True, output.reason, rescued)


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
    early_reason: EscalationReason | None,
    analyst_raw: dict | None,
    responder_raw: dict | None,
    guardian_raw: dict | None,
    retrieved_ids: list[str],
    confidence_threshold: float,
    retrieved_texts: dict[str, str] | None = None,
    rescue_coverage: float | None = None,
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

    check = check_guardian(guardian_raw, retrieved_ids, retrieved_texts, rescue_coverage)
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
