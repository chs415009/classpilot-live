"""Build the synthetic fixture deck used by the parse-layer tests (Stage 4).

    python scripts/make_fixture_deck.py          # PPTX + PDF (LibreOffice in Docker)
    python scripts/make_fixture_deck.py --no-pdf # PPTX only

Writes tests/fixtures/deck/fixture_deck.pptx and fixture_deck.pdf. Both are committed,
so tests never need LibreOffice. All content is synthetic (no course material).

Slides and the image-page flag each one should get:
  1 title (placeholders)               text    notes
  2 bullet text (placeholders)         text    notes
  3 diagram: panel, 3 boxes, 2 arrows  image   notes   (drawing area)
  4 image only, no text                image   notes   (image area)
  5 code in a monospace text box       text    notes
  6 summary                            text    no notes
Every slide has the same footer bar, which the flag must ignore as template.
"""

import argparse
import io
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from classpilot.prep.libreoffice import pptx_to_pdf  # noqa: E402
from classpilot.settings import load_settings  # noqa: E402

OUT_DIR = ROOT / "tests" / "fixtures" / "deck"
PPTX = OUT_DIR / "fixture_deck.pptx"
PDF = OUT_DIR / "fixture_deck.pdf"

TITLE_LAYOUT, CONTENT_LAYOUT, TITLE_ONLY_LAYOUT, BLANK_LAYOUT = 0, 1, 5, 6

CODE = """SELECT order_id,
       customer_id,
       CAST(amount AS NUMBER(10, 2)) AS amount
FROM {{ source('shop', 'raw_orders') }}
WHERE status IS NOT NULL"""


def footer(slide, with_text: bool = True) -> None:
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(7.1), Inches(10), Inches(0.4))
    bar.fill.solid()
    bar.fill.fore_color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    bar.line.fill.background()
    if with_text:
        box = slide.shapes.add_textbox(Inches(0.3), Inches(7.12), Inches(6), Inches(0.35))
        run = box.text_frame.paragraphs[0].add_run()
        run.text = "ClassPilot fixture deck"
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)


def notes(slide, text: str) -> None:
    slide.notes_slide.notes_text_frame.text = text


def bullets(placeholder, lines: list[str]) -> None:
    frame = placeholder.text_frame
    frame.text = lines[0]
    for line in lines[1:]:
        frame.add_paragraph().text = line


def chart_png() -> io.BytesIO:
    """A bar chart drawn with plain shapes (no text), deterministic."""
    image = Image.new("RGB", (1600, 1100), (250, 250, 247))
    draw = ImageDraw.Draw(image)
    draw.line([(140, 980), (1500, 980)], fill=(60, 60, 60), width=6)
    draw.line([(140, 980), (140, 120)], fill=(60, 60, 60), width=6)
    colors = [(176, 112, 56), (150, 150, 160), (212, 175, 55)]
    for i, height in enumerate([360, 590, 800]):
        left = 260 + i * 420
        draw.rectangle([left, 980 - height, left + 260, 975], fill=colors[i])
    for y in range(180, 980, 160):
        draw.line([(150, y), (1500, y)], fill=(215, 215, 210), width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def build() -> Presentation:
    deck = Presentation()  # default template, 4:3 (10 x 7.5 in)
    # The default template carries its own author metadata; keep the fixture neutral.
    props = deck.core_properties
    props.title = "ClassPilot fixture deck"
    props.author = props.last_modified_by = "ClassPilot"
    props.created = props.modified = datetime(2026, 11, 5, tzinfo=UTC)
    layouts = deck.slide_layouts

    s1 = deck.slides.add_slide(layouts[TITLE_LAYOUT])
    s1.shapes.title.text = "Medallion Architecture Basics"
    s1.placeholders[1].text = "Synthetic fixture deck for parse-layer tests"
    footer(s1)
    notes(s1, "Welcome. Today we look at the bronze, silver, and gold layers.")

    s2 = deck.slides.add_slide(layouts[CONTENT_LAYOUT])
    s2.shapes.title.text = "Three Layers"
    bullets(
        s2.placeholders[1],
        [
            "Bronze keeps raw data exactly as it arrived",
            "Silver holds cleaned and deduplicated records",
            "Gold serves business-ready aggregates",
        ],
    )
    footer(s2)
    notes(s2, "Stress that bronze is never edited, so every load can be replayed.")

    s3 = deck.slides.add_slide(layouts[TITLE_ONLY_LAYOUT])
    s3.shapes.title.text = "Data Flow"
    panel = s3.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.5), Inches(1.7), Inches(9), Inches(5)
    )
    panel.fill.solid()
    panel.fill.fore_color.rgb = RGBColor(0xEE, 0xF2, 0xF7)
    panel.line.color.rgb = RGBColor(0x9A, 0xA8, 0xBA)
    boxes = []
    for i, (label, rgb) in enumerate(
        [
            ("Bronze", (0xB0, 0x70, 0x38)),
            ("Silver", (0x96, 0x96, 0xA0)),
            ("Gold", (0xD4, 0xAF, 0x37)),
        ]
    ):
        box = s3.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0.9 + i * 3), Inches(3.3), Inches(2.2), Inches(1.6)
        )
        box.fill.solid()
        box.fill.fore_color.rgb = RGBColor(*rgb)
        box.text_frame.text = label
        boxes.append(box)
    for left, right in zip(boxes, boxes[1:], strict=False):
        arrow = s3.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            left.left + left.width,
            left.top + left.height // 2,
            right.left,
            right.top + right.height // 2,
        )
        arrow.line.width = Pt(3)
        arrow.line.color.rgb = RGBColor(0x33, 0x33, 0x33)
    footer(s3)
    notes(s3, "Data moves left to right; each step adds structure.")

    s4 = deck.slides.add_slide(layouts[BLANK_LAYOUT])
    s4.shapes.add_picture(chart_png(), Inches(0.6), Inches(0.4), width=Inches(8.8))
    footer(s4, with_text=False)
    notes(s4, "The chart shows record counts growing from bronze to gold.")

    s5 = deck.slides.add_slide(layouts[TITLE_ONLY_LAYOUT])
    s5.shapes.title.text = "A Silver Model in dbt"
    code = s5.shapes.add_textbox(Inches(0.7), Inches(1.9), Inches(8.6), Inches(3.5))
    frame = code.text_frame
    for i, line in enumerate(CODE.splitlines()):
        paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        run = paragraph.add_run()
        run.text = line
        run.font.name = "Courier New"
        run.font.size = Pt(18)
    footer(s5)
    notes(s5, "Read the model top to bottom: select, cast, then filter null statuses.")

    s6 = deck.slides.add_slide(layouts[CONTENT_LAYOUT])
    s6.shapes.title.text = "Summary"
    bullets(
        s6.placeholders[1],
        [
            "Keep bronze unchanged for replay",
            "Clean once in silver",
            "Aggregate for consumers in gold",
        ],
    )
    footer(s6)
    return deck


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-pdf", action="store_true", help="skip the LibreOffice PDF")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    build().save(str(PPTX))
    print(f"wrote {PPTX.relative_to(ROOT)}")
    if args.no_pdf:
        return
    cfg = load_settings().parse
    work = ROOT / "outputs" / "fixture_deck_build"
    pdf = pptx_to_pdf(PPTX, work, cfg.libreoffice_image, cfg.libreoffice_timeout_seconds)
    shutil.copyfile(pdf, PDF)
    shutil.rmtree(work, ignore_errors=True)
    print(f"wrote {PDF.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
