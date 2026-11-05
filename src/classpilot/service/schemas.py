"""Request and response shapes of the service API (interface_questions.md Q-18, Q-19).

The live endpoints take and return the contracts in `contracts/live.py`
(StudentQuestion, PollEvidence, Decision); the manifest is `contracts/manifest.py`.
"""

from typing import Literal

from pydantic import BaseModel, Field

FileKindIn = Literal["slides", "reference"]
JobStatus = Literal["queued", "running", "done", "failed"]
JobStep = Literal[
    "queued",
    "converting",
    "uploading",
    "parsing",
    "chunking",
    "generating",
    "checking",
    "assembling",
    "done",
    "failed",
]
LESSON_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"


class LessonCreate(BaseModel):
    lesson_id: str | None = Field(default=None, pattern=LESSON_ID_PATTERN)
    title: str | None = None


class LessonFile(BaseModel):
    file_id: str  # SHA-256 of the bytes
    name: str
    kind: FileKindIn
    format: Literal["pptx", "pdf", "docx"]
    size_bytes: int
    reused: bool  # the same bytes were parsed before (any lesson): no parse cost


class Lesson(BaseModel):
    lesson_id: str
    title: str | None
    created_at: str
    files: list[LessonFile]
    has_manifest: bool
    last_job_id: str | None = None


class ProcessRequest(BaseModel):
    poll_count: int | None = Field(default=None, ge=0, le=20)


class JobCreated(BaseModel):
    job_id: str
    lesson_id: str
    status: JobStatus


class Progress(BaseModel):
    done: int = 0
    total: int = 0
    detail: str = ""


class ItemFailure(BaseModel):
    item: str  # "script <slide_id>", "poll q-01 seg-02", "explanation q-01 B", ...
    status: Literal["fallback", "dropped"]
    detail: str  # fallback level or drop reason
    problems: list[str]  # of the last attempt


class Job(BaseModel):
    job_id: str
    lesson_id: str
    status: JobStatus
    step: JobStep
    steps: list[JobStep]  # every step reached, in order
    progress: Progress
    poll_count: int
    failures: list[ItemFailure] = []
    error: str | None = None
    created_at: str
    started_at: str | None = None
    ended_at: str | None = None
    llm_calls: int | None = None


class ErrorBody(BaseModel):
    detail: str
