"""Page-level checks on converted files: the image-page flag and slide/page alignment.

Pure functions on extracted text and geometry, so they are tested without PDFs.

Image-page flag (Stage 1 findings, docs/agent/note.md): embedded-image area >= 0.10 of
the page identified the image slides; template drawings and logos cover every page, so
objects that (nearly) every page shares are removed before measuring. `image` and
`unsure` pages go to the vision LLM in Stage 5; `text` pages use their text layer.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from classpilot.settings import ImagePageSettings, ParseSettings

ImageFlag = Literal["image", "text", "unsure"]

# A rectangle as fractions of the page: (left, bottom, right, top), each in [0, 1].
Rect = tuple[float, float, float, float]

# Objects on at least this share of pages count as template (needs >= 3 pages).
SHARED_PAGE_SHARE = 0.8
SHARED_MIN_PAGES = 3
# Resolution of the grid that measures the union of rectangles, and of the rounding that
# matches the same template object across pages.
GRID = 200


@dataclass
class PageGeometry:
    """What the PDF says about one page: text length and object rectangles."""

    text_chars: int
    images: list[Rect] = field(default_factory=list)
    drawings: list[Rect] = field(default_factory=list)


class PageSignals(BaseModel):
    text_chars: int
    image_count: int  # after removing shared objects
    image_area: float  # union area, fraction of the page
    drawing_area: float
    shared_objects: int  # removed as template


def _key(kind: str, rect: Rect) -> tuple:
    return (kind, *(round(v * GRID) for v in rect))


def shared_keys(pages: list[PageGeometry]) -> set[tuple]:
    """Object keys that appear on at least SHARED_PAGE_SHARE of the pages."""
    if len(pages) < SHARED_MIN_PAGES:
        return set()
    counts: dict[tuple, int] = {}
    for page in pages:
        keys = {_key("image", r) for r in page.images} | {_key("path", r) for r in page.drawings}
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    needed = SHARED_PAGE_SHARE * len(pages)
    return {key for key, n in counts.items() if n >= needed}


def union_area(rects: list[Rect]) -> float:
    """Area covered by the union of the rectangles, measured on a GRID x GRID grid."""
    if not rects:
        return 0.0
    covered = bytearray(GRID * GRID)
    for left, bottom, right, top in rects:
        x0, x1 = max(0, int(left * GRID)), min(GRID, int(round(right * GRID)))
        y0, y1 = max(0, int(bottom * GRID)), min(GRID, int(round(top * GRID)))
        for y in range(y0, y1):
            row = y * GRID
            covered[row + x0 : row + x1] = b"\x01" * (x1 - x0)
    return sum(covered) / (GRID * GRID)


def page_signals(page: PageGeometry, shared: set[tuple]) -> PageSignals:
    images = [r for r in page.images if _key("image", r) not in shared]
    drawings = [r for r in page.drawings if _key("path", r) not in shared]
    removed = len(page.images) + len(page.drawings) - len(images) - len(drawings)
    return PageSignals(
        text_chars=page.text_chars,
        image_count=len(images),
        image_area=round(union_area(images), 3),
        drawing_area=round(union_area(drawings), 3),
        shared_objects=removed,
    )


def classify(signals: PageSignals, cfg: ImagePageSettings) -> tuple[ImageFlag, str]:
    """Return the flag and the rule that set it (kept in the output for review)."""
    if signals.image_area >= cfg.image_area:
        return "image", "image_area"
    if signals.drawing_area >= cfg.drawing_area:
        return "image", "drawing_area"
    if signals.image_area >= cfg.unsure_image_area:
        return "unsure", "some_image_area"
    if signals.drawing_area >= cfg.unsure_drawing_area:
        return "unsure", "some_drawing_area"
    if signals.text_chars < cfg.min_text_chars:
        return "unsure", "little_text"
    return "text", "text_only"


# --- alignment --------------------------------------------------------------------------


def words(text: str) -> set[str]:
    """Lowercase word set; NFKC folds ligatures that PDF text layers often contain."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    return {w for w in re.findall(r"[a-z0-9]+", normalized) if len(w) >= 2}


class AlignmentPage(BaseModel):
    page_index: int  # 1-based
    slide_words: int
    overlap: float | None  # None: too few words to compare


class AlignmentReport(BaseModel):
    slide_count: int
    page_count: int
    ok: bool
    min_overlap: float
    pages: list[AlignmentPage]
    mismatched: list[int]  # 1-based page indexes


class AlignmentError(ValueError):
    def __init__(self, message: str, report: AlignmentReport):
        super().__init__(message)
        self.report = report


def check_alignment(
    slide_texts: list[str], pdf_texts: list[str], cfg: ParseSettings
) -> AlignmentReport:
    """Slide i (python-pptx) must match PDF page i: same count, and most of the slide's
    words found on the page. Raises AlignmentError otherwise."""
    if len(slide_texts) != len(pdf_texts):
        report = AlignmentReport(
            slide_count=len(slide_texts),
            page_count=len(pdf_texts),
            ok=False,
            min_overlap=cfg.alignment_min_overlap,
            pages=[],
            mismatched=[],
        )
        raise AlignmentError(
            f"PPTX has {len(slide_texts)} slides but the PDF has {len(pdf_texts)} pages", report
        )
    pages, mismatched = [], []
    for index, (slide, pdf) in enumerate(zip(slide_texts, pdf_texts, strict=True), start=1):
        expected = words(slide)
        if len(expected) < cfg.alignment_min_words:
            pages.append(AlignmentPage(page_index=index, slide_words=len(expected), overlap=None))
            continue
        overlap = round(len(expected & words(pdf)) / len(expected), 3)
        pages.append(AlignmentPage(page_index=index, slide_words=len(expected), overlap=overlap))
        if overlap < cfg.alignment_min_overlap:
            mismatched.append(index)
    report = AlignmentReport(
        slide_count=len(slide_texts),
        page_count=len(pdf_texts),
        ok=not mismatched,
        min_overlap=cfg.alignment_min_overlap,
        pages=pages,
        mismatched=mismatched,
    )
    if mismatched:
        raise AlignmentError(f"slide text does not match the PDF on pages {mismatched}", report)
    return report
