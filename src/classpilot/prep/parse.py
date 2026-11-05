"""Parse a lesson's files into pages and chunks (parse layer, IMPLEMENTATION_NOTES 4.2-4.3).

Per file (run in phases over all files, see `parse_lesson`):
1. A known file hash is never converted or parsed again, also for another lesson; its
   pages are reused and its chunks copied for the lesson (same chunk ids).
2. New file: local conversion (Stage 4), then PUT of the original and of the PNGs of
   pages flagged `image` or `unsure`, one directory refresh.
3. Page text: slides use their local text and notes; references use AI_PARSE_DOCUMENT
   (LAYOUT, per page). A PDF reference whose parse fails keeps its local text layer.
4. Vision only for `image` / `unsure` pages. A failed or malformed vision reply leaves
   the page with its text (`+vision_failed`); prep never stops on an LLM error.
5. PARSED_PAGES once per file; RAW_FILES and LESSON_CHUNKS_V2 per lesson; then one
   search-service refresh.

Source ids are unique across all files: the file stem's slug, with -2, -3 when another
file already uses it, fixed at the first upload and reused with the hash.
"""

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from classpilot.adapters.parse import (
    DocumentParser,
    SnowflakeStepError,
    StageAdapter,
    VisionDescriber,
)
from classpilot.prep.chunking import chunk_file
from classpilot.prep.convert import (
    ConvertedFile,
    FileKind,
    convert_file,
    file_format,
    file_sha256,
    page_id,
    slugify_source,
)
from classpilot.prep.records import ParsedFile, ParsedPage
from classpilot.prep.tables import PrepTables
from classpilot.prep.vision import VisionReplyError, build_prompt, parse_reply
from classpilot.settings import ParseSettings

VISION_FLAGS = ("image", "unsure")


class ParseError(RuntimeError):
    pass


@dataclass
class ParseDeps:
    stage: StageAdapter
    parser: DocumentParser
    vision: VisionDescriber
    tables: PrepTables
    cfg: ParseSettings
    convert_root: Path
    # PDF to use for a PPTX instead of LibreOffice (tests use the committed fixture PDF).
    pdf_for: dict[Path, Path] = field(default_factory=dict)


@dataclass
class FileReport:
    file_id: str
    source_id: str
    original_name: str
    kind: str
    reused: bool
    pages: int
    parse_calls: int = 0
    parse_fallback: bool = False
    vision_pages: list[str] = field(default_factory=list)
    vision_failed: list[str] = field(default_factory=list)
    chunks: int = 0


def assign_source_id(name: str, file_id: str, tables: PrepTables, taken: set[str]) -> str:
    base = slugify_source(Path(name).stem)
    candidate, n = base, 1
    while candidate in taken or tables.source_owner(candidate) not in (None, file_id):
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def _reference_text(
    converted: ConvertedFile | None, stage_path: str, deps: ParseDeps, report: FileReport
) -> list[tuple[str, str]]:
    """(text, method) per page of a reference, from AI_PARSE_DOCUMENT."""
    report.parse_calls += 1
    try:
        pages = deps.parser.parse(stage_path)
    except SnowflakeStepError as exc:
        if converted is None:  # DOCX: no local text to fall back to
            raise ParseError(f"{report.original_name}: AI_PARSE_DOCUMENT failed: {exc}") from exc
        report.parse_fallback = True
        return [(p.text_layer, "local_text_fallback") for p in converted.pages]
    if converted is not None and len(pages) != converted.page_count:
        raise ParseError(
            f"{report.original_name}: AI_PARSE_DOCUMENT returned {len(pages)} pages, "
            f"the PDF has {converted.page_count}"
        )
    pages = sorted(pages, key=lambda p: p.page_index)
    return [(p.content, "ai_parse_layout") for p in pages]


# progress(step, done, total, detail): steps "converting", "uploading", "parsing",
# "chunking" in that order; `done` / `total` count files, or pages while parsing.
Progress = Callable[[str, int, int, str], None]


def _no_progress(step: str, done: int, total: int, detail: str = "") -> None:
    pass


@dataclass
class _NewFile:
    path: Path
    kind: FileKind
    fmt: str
    report: FileReport
    converted: ConvertedFile
    out_dir: Path
    stage_path: str = ""
    png_paths: dict[str, str] = field(default_factory=dict)


def _convert(path: Path, kind: FileKind, source_id: str, file_id: str, deps: ParseDeps) -> _NewFile:
    fmt = file_format(path, kind)
    report = FileReport(file_id, source_id, path.name, kind, reused=False, pages=0)
    converted = convert_file(
        path, kind, source_id, deps.convert_root, deps.cfg, pdf_path=deps.pdf_for.get(path)
    )
    out_dir = deps.convert_root / file_id[:16]
    shutil.copyfile(path, out_dir / f"original.{fmt}")
    return _NewFile(path, kind, fmt, report, converted, out_dir)


def _upload(new: _NewFile, deps: ParseDeps) -> None:
    file_id = new.report.file_id
    new.stage_path = deps.stage.put(new.out_dir / f"original.{new.fmt}", file_id)
    flagged = [p for p in new.converted.pages if p.image_flag in VISION_FLAGS]
    new.png_paths = {
        p.page_id: deps.stage.put(new.out_dir / p.png, f"{file_id}/pages") for p in flagged
    }


