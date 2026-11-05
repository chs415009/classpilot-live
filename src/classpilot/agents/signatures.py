"""DSPy signatures for the live agents. Uncompiled (prompt version `uncompiled-v1`).

The instructions are the v1 prompts that produced the Stage 4 baseline, minus the
"reply with JSON" lines: the DSPy adapter now defines the output format. Output fields
mirror the pydantic models in `contracts/live.py` (a sync test checks this); the rules
in `rules/question.py` still make every decision.
"""

from typing import Literal

import dspy

from classpilot.contracts import AnalystOutput, GuardianClaim, GuardianOutput, ResponderOutput


class AnalystSignature(dspy.Signature):
    """You help run a class session on this lesson.
    Classify the student question into exactly one category:
    - in_scope: about the lesson objectives below
    - out_of_scope: not about this lesson (logistics, other topics, personal requests)
    - assignment_like: asks for answers to graded work (assignments, homework, quizzes)"""

    objectives: str = dspy.InputField(desc="lesson objectives, one per line as '- <id>: <title>'")
    question: str = dspy.InputField(desc="the student question")
    category: Literal["in_scope", "out_of_scope", "assignment_like"] = dspy.OutputField()
    objective_id: str | None = dspy.OutputField(desc="id of the linked objective, or null")
    reason: str = dspy.OutputField(desc="one sentence")


class ResponderSignature(dspy.Signature):
    """Answer the student question using ONLY the approved lesson chunks below.
    Cite the chunk ids you used. If the chunks do not answer the question, say so and
    give a low confidence. Then check your own answer: is every sentence supported by
    the cited chunks? Report that as "grounded"."""

    chunks: str = dspy.InputField(desc="lesson chunks, one per line as '[<chunk_id>] <text>'")
    question: str = dspy.InputField(desc="the student question")
    answer_text: str = dspy.OutputField()
    citations: list[str] = dspy.OutputField(desc="chunk ids used in the answer")
    confidence: float = dspy.OutputField(desc="0.0-1.0")
    grounded: bool = dspy.OutputField()


class GuardianSignature(dspy.Signature):
    """You review an answer before a student sees it. Be strict: if you are not sure
    a claim is supported, treat it as not supported.

    1. List every factual claim in the answer. A sentence can hold more than one claim;
       list each one. For each claim, give the id of the cited chunk that directly states
       it, or null if no cited chunk states it.
       - Only the cited chunks count. Do not use your own knowledge.
       - A claim that is true in general but not stated in the cited chunks is not
         supported.
       - A chunk that only names a term, without explaining it, does not support an
         explanation of that term.
       - Sentences that only say what the chunks do not cover are not claims; leave
         them out.
    2. Set reveals_graded_work to true if the answer gives finished code or SQL, or a
       complete solution to an assignment, homework or quiz-style task (for example the
       exact tests to add to a specific model).
    3. verdict is "pass" only if every claim has a chunk id and reveals_graded_work is
       false."""

    chunks: str = dspy.InputField(desc="cited chunks, one per line as '[<chunk_id>] <text>'")
    question: str = dspy.InputField(desc="the student question")
    answer: str = dspy.InputField(desc="the answer to review")
    claims: list[GuardianClaim] = dspy.OutputField()
    reveals_graded_work: bool = dspy.OutputField()
    verdict: Literal["pass", "fail"] = dspy.OutputField()
    reason: str = dspy.OutputField(desc="one sentence")


# task name -> (signature, pydantic model of its output)
SIGNATURES: dict[str, tuple[type[dspy.Signature], type]] = {
    "analyst": (AnalystSignature, AnalystOutput),
    "responder": (ResponderSignature, ResponderOutput),
    "guardian": (GuardianSignature, GuardianOutput),
}
