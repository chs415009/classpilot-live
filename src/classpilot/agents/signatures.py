"""DSPy signatures for the live agents. Uncompiled prompt version `uncompiled-v4` (v1
until Stage 12).

The instructions started as the v1 prompts of the Stage 4 baseline (minus the "reply
with JSON" lines: the DSPy adapter defines the output format). Stage 12: the Analyst
sees the retrieved chunks and judges the question's topic; the Responder answers in
2-4 sentences; the Guardian passes rewording, direct conclusions, and short examples
tied to a stated idea (BEHAVIOR 5.3; user decision: same bar as prep).
A compiled program keeps the instructions it was compiled with. Output fields
mirror the pydantic models in `contracts/live.py` (a sync test checks this); the rules
in `rules/question.py` still make every decision.
"""

from typing import Literal

import dspy

from classpilot.contracts import AnalystOutput, GuardianClaim, GuardianOutput, ResponderOutput


class AnalystSignature(dspy.Signature):
    """You help run a class session on this lesson.
    Decide whether the student question is about the subject this lesson teaches. Judge
    the topic of the question, not whether the material answers it in full: later steps
    check the answer and save it for the professor when the material does not cover it.
    - in_scope: about the lesson's subject: a concept, example, or programming idea in
      the objectives or in the lesson material below, or a closely related idea of the
      same subject, even if the material covers it only in part or not at all.
    - out_of_scope: course logistics (exams, grading, deadlines, schedules, recordings,
      office hours), other subjects, tools, or languages the lesson is not about, or
      personal requests and recommendations.
    The lesson material is the best search match from this lesson's slides and
    readings; for an off-topic question it can be unrelated. Link an in-scope question
    to the closest objective."""

    objectives: str = dspy.InputField(desc="lesson objectives, one per line as '- <id>: <title>'")
    chunks: str = dspy.InputField(
        desc="lesson material retrieved for the question, one per line as '[<chunk_id>] <text>'"
    )
    question: str = dspy.InputField(desc="the student question")
    category: Literal["in_scope", "out_of_scope"] = dspy.OutputField()
    objective_id: str | None = dspy.OutputField(desc="id of the linked objective, or null")
    reason: str = dspy.OutputField(desc="one sentence")


class ResponderSignature(dspy.Signature):
    """Answer the student question using ONLY the approved lesson chunks below.
    Cite the chunk ids you used. If the chunks do not answer the question, say so and
    give a low confidence. You may add a short example or comparison that
    illustrates an idea the chunks state, but never a new fact. Answer in 2-4 short
    sentences: no extra background, no repetition. Then check your own answer: is
    every sentence supported by the cited chunks (a short example that illustrates an
    idea they state counts as supported)? Report that as "grounded"."""

    chunks: str = dspy.InputField(desc="lesson chunks, one per line as '[<chunk_id>] <text>'")
    question: str = dspy.InputField(desc="the student question")
    answer_text: str = dspy.OutputField()
    citations: list[str] = dspy.OutputField(desc="chunk ids used in the answer")
    confidence: float = dspy.OutputField(desc="0.0-1.0")
    grounded: bool = dspy.OutputField()


class GuardianSignature(dspy.Signature):
    """You review an answer before a student sees it. The answer may say only what the
    lesson chunks below state, in any words, plus conclusions that follow directly from
    what they state. Use only the chunks, never your own knowledge.

    1. List every factual claim in the answer, each once. A sentence can hold more than
       one claim; list each part, and do not list the whole sentence again after its
       parts. For each claim, give the id of the chunk that supports it, or null:
       - Supported: a chunk states it, in the same or in other words.
       - Supported: a direct conclusion from what the chunks state, adding no new fact
         (for example, from "Silver tables hold cleaned data" and "Gold tables are built
         from Silver tables", the claim "so Gold tables are built from cleaned data").
         Give the id of the chunk the conclusion rests on.
       - Supported: a short example or comparison that illustrates an idea a chunk
         states and adds no new fact (for example, "like a pile of plates" for "last
         in, first out"). Give the id of the chunk with that idea.
       - Not supported (null): any fact, detail, number, or reason that no chunk
         states, even if it is true in general. If you are not sure a chunk supports a
         claim, give null.
       - A chunk that only names or lists a term does not support what the term means,
         does, or checks (for example, a chunk listing "HashMap and TreeMap" does not
         support "a TreeMap keeps its keys sorted"): give null.
       - Sentences that only say what the chunks do not cover are not claims; leave
         them out.
    2. verdict is "pass" only if every claim has a chunk id."""

    chunks: str = dspy.InputField(desc="lesson chunks, one per line as '[<chunk_id>] <text>'")
    question: str = dspy.InputField(desc="the student question")
    answer: str = dspy.InputField(desc="the answer to review")
    claims: list[GuardianClaim] = dspy.OutputField(
        desc="every factual claim once, each with the id of the chunk that supports it, or null"
    )
    verdict: Literal["pass", "fail"] = dspy.OutputField()
    reason: str = dspy.OutputField(desc="one sentence")


# task name -> (signature, pydantic model of its output)
SIGNATURES: dict[str, tuple[type[dspy.Signature], type]] = {
    "analyst": (AnalystSignature, AnalystOutput),
    "responder": (ResponderSignature, ResponderOutput),
    "guardian": (GuardianSignature, GuardianOutput),
}