@dataclass
class _PageProgress:
    progress: Progress
    total: int
    done: int = 0

    def add_total(self, pages: int) -> None:  # DOCX: page count known after parsing
        self.total += pages
        self.progress("parsing", self.done, self.total, "")

    def page_done(self) -> None:
        self.done += 1
        self.progress("parsing", self.done, self.total, "")


def _parse(new: _NewFile, deps: ParseDeps, pages_progress: _PageProgress) -> ParsedFile:
    report, converted = new.report, new.converted
    if new.kind == "slides":
        texts = [(p.text_layer, "local_text") for p in converted.pages]
    else:
        pdf = converted if new.fmt == "pdf" else None
        texts = _reference_text(pdf, new.stage_path, deps, report)

    if converted.page_count is None:
        pages_progress.add_total(len(texts))
    local = {p.page_index: p for p in converted.pages}
    pages = []
    for index, (text, method) in enumerate(texts, start=1):
        record = local.get(index)
        pid = record.page_id if record else page_id(report.source_id, index)
        description = None
        if record is not None and record.image_flag in VISION_FLAGS:
            report.vision_pages.append(pid)
            prompt = build_prompt(text, record.notes)
            try:
                description = parse_reply(deps.vision.describe(new.png_paths[pid], prompt))
                method += "+vision"
            except (SnowflakeStepError, VisionReplyError):
                report.vision_failed.append(pid)
                method += "+vision_failed"
        pages.append(
            ParsedPage(
                page_index=index,
                page_id=pid,
                text_layer=text,
                notes=record.notes if record else None,
                llm_description=description,
                image_flag=record.image_flag if record else None,
                parse_method=method,
            )
        )
        pages_progress.page_done()
    parsed = ParsedFile(
        file_id=report.file_id,
        source_id=report.source_id,
        kind=new.kind,
        format=new.fmt,
        original_name=new.path.name,
        stage_path=new.stage_path,
        page_count=len(pages),
        pages=pages,
    )
    deps.tables.save_parsed(parsed)
    report.pages = len(pages)
    return parsed


def parse_lesson(
    lesson_id: str,
    slides: list[Path],
    references: list[Path],
    deps: ParseDeps,
    source: str | None = None,
    progress: Progress = _no_progress,
) -> list[FileReport]:
    """Phases over all files, so a job's step only moves forward: convert the new files,
    upload them (one directory refresh), parse and describe their pages, then chunk and
    load every file of the lesson."""
    paths = [*slides, *references]
    kinds: list[FileKind] = ["slides"] * len(slides) + ["reference"] * len(references)
    if source is not None and len(paths) != 1:
        raise ParseError("--source needs exactly one file")
    for path, kind in zip(paths, kinds, strict=True):
        if not path.is_file():
            raise ParseError(f"{path}: file not found")
        file_format(path, kind)

    # 1. Known hashes are reused; new files are converted locally.
    entries: list[tuple[ParsedFile | None, _NewFile | None, FileReport]] = []
    taken: set[str] = set()
    for n, (path, kind) in enumerate(zip(paths, kinds, strict=True)):
        progress("converting", n, len(paths), path.name)
        file_id = file_sha256(path)
        parsed = deps.tables.known_file(file_id)
        if parsed is not None:
            report = FileReport(
                file_id, parsed.source_id, path.name, parsed.kind, True, parsed.page_count
            )
            entries.append((parsed, None, report))
            taken.add(parsed.source_id)
            continue
        if source is not None:
            source_id = slugify_source(source)
            owner = deps.tables.source_owner(source_id)
            if owner not in (None, file_id):
                raise ParseError(f"source id {source_id!r} is used by another file")
        else:
            source_id = assign_source_id(path.name, file_id, deps.tables, taken)
        new = _convert(path, kind, source_id, file_id, deps)
        entries.append((None, new, new.report))
        taken.add(source_id)
    progress("converting", len(paths), len(paths), "")

    # 2. Upload the originals and the page images for vision; one directory refresh.
    new_files = [new for _, new, _ in entries if new is not None]
    for n, new in enumerate(new_files):
        progress("uploading", n, len(new_files), new.path.name)
        _upload(new, deps)
    if new_files:
        deps.stage.refresh()
    progress("uploading", len(new_files), len(new_files), "")

    # 3. Page text (AI_PARSE_DOCUMENT for references) and vision for image pages.
    pages_progress = _PageProgress(progress, sum(n.converted.page_count or 0 for n in new_files))
    progress("parsing", 0, pages_progress.total, "")
    parsed_files = []
    for parsed, new, report in entries:
        parsed_files.append((parsed if new is None else _parse(new, deps, pages_progress), report))

    # 4. Chunks per file, copied for this lesson; one search-service refresh.
    reports = []
    for n, (parsed, report) in enumerate(parsed_files):
        progress("chunking", n, len(parsed_files), parsed.original_name)
        chunks = chunk_file(parsed, deps.cfg.chunk_max_chars)
        deps.tables.register_file(lesson_id, parsed)
        deps.tables.replace_chunks(lesson_id, parsed.file_id, chunks)
        report.chunks = len(chunks)
        reports.append(report)
    deps.tables.refresh_search()
    progress("chunking", len(parsed_files), len(parsed_files), "")
    return reports
