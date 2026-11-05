"""Path A rules: poll threshold, explain/reveal, and the explanation lookup."""

from dataclasses import dataclass
from typing import Literal

from classpilot.contracts import PollEvidence
from classpilot.contracts.manifest import Manifest, Question


@dataclass
class ThresholdResult:
    triggered: bool
    top_wrong_option: str | None
    wrong_share: float  # top wrong option count / answers received


def check_poll_threshold(
    evidence: PollEvidence, min_responses: int, wrong_ratio_threshold: float
) -> ThresholdResult:
    wrong_counts = {
        option: count
        for option, count in evidence.option_counts.items()
        if option != evidence.correct_option
    }
    if evidence.answers_received <= 0 or not wrong_counts:
        return ThresholdResult(False, None, 0.0)

    top_option = max(wrong_counts, key=lambda option: wrong_counts[option])
    share = wrong_counts[top_option] / evidence.answers_received
    triggered = evidence.answers_received >= min_responses and share >= wrong_ratio_threshold
    return ThresholdResult(triggered, top_option, share)


@dataclass
class PollOutcome:
    action: Literal["explain", "reveal"]
    option: str | None = None  # the wrong option to explain


def decide_poll(threshold: ThresholdResult) -> PollOutcome:
    if threshold.triggered:
        return PollOutcome("explain", threshold.top_wrong_option)
    return PollOutcome("reveal")


@dataclass
class Explanation:
    misconception_id: str
    remediation_id: str
    text: str
    show_slide: str


def lookup_explanation(manifest: Manifest, question: Question, option: str) -> Explanation | None:
    """known_wrong[option] -> misconception -> remediation. None if any link is missing
    (a validated manifest always has them; the caller then reveals instead)."""
    misconception_id = question.known_wrong.get(option)
    misconception = manifest.misconceptions.get(misconception_id) if misconception_id else None
    if misconception is None:
        return None
    remediation = manifest.remediations.get(misconception.remediation)
    if remediation is None:
        return None
    return Explanation(
        misconception_id, misconception.remediation, remediation.text, remediation.show_slide
    )
