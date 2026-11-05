"""Parse a lesson's files into pages and chunks (parse layer, IMPLEMENTATION_NOTES 4.2-4.3).

Per file:
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


def parse_new_file(
    path: Path, kind: FileKind, source_id: str, file_id: str, deps: ParseDeps
) -> tuple[ParsedFile, FileReport]:
    fmt = file_format(path, kind)
    report = FileReport(file_id, source_id, path.name, kind, reused=False, pages=0)
    converted = convert_file(
        path, kind, source_id, deps.convert_root, deps.cfg, pdf_path=deps.pdf_for.get(path)
    )
    out_dir = deps.convert_root / file_id[:16]
    original = out_dir / f"original.{fmt}"
    shutil.copyfile(path, original)

    stage_path = deps.stage.put(original, file_id)
    flagged = [p for p in converted.pages if p.image_flag in VISION_FLAGS]
    png_paths = {p.page_id: deps.stage.put(out_dir / p.png, f"{file_id}/pages") for p in flagged}
    deps.stage.refresh()

    if kind == "slides":
        texts = [(p.text_layer, "local_text") for p in converted.pages]
    else:
        texts = _reference_text(converted if fmt == "pdf" else None, stage_path, deps, report)

    local = {p.page_index: p for p in converted.pages}
    pages = []
    for index, (text, method) in enumerate(texts, start=1):
        record = local.get(index)
        pid = record.page_id if record else page_id(source_id, index)
        description = None
        if record is not None and record.image_flag in VISION_FLAGS:
            report.vision_pages.append(pid)
            prompt = build_prompt(text, record.notes)
            try:
                description = parse_reply(deps.vision.describe(png_paths[pid], prompt))
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
    parsed = ParsedFile(
        file_id=file_id,
        source_id=source_id,
        kind=kind,
        format=fmt,
        original_name=path.name,
        stage_path=stage_path,
        page_count=len(pages),
        pages=pages,
    )
    deps.tables.save_parsed(parsed)
    report.pages = len(pages)
    return parsed, report


def parse_lesson(
    lesson_id: str,
    slides: list[Path],
    references: list[Path],
    deps: ParseDeps,
    source: str | None = None,
) -> list[FileReport]:
    paths = [*slides, *references]
    kinds: list[FileKind] = ["slides"] * len(slides) + ["reference"] * len(references)
    if source is not None and len(paths) != 1:
        raise ParseError("--source needs exactly one file")
    for path, kind in zip(paths, kinds, strict=True):
        if not path.is_file():
            raise ParseError(f"{path}: file not found")
        file_format(path, kind)

    reports, taken = [], set()
    for path, kind in zip(paths, kinds, strict=True):
        file_id = file_sha256(path)
        parsed = deps.tables.known_file(file_id)
        if parsed is not None:
            report = FileReport(
                file_id, parsed.source_id, path.name, parsed.kind, True, parsed.page_count
            )
        else:
            if source is not None:
                source_id = slugify_source(source)
                owner = deps.tables.source_owner(source_id)
                if owner not in (None, file_id):
                    raise ParseError(f"source id {source_id!r} is used by another file")
            else:
                source_id = assign_source_id(path.name, file_id, deps.tables, taken)
            parsed, report = parse_new_file(path, kind, source_id, file_id, deps)
        taken.add(parsed.source_id)
        chunks = chunk_file(parsed, deps.cfg.chunk_max_chars)
        deps.tables.register_file(lesson_id, parsed)
        deps.tables.replace_chunks(lesson_id, parsed.file_id, chunks)
        report.chunks = len(chunks)
        reports.append(report)
    deps.tables.refresh_search()
    return reports
