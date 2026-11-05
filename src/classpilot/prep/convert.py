"""Local conversion of uploaded files (parse layer step 1, IMPLEMENTATION_NOTES 4.1).

- PPTX slides: python-pptx text and speaker notes; LibreOffice (Docker) -> PDF;
  pypdfium2 -> one PNG per page, plus the geometry for the image-page flag. The slide
  count must equal the PDF page count and each slide's text must match its page.
- PDF slides: pypdfium2 text layer and PNG per page (no notes).
- PDF references: text layer, PNG, and image-page flag per page.
- DOCX references: passed through (hash and metadata only; parsed in Snowflake).

Each file gets `file_id` = SHA-256 of its bytes and pages get `<source>-p<NN>` ids
(1-based, the slide number the professor sees). Output per file:
`<out_root>/<file_id[:16]>/convert.json` and `pages/p<NN>.png`.
"""

import hashlib
import io
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pydantic import BaseModel

from classpilot.prep.libreoffice import LibreOfficeError, pptx_to_pdf
from classpilot.prep.pages import (
    AlignmentReport,
    ImageFlag,
    PageGeometry,
    PageSignals,
    Rect,
    check_alignment,
    classify,
    page_signals,
    shared_keys,
)
from classpilot.settings import ParseSettings

FileKind = Literal["slides", "reference"]
FileFormat = Literal["pptx", "pdf", "docx"]
ALLOWED_FORMATS: dict[str, set[str]] = {"slides": {"pptx", "pdf"}, "reference": {"pdf", "docx"}}
SOURCE_MAX_LEN = 32


class ConvertError(ValueError):
    pass


class PageRecord(BaseModel):
    page_id: str  # <source>-p<NN>
    page_index: int  # 1-based
    text_layer: str  # PPTX: python-pptx slide text; PDF: pypdfium2 text layer
    notes: str | None  # PPTX speaker notes; None when the slide has none
    hidden: bool  # PPTX hidden slide (still exported, so indexes stay aligned)
    png: str  # relative to the file's output directory
    png_bytes: int
    png_px: tuple[int, int]
    render_scale: float
    image_flag: ImageFlag
    image_reason: str
    signals: PageSignals


class ConvertedFile(BaseModel):
    file_id: str  # sha256 hex of the original bytes
    source_id: str
    kind: FileKind
    format: FileFormat
    original_name: str
    page_count: int | None  # from pypdfium2; None for DOCX
    pdf: str | None  # PPTX: the LibreOffice PDF, relative to the output directory
    pptx_repaired: bool  # LibreOffice could only open a python-pptx re-saved copy
    alignment: AlignmentReport | None
    pages: list[PageRecord]


