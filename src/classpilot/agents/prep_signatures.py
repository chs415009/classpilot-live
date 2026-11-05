"""DSPy signatures for prep-time generation and the prep Guardian (Stage 6, uncompiled).

Generators: Segmenter, ScriptWriter, PollPlacer, PollWriter, ExplanationWriter. Every
generator takes a `feedback` input: "(none)" on the first attempt, then the problems
the structure checks and the Guardian found (`rules/prep.py`). The retry loop is code
(`prep/generate.py`), not DSPy.

ScriptWriter, PollWriter, and ExplanationWriter cite chunk ids, and their Guardian sees
only the cited chunks (IMPLEMENTATION_NOTES 7.4). Segmenter and PollPlacer produce
structure, not text for students: they refer to slide and segment ids, and no Guardian
checks them; code checks their structure.

The prep Guardian has one signature per item type, because each type has its own rule
(scripts: transitions are not claims; polls: each wrong option shown wrong;
explanations: every claim supported). The live Guardian (`signatures.py`) is unchanged.
Output fields mirror the pydantic models in `contracts/prep.py` (a sync test checks this).
"""

from typing import Literal

import dspy

from classpilot.contracts.live import GuardianClaim
from classpilot.contracts.prep import (
    ExplanationOutput,
    MisconceptionDraft,
    PlacementOutput,
    PollGuardianOutput,
    PollOutput,
    PrepGuardianOutput,
    ScriptOutput,
    SegmentDraft,
    SegmenterOutput,
    WrongOptionCheck,
)

CHUNKS_DESC = "lesson chunks, one per line as '[<chunk_id>] (<slide id> or reference) <text>'"
FEEDBACK_DESC = "problems with your previous answer that you must fix, or '(none)'"


class SegmenterSignature(dspy.Signature):
    """You plan a class session from the professor's slides. Split the deck into
    segments: runs of consecutive slides that teach one learning objective.
    - Every slide belongs to exactly one segment. Keep the deck order.
    - A segment usually has 2 to 5 slides. A title or agenda slide joins the segment
      that follows it.
    - Write each objective as one sentence that starts with a verb and names what a
      student can do afterwards (for example "Explain why the Bronze layer keeps raw
      data unchanged").
    - Base the objectives only on the slide content given.
    - If feedback is given, your previous answer had these problems; fix all of them."""

    slides: str = dspy.InputField(
        desc="the deck in order: a '[<slide_id>]' line per slide, then its chunks"
    )
    feedback: str = dspy.InputField(desc=FEEDBACK_DESC)
    segments: list[SegmentDraft] = dspy.OutputField(desc="in deck order; slides as slide ids")


class ScriptWriterSignature(dspy.Signature):
    """You write what the class assistant says aloud while one slide is on screen.
    The professor is not in the room; a text-to-speech voice reads your script.
    - Teach this slide's content in 2 to 5 short spoken sentences, in service of the
      segment objective.
    - Use only facts stated in the chunks given; do not add facts from your own
      knowledge. Cite the ids of the chunks you used.
    - You may add a short transition (for example "Next, let's look at how data moves")
      that states no facts.
    - Plain spoken English only: no Markdown, bullets, backticks, or code. Spell out
      code and symbols in words (say "order id" for order_id and "dot s q l" for .sql),
      and describe what code does instead of reading it out.
    - If feedback is given, your previous script had these problems; fix all of them."""

    objective: str = dspy.InputField(desc="the objective of the segment this slide is in")
    slide: str = dspy.InputField(desc="the slide id and its position in the deck and segment")
    chunks: str = dspy.InputField(desc=CHUNKS_DESC)
    feedback: str = dspy.InputField(desc=FEEDBACK_DESC)
    script: str = dspy.OutputField()
    citations: list[str] = dspy.OutputField(desc="chunk ids the script relies on")


class PollPlacerSignature(dspy.Signature):
    """You choose where to place in-class polls. A poll comes at the end of a segment and
    checks that segment's objective with one multiple-choice question.
    - Return the ids of the segments whose content suits such a question, best first.
      Name each segment at most once. Leave out segments with nothing to test, such as a
      title or agenda segment.
    - Name up to poll_count segments first, then any other suitable segments as backups,
      still best first. A backup is used only when a poll cannot be written.
    - Prefer polls spread across the lesson. A poll after the last slide is allowed.
    - If feedback is given, your previous answer had these problems; fix all of them."""

    segments: str = dspy.InputField(
        desc="one per line as '- <segment_id> (slides <first>..<last>): <objective>'"
    )
    poll_count: int = dspy.InputField(desc="the number of polls wanted")
    feedback: str = dspy.InputField(desc=FEEDBACK_DESC)
    segment_ids: list[str] = dspy.OutputField(desc="segment ids, best first")
    reason: str = dspy.OutputField(desc="one sentence")


