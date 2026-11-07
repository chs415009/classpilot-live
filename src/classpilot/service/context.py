"""Everything the endpoints share: settings, stores, backends, live lesson cache, poll guard."""

import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from classpilot.adapters.llm import LLMClient
from classpilot.adapters.retrieval import Retriever
from classpilot.content import Content, lesson_content
from classpilot.contracts import Decision
from classpilot.contracts.manifest import Manifest, load_manifest
from classpilot.contracts.trace import DecisionLogEntry
from classpilot.prep.generate import GenerateDeps, Generator, LessonMaterial, load_material
from classpilot.prep.outputs import check_and_review, copy_slide_images, write_generation
from classpilot.prep.parse import ParseDeps, parse_lesson
from classpilot.prep.tables import PrepTables
from classpilot.service.schemas import ItemFailure, Progress
from classpilot.service.store import JobStore, LessonStore, now, redact
from classpilot.settings import PROJECT_ROOT, Settings
from classpilot.trace import RunOutput, write_run


@dataclass
class Backends:
    """Adapter factories. The defaults follow `settings.backend`; tests replace them."""

    parse_deps: Callable[[], ParseDeps]
    generate_deps: Callable[[Settings, LessonMaterial], GenerateDeps]
    tables: Callable[[], PrepTables]
    live_llm: Callable[[], LLMClient]
    live_retriever: Callable[[Content], Retriever]


def default_backends(settings: Settings, data_dir: Path) -> Backends:
    from classpilot.prep.backends import make_generate_deps, make_parse_deps, make_tables

    tables_dir, convert_dir = data_dir / "tables", data_dir / "convert"

    def live_llm() -> LLMClient:
        if settings.backend == "cortex":
            from classpilot.agents.compiled import cortex_live_agents

            return cortex_live_agents(settings)
        from classpilot.adapters.llm import MockLLM

        return MockLLM()

    def live_retriever(content: Content) -> Retriever:
        from classpilot.adapters.retrieval import CortexSearchRetriever, MockRetriever

        if settings.backend == "cortex":
            return CortexSearchRetriever(settings, service_name=settings.objects.search_service)
        return MockRetriever(content.chunks)

    return Backends(
        parse_deps=lambda: make_parse_deps(settings, tables_dir, convert_dir),
        generate_deps=make_generate_deps,
        tables=lambda: make_tables(settings, tables_dir),
        live_llm=live_llm,
        live_retriever=live_retriever,
    )


