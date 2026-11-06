"""Outputs of the prep generators and the prep-time Guardian (agent-internal, Stage 6).

These are not interfaces: other parts read only the manifest built from them
(`contracts/manifest.py`). The DSPy signatures in `agents/prep_signatures.py` have the
same output fields (a sync test checks this); the prep rules in `rules/prep.py` check
the structure and make every pass/fail call.
"""

from typing import Literal

from pydantic import BaseModel

OPTION_LETTERS = ("A", "B", "C", "D")


class SegmentDraft(BaseModel):
    slides: list[str]  # slide ids, consecutive, in deck order
    objective: str


class SegmenterOutput(BaseModel):
    segments: list[SegmentDraft]


class ScriptOutput(BaseModel):
    script: str
    citations: list[str]  # chunk ids


class PlacementOutput(BaseModel):
    segment_ids: list[str]  # segments whose end suits a poll, best first
    reason: str


class MisconceptionDraft(BaseModel):
    option: str  # the wrong option that shows this misconception
    label: str
    description: str


class PollOutput(BaseModel):
    question: str
    options: dict[str, str]  # A-D -> option text
    correct_option: str
    misconceptions: list[MisconceptionDraft]  # one per wrong option
    citations: list[str]


class ExplanationOutput(BaseModel):
    title: str
    text: str  # read by TTS while the front end shows `show_slide`
    show_slide: str
    citations: list[str]


class PrepClaim(BaseModel):
    """A claim with the cited chunk that states it and a quote from that chunk. Code
    checks that the quote is in the chunk (Stage 9: false passes); None = not given.

    `kind` (Stage 9, user decision): "fact" must be stated by the chunk; "example" is
    the writer's own example or rewording, and its chunk and quote are the concept it
    illustrates; "framing" is a transition or motivation sentence with no fact, allowed
    without a chunk up to `prep.max_framing_claims`."""

    claim: str
    chunk_id: str | None  # cited chunk that states the claim; None = not supported
    quote: str | None = None
    kind: Literal["fact", "example", "framing"] = "fact"


class PrepGuardianOutput(BaseModel):
    """Scripts and explanations: every factual claim with the cited chunk that states it."""

    claims: list[PrepClaim]
    verdict: Literal["pass", "fail"]
    reason: str


class WrongOptionCheck(BaseModel):
    option: str
    chunk_id: str | None  # cited chunk that shows the option is wrong; None = not shown
    quote: str | None = None  # words of that chunk that show it


class PollGuardianOutput(BaseModel):
    """Polls: claims of the question and correct option, and why each wrong option is wrong."""

    claims: list[PrepClaim]
    wrong_options: list[WrongOptionCheck]
    verdict: Literal["pass", "fail"]
    reason: str