class PollWriterSignature(dspy.Signature):
    """You write one multiple-choice poll that checks the segment objective. Students
    answer it on their phones during class.
    - Use only facts stated in the chunks given. Cite every chunk id that the question
      and its options rely on.
    - Exactly 4 options keyed A, B, C, D, with exactly one correct option. Do not always
      put the correct option first.
    - The question and the correct option must be stated in the chunks. Each wrong
      option must be clearly wrong according to the chunks (they state something that
      contradicts it), not merely unmentioned.
    - Each wrong option shows one specific misconception a student might have. For
      every wrong option, give that misconception: a short label and one sentence that
      describes the mistaken belief.
    - Keep the question and the options short and plain: no Markdown or code.
    - If feedback is given, your previous poll had these problems; fix all of them."""

    objective: str = dspy.InputField(desc="the segment objective the poll checks")
    chunks: str = dspy.InputField(desc=CHUNKS_DESC)
    feedback: str = dspy.InputField(desc=FEEDBACK_DESC)
    question: str = dspy.OutputField()
    options: dict[str, str] = dspy.OutputField(desc="keys A, B, C, D -> option text")
    correct_option: str = dspy.OutputField(desc="A, B, C, or D")
    misconceptions: list[MisconceptionDraft] = dspy.OutputField(
        desc="one per wrong option, with that option's key"
    )
    citations: list[str] = dspy.OutputField(desc="chunk ids the poll relies on")


class ExplanationWriterSignature(dspy.Signature):
    """Many students picked the same wrong option in a class poll. Write the short
    explanation that the class assistant reads aloud while one slide is shown; after it,
    the correct option is revealed.
    - Address the misconception behind the chosen option: say why it is wrong and what
      the lesson says instead, in 2 to 4 short spoken sentences.
    - Use only facts stated in the chunks given. Cite the ids of the chunks you used,
      including at least one slide chunk.
    - show_slide is the slide id of one cited slide chunk that best shows the right idea.
    - Do not say the letter of the correct option; it is revealed after you.
    - Plain spoken English only: no Markdown, bullets, backticks, or code. Spell out
      code and symbols in words (say "order id" for order_id and "dot s q l" for .sql),
      and describe what code does instead of reading it out.
    - title names the idea in a few words (for the post-class report).
    - If feedback is given, your previous explanation had these problems; fix all of
      them."""

    question: str = dspy.InputField(desc="the poll question")
    options: str = dspy.InputField(desc="the options, one per line as '<key>: <text>'")
    correct_option: str = dspy.InputField(desc="key of the correct option")
    wrong_option: str = dspy.InputField(desc="key of the wrong option the students picked")
    misconception: str = dspy.InputField(desc="'<label>: <description>' of that option")
    chunks: str = dspy.InputField(desc=CHUNKS_DESC)
    feedback: str = dspy.InputField(desc=FEEDBACK_DESC)
    title: str = dspy.OutputField()
    text: str = dspy.OutputField()
    show_slide: str = dspy.OutputField(desc="slide id of a cited slide chunk")
    citations: list[str] = dspy.OutputField(desc="chunk ids the explanation relies on")


class ScriptGuardianSignature(dspy.Signature):
    """You check a script that a text-to-speech voice reads to students while a
    slide is shown. Be strict: if you are not sure a claim is supported, treat it as not
    supported.
    1. List every factual claim in the script. A sentence can hold more than one claim;
       list each one.
       For each claim, give the id of the cited chunk that directly states it, or null
       if no cited chunk states it.
       - Only the cited chunks count. Do not use your own knowledge.
       - A claim that is true in general but not stated in the cited chunks is not
         supported.
       - A chunk that only names a term, without explaining it, does not support an
         explanation of that term.
       - Transitions and sign-posts ("Next, let's look at ...", "Let's recap") state no
         facts; they are not claims, so leave them out.
    2. verdict is "pass" only if every claim has a chunk id."""

    chunks: str = dspy.InputField(desc="cited chunks, one per line as '[<chunk_id>] <text>'")
    script: str = dspy.InputField(desc="the script to check")
    claims: list[GuardianClaim] = dspy.OutputField(
        desc="every factual claim, each with the id of the cited chunk that states it, or null"
    )
    verdict: Literal["pass", "fail"] = dspy.OutputField()
    reason: str = dspy.OutputField(desc="one sentence")


