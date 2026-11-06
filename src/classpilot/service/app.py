"""The ClassPilot service: prep, live, and export endpoints (IMPLEMENTATION_NOTES 3).

    uvicorn classpilot.service.app:create_app --factory --port 8000

Shapes: `service/schemas.py` and `contracts/` (interface_questions.md Q-18, Q-19, Q-22).
Backend (mock or cortex) from `config/settings.yaml` / BACKEND; credentials only from
the service's `.env`, and never in a response.
"""

import hashlib
import os
import re
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from classpilot.contracts import Decision, PollEvidence, StudentQuestion
from classpilot.live.poll import PollInputError, run_poll
from classpilot.live.question_graph import Deps, run_question
from classpilot.service.context import ServiceContext
from classpilot.service.exports import lesson_bundle, session_export
from classpilot.service.schemas import (
    ErrorBody,
    FileKindIn,
    Job,
    JobCreated,
    Lesson,
    LessonCreate,
    LessonFile,
    ProcessRequest,
)
from classpilot.service.store import now, safe_name
from classpilot.settings import Settings, load_settings

ALLOWED = {"slides": {"pptx", "pdf"}, "reference": {"pdf", "docx"}}
MAGIC = {"pdf": b"%PDF-", "pptx": b"PK\x03\x04", "docx": b"PK\x03\x04"}
CHUNK = 1024 * 1024
SLIDE_ID = re.compile(r"^[a-z0-9-]+-p\d{2,}$")
ERRORS = {404: {"model": ErrorBody}, 409: {"model": ErrorBody}, 422: {"model": ErrorBody}}