# --- ids --------------------------------------------------------------------------------


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def slugify_source(text: str) -> str:
    """Source id: lowercase [a-z0-9-], at most SOURCE_MAX_LEN characters."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:SOURCE_MAX_LEN].rstrip("-") or "file"


def unique_source_ids(names: list[str]) -> list[str]:
    """Slug of each file stem; repeats in one batch get -2, -3, ..."""
    seen: dict[str, int] = {}
    ids = []
    for name in names:
        base = slugify_source(Path(name).stem)
        seen[base] = seen.get(base, 0) + 1
        ids.append(base if seen[base] == 1 else f"{base}-{seen[base]}")
    return ids


def page_id(source_id: str, page_index: int) -> str:
    return f"{source_id}-p{page_index:02d}"


def file_format(path: Path, kind: FileKind) -> FileFormat:
    fmt = path.suffix.lower().lstrip(".")
    if fmt not in ALLOWED_FORMATS[kind]:
        allowed = ", ".join(sorted(ALLOWED_FORMATS[kind]))
        raise ConvertError(f"{path.name}: {kind} must be one of {allowed}")
    return fmt  # type: ignore[return-value]


# --- PPTX -------------------------------------------------------------------------------


@dataclass
class SlideText:
    text: str
    notes: str | None
    hidden: bool


def _clean(text: str) -> str:
    # python-pptx returns line breaks inside a paragraph as vertical tabs.
    return "\n".join(line.rstrip() for line in text.replace("\v", "\n").splitlines()).strip()


def _shape_texts(shapes) -> list[str]:
    texts = []
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            texts.extend(_shape_texts(shape.shapes))
        elif shape.has_text_frame:
            texts.append(shape.text_frame.text)
        elif getattr(shape, "has_table", False) and shape.has_table:
            for row in shape.table.rows:
                texts.append("\t".join(cell.text for cell in row.cells))
    return [t for t in (_clean(t) for t in texts) if t]


def read_pptx(path: Path) -> list[SlideText]:
    slides = []
    for slide in Presentation(str(path)).slides:
        notes = None
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = _clean(slide.notes_slide.notes_text_frame.text) or None
        slides.append(
            SlideText(
                text="\n".join(_shape_texts(slide.shapes)),
                notes=notes,
                hidden=slide._element.get("show") == "0",
            )
        )
    return slides


def pdf_for_pptx(path: Path, work_dir: Path, cfg: ParseSettings) -> tuple[Path, bool]:
    """LibreOffice PDF for a PPTX; returns (pdf, repaired).

    Some generated PPTX files (written with prefixed package namespaces such as
    `<ns0:Types>`) do not open in LibreOffice although python-pptx reads them. On a
    load failure, a python-pptx re-saved copy is tried once.
    """
    image, timeout = cfg.libreoffice_image, cfg.libreoffice_timeout_seconds
    try:
        return pptx_to_pdf(path, work_dir, image, timeout), False
    except LibreOfficeError as first:
        if first.kind != "load":
            raise
        repaired = work_dir / "repaired.pptx"
        Presentation(str(path)).save(str(repaired))
        try:
            return pptx_to_pdf(repaired, work_dir, image, timeout), True
        except LibreOfficeError as second:
            raise LibreOfficeError(
                f"{path.name}: {first}; re-saved copy also failed: {second}", second.kind
            ) from second


# --- PDF --------------------------------------------------------------------------------


@dataclass
class PdfPage:
    text: str
    geometry: PageGeometry


def _page_rect(obj, width: float, height: float) -> Rect:
    """Object bounds as page fractions; objects inside Form XObjects report bounds in
    the form's space, so the container matrices are applied first."""
    left, bottom, right, top = obj.get_bounds()
    container = obj.container
    while container is not None:
        left, bottom, right, top = container.get_matrix().on_rect(left, bottom, right, top)
        container = container.container
    return (
        min(max(left / width, 0.0), 1.0),
        min(max(bottom / height, 0.0), 1.0),
        min(max(right / width, 0.0), 1.0),
        min(max(top / height, 0.0), 1.0),
    )


def read_pdf(path: Path) -> list[PdfPage]:
    pdf = pdfium.PdfDocument(str(path))
    try:
        pages = []
        for page in pdf:
            width, height = page.get_size()
            text = page.get_textpage().get_text_range()
            text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()
            images, drawings = [], []
            for obj in page.get_objects(
                filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE, pdfium_c.FPDF_PAGEOBJ_PATH]
            ):
                rect = _page_rect(obj, width, height)
                if rect[2] <= rect[0] or rect[3] <= rect[1]:
                    continue
                if obj.type == pdfium_c.FPDF_PAGEOBJ_IMAGE:
                    images.append(rect)
                else:
                    drawings.append(rect)
            pages.append(PdfPage(text, PageGeometry(len(text), images, drawings)))
        return pages
    finally:
        pdf.close()


@dataclass
class RenderedPage:
    png: Path
    png_bytes: int
    png_px: tuple[int, int]
    scale: float


def render_pages(path: Path, png_dir: Path, cfg: ParseSettings) -> list[RenderedPage]:
    """One PNG per page at `render_scale`; re-rendered smaller until under the limit."""
    png_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(path))
    try:
        rendered = []
        for index, page in enumerate(pdf, start=1):
            scale = cfg.render_scale
            while True:
                image = page.render(scale=scale).to_pil()
                buffer = io.BytesIO()
                image.save(buffer, format="PNG", optimize=True)
                size = buffer.tell()
                if size <= cfg.png_max_bytes:
                    break
                if scale <= cfg.min_render_scale:
                    raise ConvertError(
                        f"{path.name} page {index}: PNG is {size} bytes at the minimum "
                        f"scale {scale}; limit {cfg.png_max_bytes}"
                    )
                # PNG size grows about with the pixel count, so scale by the square root.
                scale = max(cfg.min_render_scale, scale * (cfg.png_max_bytes / size) ** 0.5 * 0.95)
            target = png_dir / f"p{index:02d}.png"
            target.write_bytes(buffer.getvalue())
            rendered.append(RenderedPage(target, size, image.size, round(scale, 3)))
        return rendered
    finally:
        pdf.close()


