"""Lessons on local disk, jobs in memory (IMPLEMENTATION_NOTES 3).

<data_dir>/
  lessons/<lesson_id>/lesson.json     id, title, uploaded files
  lessons/<lesson_id>/uploads/<name>  the uploaded bytes, under their original name
  lessons/<lesson_id>/prep/           manifest.json, generation_report.json, review.md, slides/
  tables/                             mock-mode prep tables (RAW_FILES, PARSED_PAGES, chunks)
  convert/                            local conversion (PNGs, convert.json) per file hash
  traces.jsonl, decision_log.jsonl    live decisions

Lessons survive a restart; jobs and the poll guard do not (a demo does not need that).
"""

import json
import os
import re
import secrets
import threading
from datetime import UTC, datetime
from pathlib import Path

from classpilot.service.schemas import Job, Lesson, LessonFile

SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


def safe_name(name: str) -> str:
    """The upload's base name with unsafe characters removed (no paths)."""
    base = Path(name.replace("\\", "/")).name
    cleaned = SAFE_NAME.sub("_", base).strip(" .")
    return cleaned or "upload"


def redact(text: str) -> str:
    """Replace the value of every SNOWFLAKE_* environment variable (credentials, account,
    key path) so that no error message or log line carries one."""
    for key, value in os.environ.items():
        if key.startswith("SNOWFLAKE_") and value and len(value) >= 4:
            text = text.replace(value, f"<{key}>")
    return text


class LessonStore:
    def __init__(self, root: Path):
        self.root = root / "lessons"
        self.lock = threading.Lock()

    def dir(self, lesson_id: str) -> Path:
        return self.root / lesson_id

    def prep_dir(self, lesson_id: str) -> Path:
        return self.dir(lesson_id) / "prep"

    def uploads(self, lesson_id: str) -> Path:
        return self.dir(lesson_id) / "uploads"

    def exists(self, lesson_id: str) -> bool:
        return (self.dir(lesson_id) / "lesson.json").is_file()

    def get(self, lesson_id: str) -> Lesson | None:
        path = self.dir(lesson_id) / "lesson.json"
        if not path.is_file():
            return None
        lesson = Lesson.model_validate_json(path.read_text())
        lesson.has_manifest = (self.prep_dir(lesson_id) / "manifest.json").is_file()
        return lesson

    def save(self, lesson: Lesson) -> None:
        path = self.dir(lesson.lesson_id) / "lesson.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(lesson.model_dump_json(indent=2))

    def create(self, lesson_id: str | None, title: str | None) -> Lesson | None:
        """None if the id is taken."""
        with self.lock:
            lesson_id = lesson_id or new_id("lesson")
            if self.exists(lesson_id):
                return None
            lesson = Lesson(
                lesson_id=lesson_id, title=title, created_at=now(), files=[], has_manifest=False
            )
            self.save(lesson)
            return lesson

    def add_file(self, lesson_id: str, entry: LessonFile) -> Lesson:
        """Add or replace (same name or same bytes) a file of the lesson."""
        with self.lock:
            lesson = self.get(lesson_id)
            assert lesson is not None
            lesson.files = [
                f for f in lesson.files if f.name != entry.name and f.file_id != entry.file_id
            ] + [entry]
            self.save(lesson)
            return lesson

    def set_last_job(self, lesson_id: str, job_id: str) -> None:
        with self.lock:
            lesson = self.get(lesson_id)
            if lesson is not None:
                lesson.last_job_id = job_id
                self.save(lesson)

    def known_upload(self, file_id: str) -> bool:
        """The same bytes were uploaded to any lesson before."""
        for path in self.root.glob("*/lesson.json"):
            if any(f["file_id"] == file_id for f in json.loads(path.read_text())["files"]):
                return True
        return False


class JobStore:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def create(self, lesson_id: str, poll_count: int) -> Job | None:
        """None if a job of this lesson is still queued or running."""
        with self.lock:
            if any(
                j.lesson_id == lesson_id and j.status in ("queued", "running")
                for j in self.jobs.values()
            ):
                return None
            job = Job(
                job_id=new_id("job"),
                lesson_id=lesson_id,
                status="queued",
                step="queued",
                steps=["queued"],
                progress={},
                poll_count=poll_count,
                created_at=now(),
            )
            self.jobs[job.job_id] = job
            return job

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def update(self, job_id: str, **fields) -> None:
        with self.lock:
            job = self.jobs[job_id]
            step = fields.get("step")
            if step and step != job.step:
                job.steps.append(step)
            for key, value in fields.items():
                setattr(job, key, value)