@dataclass
class ServiceContext:
    settings: Settings
    data_dir: Path
    backends: Backends
    lessons: LessonStore = field(init=False)
    jobs: JobStore = field(default_factory=JobStore)
    # Repeat guards: (session_id, poll_id) and (session_id, event_id) -> first decision.
    poll_decisions: dict[tuple[str, str], Decision] = field(default_factory=dict)
    question_decisions: dict[tuple[str, str], Decision] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    _live: dict[str, Content] = field(default_factory=dict)
    _llm: LLMClient | None = None
    _inflight: dict[tuple[str, str], threading.Lock] = field(default_factory=dict)

    def __post_init__(self):
        self.lessons = LessonStore(self.data_dir)
        self._load_guards()

    def _load_guards(self) -> None:
        """Rebuild the repeat guards from the decision log, so that after a restart a
        repeated question is not run again and a poll does not trigger twice."""
        if not self.log_path.is_file():
            return
        for line in self.log_path.read_text().splitlines():
            try:
                entry = DecisionLogEntry.model_validate_json(line)
            except ValueError:
                continue  # a torn last line after a crash
            d = entry.decision
            if d.path == "poll" and d.poll_id:
                self.poll_decisions.setdefault((d.session_id, d.poll_id), d)
            elif entry.question is not None:
                self.question_decisions.setdefault((d.session_id, entry.question.event_id), d)

    def question_lock(self, key: tuple[str, str]) -> threading.Lock:
        """One lock per (session_id, event_id): a repeat sent while the first call still
        runs waits for it and gets the same decision."""
        with self.lock:
            return self._inflight.setdefault(key, threading.Lock())

    @classmethod
    def build(cls, settings: Settings, data_dir: Path | None = None, backends=None):
        root = data_dir or (PROJECT_ROOT / settings.service.data_dir)
        return cls(settings, root, backends or default_backends(settings, root))

    @property
    def trace_path(self) -> Path:
        return self.data_dir / "traces.jsonl"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "decision_log.jsonl"

    def write_run(self, output: RunOutput) -> None:
        with self.lock:  # one writer at a time: lines never interleave
            write_run(output, self.trace_path, self.log_path)

    # ---------- live ----------

    def manifest(self, lesson_id: str) -> Manifest | None:
        path = self.lessons.prep_dir(lesson_id) / "manifest.json"
        return load_manifest(path) if path.is_file() else None

    def live_content(self, lesson_id: str) -> Content | None:
        """The lesson's manifest, objectives (from its segments), and chunks; cached."""
        with self.lock:
            if lesson_id in self._live:
                return self._live[lesson_id]
        manifest = self.manifest(lesson_id)
        if manifest is None:
            return None
        content = lesson_content(
            lesson_id, manifest, self.backends.tables().lesson_chunks(lesson_id)
        )
        with self.lock:
            self._live[lesson_id] = content
        return content

    def live_llm(self) -> LLMClient:
        with self.lock:
            if self._llm is None:
                self._llm = self.backends.live_llm()
            return self._llm

    def forget_lesson(self, lesson_id: str) -> None:
        with self.lock:
            self._live.pop(lesson_id, None)

    # ---------- prep job ----------

    def run_job(self, job_id: str) -> None:
        """Background task: parse -> generate -> check -> assemble. Never raises."""
        job = self.jobs.get(job_id)
        lesson = self.lessons.get(job.lesson_id)
        update = lambda **f: self.jobs.update(job_id, **f)  # noqa: E731

        def progress(step: str, done: int, total: int, detail: str = "") -> None:
            update(step=step, progress=Progress(done=done, total=total, detail=detail))

        update(status="running", started_at=now())
        lesson_id = lesson.lesson_id
        out_dir = self.lessons.prep_dir(lesson_id)
        tmp_dir = out_dir.with_name("prep.tmp")
        try:
            parse_deps = self.backends.parse_deps()
            uploads = self.lessons.uploads(lesson_id)
            slides = [uploads / f.name for f in lesson.files if f.kind == "slides"]
            refs = [uploads / f.name for f in lesson.files if f.kind == "reference"]
            parse_lesson(lesson_id, slides, refs, parse_deps, progress=progress)

            tables = parse_deps.tables
            material = load_material(lesson_id, tables)
            prep = self.settings.prep.model_copy(update={"poll_count": job.poll_count})
            settings = self.settings.model_copy(update={"prep": prep})
            start = time.perf_counter()
            generator = Generator(
                material, self.backends.generate_deps(settings, material), progress
            )
            result = generator.run()
            seconds = round(time.perf_counter() - start, 1)

            progress("checking", 0, 1)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            write_generation(tmp_dir, result, self.settings.backend, seconds)
            problems, _ = check_and_review(tmp_dir, lesson_id, tables, job.poll_count)
            if problems:
                raise RuntimeError(f"manifest checks failed: {'; '.join(problems[:5])}")

            progress("assembling", 0, 1)
            copy_slide_images(lesson_id, tables, parse_deps.convert_root, tmp_dir)
            shutil.rmtree(out_dir, ignore_errors=True)
            tmp_dir.rename(out_dir)  # a failed job never replaces the last good manifest
            self.forget_lesson(lesson_id)
            update(
                status="done",
                step="done",
                progress=Progress(done=1, total=1),
                failures=failures(result.report.items),
                llm_calls=result.report.llm_calls,
                ended_at=now(),
            )
        except Exception as exc:  # the job reports every failure; the service keeps running
            shutil.rmtree(tmp_dir, ignore_errors=True)
            message = redact(f"{type(exc).__name__}: {exc}")[:1000]
            update(status="failed", step="failed", error=message, ended_at=now())


def failures(items) -> list[ItemFailure]:
    out = []
    for item in items:
        if item.status in ("fallback", "dropped"):
            last = item.attempts[-1].problems if item.attempts else []
            out.append(
                ItemFailure(
                    item=item.item,
                    status=item.status,
                    detail=redact(item.detail),
                    problems=[redact(p) for p in last],
                )
            )
    return out