# --- one file ---------------------------------------------------------------------------


def convert_file(
    path: Path,
    kind: FileKind,
    source_id: str,
    out_root: Path,
    cfg: ParseSettings,
    pdf_path: Path | None = None,
) -> ConvertedFile:
    """Convert one file and write its convert.json. `pdf_path` supplies the PDF of a
    PPTX instead of running LibreOffice (tests use the committed fixture PDF)."""
    fmt = file_format(path, kind)
    file_id = file_sha256(path)
    out_dir = out_root / file_id[:16]
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    base = dict(
        file_id=file_id, source_id=source_id, kind=kind, format=fmt, original_name=path.name
    )
    if fmt == "docx":
        result = ConvertedFile(
            **base, page_count=None, pdf=None, pptx_repaired=False, alignment=None, pages=[]
        )
        (out_dir / "convert.json").write_text(result.model_dump_json(indent=2))
        return result

    slides: list[SlideText] | None = None
    repaired = False
    pdf_rel = None
    if fmt == "pptx":
        slides = read_pptx(path)
        if pdf_path is None:
            pdf_path, repaired = pdf_for_pptx(path, out_dir / "libreoffice", cfg)
        shutil.copyfile(pdf_path, out_dir / "slides.pdf")
        shutil.rmtree(out_dir / "libreoffice", ignore_errors=True)
        pdf_path, pdf_rel = out_dir / "slides.pdf", "slides.pdf"
    else:
        pdf_path = path

    pdf_pages = read_pdf(pdf_path)
    alignment = None
    if slides is not None:
        alignment = check_alignment([s.text for s in slides], [p.text for p in pdf_pages], cfg)

    rendered = render_pages(pdf_path, out_dir / "pages", cfg)
    shared = shared_keys([p.geometry for p in pdf_pages])
    records = []
    for index, (pdf_page, png) in enumerate(zip(pdf_pages, rendered, strict=True), start=1):
        signals = page_signals(pdf_page.geometry, shared)
        flag, reason = classify(signals, cfg.image_page)
        slide = slides[index - 1] if slides is not None else None
        records.append(
            PageRecord(
                page_id=page_id(source_id, index),
                page_index=index,
                text_layer=slide.text if slide is not None else pdf_page.text,
                notes=slide.notes if slide is not None else None,
                hidden=slide.hidden if slide is not None else False,
                png=str(png.png.relative_to(out_dir)),
                png_bytes=png.png_bytes,
                png_px=png.png_px,
                render_scale=png.scale,
                image_flag=flag,
                image_reason=reason,
                signals=signals,
            )
        )
    result = ConvertedFile(
        **base,
        page_count=len(pdf_pages),
        pdf=pdf_rel,
        pptx_repaired=repaired,
        alignment=alignment,
        pages=records,
    )
    (out_dir / "convert.json").write_text(result.model_dump_json(indent=2))
    return result


def convert_files(
    slides: list[Path],
    references: list[Path],
    out_root: Path,
    cfg: ParseSettings,
    source: str | None = None,
) -> list[ConvertedFile]:
    """Convert a batch; source ids come from the file names (or `source` for one file)."""
    paths = [*slides, *references]
    kinds: list[FileKind] = ["slides"] * len(slides) + ["reference"] * len(references)
    if source is not None:
        if len(paths) != 1:
            raise ConvertError("--source needs exactly one file")
        ids = [slugify_source(source)]
    else:
        ids = unique_source_ids([p.name for p in paths])
    for path, kind in zip(paths, kinds, strict=True):
        if not path.is_file():
            raise ConvertError(f"{path}: file not found")
        file_format(path, kind)
    return [
        convert_file(path, kind, source_id, out_root, cfg)
        for path, kind, source_id in zip(paths, kinds, ids, strict=True)
    ]
