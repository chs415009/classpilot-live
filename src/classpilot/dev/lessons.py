"""Lesson folders for the dev report and their fixed test questions (Stage 10).

materials/lessons/<lesson_id>/      (gitignored: real course content)
  slides/               *.pptx | *.pdf
  refs/                 *.pdf | *.docx
  test_questions.json   hand-written test questions (LessonQuestionSet)
  lesson.yaml           optional: title, poll_count

Test questions are written by hand from the lesson's materials and stay fixed, so runs
can be compared. Code checks only their format.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from classpilot.contracts.live import EscalationReason
from classpilot.settings import PROJECT_ROOT

LESSONS_DIR = PROJECT_ROOT / "materials" / "lessons"
QUESTIONS_FILE = "test_questions.json"
SLIDE_SUFFIXES = {".pptx", ".pdf"}
REF_SUFFIXES = {".pdf", ".docx"}

Category = Literal["direct", "reworded", "partial", "out_of_scope"]
CATEGORIES: tuple[str, ...] = Category.__args__


class LessonError(Exception):
    pass


class LessonQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    category: Category
    question_text: str
    expected_action: Literal["answer", "escalate"]
    accepted_reasons: list[EscalationReason] = []  # escalation reasons that count as a match
    sources: list[str] = []  # chunk ids an answer should cite (reference only)
    why: str

    @model_validator(mode="after")
    def reasons_fit_action(self):
        if self.expected_action == "escalate" and not self.accepted_reasons:
            raise ValueError(f"{self.question_id}: escalate needs accepted_reasons")
        if self.expected_action == "answer" and self.accepted_reasons:
            raise ValueError(f"{self.question_id}: answer takes no accepted_reasons")
        if not self.question_text.strip():
            raise ValueError(f"{self.question_id}: empty question_text")
        return self


class LessonQuestionSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lesson_id: str
    note: str = ""
    questions: list[LessonQuestion]

    @model_validator(mode="after")
    def unique_ids(self):
        if not self.questions:
            raise ValueError("no questions")
        ids = [q.question_id for q in self.questions]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate question_id: {', '.join(dupes)}")
        return self


def load_questions(path: Path, lesson_id: str | None = None) -> LessonQuestionSet:
    try:
        qset = LessonQuestionSet.model_validate_json(path.read_text())
    except (OSError, ValidationError) as exc:
        raise LessonError(f"{path}: {exc}") from exc
    if lesson_id is not None and qset.lesson_id != lesson_id:
        raise LessonError(f"{path}: lesson_id {qset.lesson_id!r}, expected {lesson_id!r}")
    return qset


@dataclass
class LessonFolder:
    lesson_id: str
    path: Path
    title: str | None
    poll_count: int | None
    slides: list[Path]
    refs: list[Path]

    @property
    def questions_path(self) -> Path:
        return self.path / QUESTIONS_FILE


def _files(folder: Path, suffixes: set[str]) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in suffixes)


def load_lesson(lesson_id: str, root: Path = LESSONS_DIR) -> LessonFolder:
    path = root / lesson_id
    if not path.is_dir():
        raise LessonError(f"no lesson folder {path}")
    meta: dict = {}
    meta_path = path / "lesson.yaml"
    if meta_path.is_file():
        meta = yaml.safe_load(meta_path.read_text()) or {}
        if not isinstance(meta, dict):
            raise LessonError(f"{meta_path}: expected a mapping")
    poll_count = meta.get("poll_count")
    if poll_count is not None and (not isinstance(poll_count, int) or poll_count < 0):
        raise LessonError(f"{meta_path}: poll_count must be a whole number >= 0")
    folder = LessonFolder(
        lesson_id=lesson_id,
        path=path,
        title=meta.get("title"),
        poll_count=poll_count,
        slides=_files(path / "slides", SLIDE_SUFFIXES),
        refs=_files(path / "refs", REF_SUFFIXES),
    )
    if not folder.slides:
        raise LessonError(f"{path / 'slides'}: no .pptx or .pdf file")
    return folder


def list_lessons(root: Path = LESSONS_DIR) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