def create_app(
    settings: Settings | None = None, data_dir: Path | None = None, backends=None
) -> FastAPI:
    settings = settings or load_settings()
    ctx = ServiceContext.build(settings, data_dir, backends)
    app = FastAPI(title="ClassPilot Live service", version="0.2.0")
    app.state.ctx = ctx
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.service.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def lesson_or_404(lesson_id: str) -> Lesson:
        lesson = ctx.lessons.get(lesson_id)
        if lesson is None:
            raise HTTPException(404, f"lesson {lesson_id!r} not found")
        return lesson

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "backend": settings.backend}

    # ---------- prep ----------

    @app.post("/lessons", status_code=201, response_model=Lesson, responses=ERRORS)
    def create_lesson(body: LessonCreate | None = None) -> Lesson:
        body = body or LessonCreate()
        lesson = ctx.lessons.create(body.lesson_id, body.title)
        if lesson is None:
            raise HTTPException(409, f"lesson {body.lesson_id!r} already exists")
        return lesson

    @app.get("/lessons/{lesson_id}", response_model=Lesson, responses=ERRORS)
    def get_lesson(lesson_id: str) -> Lesson:
        return lesson_or_404(lesson_id)

    @app.post(
        "/lessons/{lesson_id}/files",
        status_code=201,
        response_model=LessonFile,
        responses={**ERRORS, 413: {"model": ErrorBody}, 415: {"model": ErrorBody}},
    )
    async def upload_file(
        lesson_id: str,
        kind: Annotated[FileKindIn, Form()],
        file: Annotated[UploadFile, File()],
    ) -> LessonFile:
        lesson_or_404(lesson_id)
        name = safe_name(file.filename or "")
        fmt = Path(name).suffix.lower().lstrip(".")
        if fmt not in ALLOWED[kind]:
            allowed = ", ".join(sorted(ALLOWED[kind]))
            raise HTTPException(415, f"{kind} must be {allowed}; got {name!r}")

        # Stream to a temporary file: size limit and hash before anything else.
        limit = settings.service.max_upload_mb * 1024 * 1024
        uploads = ctx.lessons.uploads(lesson_id)
        uploads.mkdir(parents=True, exist_ok=True)
        tmp = uploads / f".incoming-{os.getpid()}-{id(file)}"
        digest, size, head = hashlib.sha256(), 0, b""
        try:
            with tmp.open("wb") as out:
                while chunk := await file.read(CHUNK):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(
                            413, f"{name!r} is over {settings.service.max_upload_mb} MB"
                        )
                    head = head or chunk[:8]
                    digest.update(chunk)
                    out.write(chunk)
            if not head.startswith(MAGIC[fmt]):
                raise HTTPException(415, f"{name!r} is not a valid {fmt} file")
            file_id = digest.hexdigest()
            reused = ctx.lessons.known_upload(file_id) or (
                ctx.backends.tables().known_file(file_id) is not None
            )
            tmp.replace(uploads / name)
        finally:
            tmp.unlink(missing_ok=True)
        entry = LessonFile(
            file_id=file_id, name=name, kind=kind, format=fmt, size_bytes=size, reused=reused
        )
        ctx.lessons.add_file(lesson_id, entry)
        ctx.forget_lesson(lesson_id)
        return entry

    @app.post(
        "/lessons/{lesson_id}/process",
        status_code=202,
        response_model=JobCreated,
        responses=ERRORS,
    )
    def process_lesson(
        lesson_id: str, background: BackgroundTasks, body: ProcessRequest | None = None
    ) -> JobCreated:
        lesson = lesson_or_404(lesson_id)
        if not any(f.kind == "slides" for f in lesson.files):
            raise HTTPException(409, f"lesson {lesson_id!r} has no slides yet")
        requested = body.poll_count if body else None
        poll_count = settings.prep.poll_count if requested is None else requested
        job = ctx.jobs.create(lesson_id, poll_count)
        if job is None:
            raise HTTPException(409, f"lesson {lesson_id!r} is already being processed")
        ctx.lessons.set_last_job(lesson_id, job.job_id)
        background.add_task(ctx.run_job, job.job_id)
        return JobCreated(job_id=job.job_id, lesson_id=lesson_id, status=job.status)

    @app.get("/jobs/{job_id}", response_model=Job, responses=ERRORS)
    def get_job(job_id: str) -> Job:
        job = ctx.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"job {job_id!r} not found")
        return job

    @app.get("/lessons/{lesson_id}/manifest", responses=ERRORS)
    def get_manifest(lesson_id: str) -> FileResponse:
        lesson_or_404(lesson_id)
        path = ctx.lessons.prep_dir(lesson_id) / "manifest.json"
        if not path.is_file():
            raise HTTPException(404, f"lesson {lesson_id!r} has no manifest yet")
        return FileResponse(path, media_type="application/json")

    @app.get(
        "/lessons/{lesson_id}/slides/{slide_id}",
        responses={**ERRORS, 200: {"content": {"image/png": {}}}},
    )
    def get_slide(lesson_id: str, slide_id: str) -> FileResponse:
        lesson_or_404(lesson_id)
        slide_id = slide_id.removesuffix(".png")
        path = ctx.lessons.prep_dir(lesson_id) / "slides" / f"{slide_id}.png"
        if not SLIDE_ID.match(slide_id) or not path.is_file():
            raise HTTPException(404, f"slide {slide_id!r} not found in lesson {lesson_id!r}")
        return FileResponse(path, media_type="image/png")

    @app.get(
        "/lessons/{lesson_id}/bundle",
        responses={**ERRORS, 200: {"content": {"application/zip": {}}}},
    )
    def get_bundle(lesson_id: str) -> Response:
        """manifest.json + slides/*.png in one zip, to fetch once before class (Q-18)."""
        lesson_or_404(lesson_id)
        prep_dir = ctx.lessons.prep_dir(lesson_id)
        if not (prep_dir / "manifest.json").is_file():
            raise HTTPException(404, f"lesson {lesson_id!r} has no manifest yet")
        return Response(
            lesson_bundle(prep_dir),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{lesson_id}.zip"'},
        )

    # ---------- live ----------

    @app.post("/questions", response_model=Decision, responses=ERRORS)
    def post_question(question: StudentQuestion) -> Decision:
        content = ctx.live_content(question.lesson_id)
        if content is None:
            raise HTTPException(404, f"lesson {question.lesson_id!r} has no manifest")
        key = (question.session_id, question.event_id)
        with ctx.question_lock(key):  # a repeated event_id gets the first decision (Q-19)
            if key in ctx.question_decisions:
                return ctx.question_decisions[key]
            deps = Deps(settings, content, ctx.live_llm(), ctx.backends.live_retriever(content))
            output = run_question(question, deps)  # LLM errors and timeouts escalate inside
            ctx.write_run(output)
            ctx.question_decisions[key] = output.decision
        return output.decision

    @app.post("/polls/result", response_model=Decision, responses=ERRORS)
    def post_poll_result(evidence: PollEvidence) -> Decision:
        manifest = ctx.manifest(evidence.lesson_id)
        if manifest is None:
            raise HTTPException(404, f"lesson {evidence.lesson_id!r} has no manifest")
        found = manifest.find_question(evidence.poll_id)
        if found is None or found[1].status == "dropped":
            raise HTTPException(404, f"poll {evidence.poll_id!r} is not an active poll")
        key = (evidence.session_id, evidence.poll_id)
        with ctx.lock:  # a poll triggers at most once (Q-14)
            if key in ctx.poll_decisions:
                return ctx.poll_decisions[key]
            try:
                output = run_poll(evidence, manifest, settings.backend)
            except PollInputError as exc:
                raise HTTPException(422, str(exc)) from exc
            ctx.poll_decisions[key] = output.decision
        ctx.write_run(output)
        return output.decision

    # ---------- after class ----------

    @app.get(
        "/sessions/{session_id}/export",
        responses={**ERRORS, 200: {"content": {"application/zip": {}}}},
    )
    def get_session_export(session_id: str) -> Response:
        """The session's trace records, decision log, and lesson manifests (Q-22)."""
        with ctx.lock:  # no half-written line while reading
            result = session_export(
                session_id, ctx.trace_path, ctx.log_path, ctx.lessons.prep_dir, now()
            )
        if result is None:
            raise HTTPException(404, f"session {session_id!r} has no decisions")
        data, _ = result
        safe = safe_name(session_id)
        return Response(
            data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{safe}.zip"'},
        )

    return app