class PollGuardianSignature(dspy.Signature):
    """You check a multiple-choice poll before students see it. Be strict: if you
    are not sure, treat it as not supported.
    1. List the factual claims that the question and its correct option make: what the
       question assumes, and that the correct option answers it.
       For each claim, give the id of the cited chunk that directly states it, or null
       if no cited chunk states it.
       - Only the cited chunks count. Do not use your own knowledge.
       - A claim that is true in general but not stated in the cited chunks is not
         supported.
       - A chunk that only names a term, without explaining it, does not support an
         explanation of that term.
    2. For every wrong option, give the id of the cited chunk that shows it is wrong
       (the chunk states something that contradicts it), or null. An option that the
       chunks only fail to mention is not shown wrong. An option that could also be
       argued to be correct is not shown wrong.
    3. verdict is "pass" only if every claim and every wrong option has a chunk id."""

    chunks: str = dspy.InputField(desc="cited chunks, one per line as '[<chunk_id>] <text>'")
    question: str = dspy.InputField(desc="the poll question")
    options: str = dspy.InputField(desc="the options, one per line as '<key>: <text>'")
    correct_option: str = dspy.InputField(desc="key of the correct option")
    claims: list[GuardianClaim] = dspy.OutputField(
        desc="claims of the question and correct option, each with a chunk id or null"
    )
    wrong_options: list[WrongOptionCheck] = dspy.OutputField(
        desc="one per wrong option: the chunk id that shows it is wrong, or null"
    )
    verdict: Literal["pass", "fail"] = dspy.OutputField()
    reason: str = dspy.OutputField(desc="one sentence")


class ExplanationGuardianSignature(dspy.Signature):
    """You check an explanation that a text-to-speech voice reads to students after
    they picked a wrong option in a poll. Be strict: if you are not sure a claim is
    supported, treat it as not supported.
    1. List every factual claim in the explanation. A sentence can hold more than one
       claim; list each one.
       For each claim, give the id of the cited chunk that directly states it, or null
       if no cited chunk states it.
       - Only the cited chunks count. Do not use your own knowledge.
       - A claim that is true in general but not stated in the cited chunks is not
         supported.
       - A chunk that only names a term, without explaining it, does not support an
         explanation of that term.
       - Sentences that only refer to the poll ("Many of you chose this option", "The
         answer comes next") are not claims; leave them out.
    2. verdict is "pass" only if every claim has a chunk id."""

    chunks: str = dspy.InputField(desc="cited chunks, one per line as '[<chunk_id>] <text>'")
    question: str = dspy.InputField(desc="the poll question")
    wrong_option: str = dspy.InputField(desc="'<key>: <text>' of the option the students picked")
    explanation: str = dspy.InputField(desc="the explanation to check")
    claims: list[GuardianClaim] = dspy.OutputField(
        desc="every factual claim, each with the id of the cited chunk that states it, or null"
    )
    verdict: Literal["pass", "fail"] = dspy.OutputField()
    reason: str = dspy.OutputField(desc="one sentence")


# task name -> (signature, pydantic model of its output)
PREP_SIGNATURES: dict[str, tuple[type[dspy.Signature], type]] = {
    "segmenter": (SegmenterSignature, SegmenterOutput),
    "script_writer": (ScriptWriterSignature, ScriptOutput),
    "poll_placer": (PollPlacerSignature, PlacementOutput),
    "poll_writer": (PollWriterSignature, PollOutput),
    "explanation_writer": (ExplanationWriterSignature, ExplanationOutput),
    "script_guardian": (ScriptGuardianSignature, PrepGuardianOutput),
    "poll_guardian": (PollGuardianSignature, PollGuardianOutput),
    "explanation_guardian": (ExplanationGuardianSignature, PrepGuardianOutput),
}
GENERATORS = ("segmenter", "script_writer", "poll_placer", "poll_writer", "explanation_writer")
