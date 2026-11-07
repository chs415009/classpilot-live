"""Labeled question sets for the Stage 9 eval and compile.

A set file holds its lesson (objectives and chunks) next to the questions, so the labels
stay valid when a later prep run changes the lesson's segments:

    {"set_id": "...", "split": "train" | "dev", "retrieval": "inline" | "search",
     "lesson": {"lesson_id": "...", "objectives": [...], "chunks": [...]},
     "questions": [{"id", "objective_id", "question_text", "expected_action",
                    "expected_reason"?, "note"?}, ...]}

`retrieval: inline` ranks the set's own chunks with the word-overlap retriever in every
backend (synthetic lessons are not in Snowflake). `search` uses Cortex Search on the
prep lessons' service in cortex mode. The train set is synthetic and committed
(`eval/questions_train.json`); dev sets on real lessons live in `materials/eval/`
(gitignored), since they hold real course content.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, model_validator

from classpilot.content import Content
from classpilot.settings import PROJECT_ROOT

TRAIN_SET_PATH = PROJECT_ROOT / "eval" / "questions_train.json"
DEV_SET_PATH = PROJECT_ROOT / "materials" / "eval" / "questions_dev.json"

ESCALATION_REASONS = {"out_of_scope", "low_confidence", "unsupported"}


class EvalQuestion(BaseModel):
    id: str
    objective_id: str | None
    question_text: str
    expected_action: Literal["answer", "escalate"]
    expected_reason: str | None = None
    note: str = ""

    @model_validator(mode="after")
    def _reason_matches_action(self):
        if self.expected_action == "escalate" and self.expected_reason not in ESCALATION_REASONS:
            raise ValueError(f"{self.id}: escalate needs one of {sorted(ESCALATION_REASONS)}")
        if self.expected_action == "answer" and self.expected_reason is not None:
            raise ValueError(f"{self.id}: an answer has no expected_reason")
        return self


@dataclass
class QuestionSet:
    set_id: str
    split: str
    retrieval: str
    content: Content
    questions: list[EvalQuestion]
    path: Path


def load_question_set(path: Path) -> QuestionSet:
    data = json.loads(Path(path).read_text())
    if data.get("split") not in ("train", "dev"):
        raise ValueError(f"{path}: split must be train or dev")
    if data.get("retrieval") not in ("inline", "search"):
        raise ValueError(f"{path}: retrieval must be inline or search")
    lesson = data["lesson"]
    lesson_id = lesson["lesson_id"]
    chunks = [{**c, "lesson_id": lesson_id} for c in lesson["chunks"]]
    questions = [EvalQuestion.model_validate(q) for q in data["questions"]]
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate question ids")
    objective_ids = {o["objective_id"] for o in lesson["objectives"]}
    unknown = [q.id for q in questions if q.objective_id and q.objective_id not in objective_ids]
    if unknown:
        raise ValueError(f"{path}: unknown objective_id in {unknown}")
    content = Content(lesson_id, lesson["objectives"], chunks, manifest=None)
    return QuestionSet(data["set_id"], data["split"], data["retrieval"], content, questions, path)


def normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def split_overlap(train: QuestionSet, dev: QuestionSet) -> list[str]:
    """Ids or question texts that appear in both sets (must be empty)."""
    overlap = sorted({q.id for q in train.questions} & {q.id for q in dev.questions})
    texts = {normalized(q.question_text) for q in train.questions}
    overlap += [q.id for q in dev.questions if normalized(q.question_text) in texts]
    if train.split != "train" or dev.split != "dev":
        overlap.append(f"splits are {train.split!r} and {dev.split!r}")
    return overlap
