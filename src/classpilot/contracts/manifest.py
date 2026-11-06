"""Lesson manifest in the team's structure (IMPLEMENTATION_NOTES section 5).

DRAFT until the team agrees (interface_questions.md Q-13). Every existing team field
name is kept; the v2 fields are `params`, `slides`, `correct_option`, `status`,
remediation `text` / `show_slide`, and chunk-id `citations`.

The validator checks the cross-references that pydantic types cannot express, so a
manifest that loads is safe for the poll path to use without further checks.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, model_validator

Status = Literal["ok", "ok_after_retry", "fallback", "dropped"]


class ManifestParams(BaseModel):
    poll_answer_seconds: int = 60
    min_responses: int = 5
    wrong_ratio_threshold: float = 0.60


class Slide(BaseModel):
    order: int
    image_ref: str | None = None
    script: str
    status: Status


class Question(BaseModel):
    text: str
    options: dict[str, str]
    correct_option: str
    known_wrong: dict[str, str]  # wrong option -> misconception id
    segment: str
    status: Status


class Segment(BaseModel):
    segment_id: str  # also the objective id
    objective: str
    slides: list[str]
    questions: dict[str, Question]
    active_poll: str | None


class Misconception(BaseModel):
    label: str
    description: str
    remediation: str  # exactly one remediation id


class Remediation(BaseModel):
    type: Literal["tts_explanation"]
    title: str
    text: str
    show_slide: str
    content_ref: str | None = None
    citations: list[str]  # chunk ids
    status: Status


class Manifest(BaseModel):
    lesson_id: str
    params: ManifestParams = ManifestParams()
    slides: dict[str, Slide]
    segments: list[Segment]
    misconceptions: dict[str, Misconception]
    remediations: dict[str, Remediation]

    @model_validator(mode="after")
    def check_references(self) -> "Manifest":
        errors = manifest_errors(self)
        if errors:
            raise ValueError("; ".join(errors))
        return self

    def find_question(self, poll_id: str) -> tuple[Segment, Question] | None:
        for segment in self.segments:
            if poll_id in segment.questions:
                return segment, segment.questions[poll_id]
        return None


def manifest_errors(m: Manifest) -> list[str]:
    errors: list[str] = []
    segment_ids = [s.segment_id for s in m.segments]
    if len(set(segment_ids)) != len(segment_ids):
        errors.append("segment ids are not unique")

    for seg in m.segments:
        for slide_id in seg.slides:
            if slide_id not in m.slides:
                errors.append(f"{seg.segment_id}: unknown slide {slide_id!r}")

        # A segment without a poll has active_poll null and questions {}. A segment whose
        # polls were all dropped keeps them (status "dropped") with active_poll null.
        if not seg.questions and seg.active_poll is not None:
            errors.append(f"{seg.segment_id}: active_poll set but questions is empty")
        if seg.active_poll is None and any(q.status != "dropped" for q in seg.questions.values()):
            errors.append(f"{seg.segment_id}: active_poll is null but a question is not dropped")
        if seg.active_poll is not None:
            active = seg.questions.get(seg.active_poll)
            if active is None:
                errors.append(f"{seg.segment_id}: active_poll {seg.active_poll!r} not in questions")
            elif active.status == "dropped":
                errors.append(f"{seg.segment_id}: active_poll {seg.active_poll!r} is dropped")

        for qid, q in seg.questions.items():
            where = f"{seg.segment_id}/{qid}"
            if q.segment != seg.segment_id:
                errors.append(f"{where}: segment field is {q.segment!r}")
            for option, mid in q.known_wrong.items():
                if mid not in m.misconceptions:
                    errors.append(f"{where}: option {option} -> unknown misconception {mid!r}")
            if q.status == "dropped":
                # Kept only so the report can count it; the poll path never uses it.
                # It may lack options or misconceptions (the generation that failed).
                continue
            if q.correct_option not in q.options:
                errors.append(f"{where}: correct_option {q.correct_option!r} not in options")
            # A wrong option without an explanation is allowed (Stage 9): if it
            # triggers, the poll path reveals the correct option.
            wrong = set(q.options) - {q.correct_option}
            extra = set(q.known_wrong) - wrong
            if extra:
                errors.append(
                    f"{where}: known_wrong has {sorted(extra)}, wrong options are {sorted(wrong)}"
                )

    owners: dict[str, str] = {}
    for mid, mis in m.misconceptions.items():
        if mis.remediation not in m.remediations:
            errors.append(f"{mid}: unknown remediation {mis.remediation!r}")
        elif mis.remediation in owners:
            errors.append(
                f"{mid}: remediation {mis.remediation!r} already used by {owners[mis.remediation]}"
            )
        else:
            owners[mis.remediation] = mid

    for rid, rem in m.remediations.items():
        if rem.show_slide not in m.slides:
            errors.append(f"{rid}: unknown show_slide {rem.show_slide!r}")
    return errors


def load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate(json.loads(Path(path).read_text()))
