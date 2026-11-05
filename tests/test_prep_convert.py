"""Local conversion (prep/convert.py) on the committed synthetic fixture deck.

The PPTX tests pass the committed fixture PDF, so they do not need LibreOffice. The
LibreOffice tests at the end run the Docker image and are skipped (and reported as
skipped) when Docker or the image is not available.
"""

import json
import shutil
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from pptx import Presentation

from classpilot.cli import main
from classpilot.prep import convert
from classpilot.prep.convert import (
    ConvertError,
    convert_file,
    convert_files,
    file_sha256,
    page_id,
    pdf_for_pptx,
    read_pptx,
    unique_source_ids,
)
from classpilot.prep.libreoffice import LibreOfficeError, docker_ready
from classpilot.prep.pages import AlignmentError
from classpilot.settings import ParseSettings

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "deck"
DECK_PPTX = FIXTURE_DIR / "fixture_deck.pptx"
DECK_PDF = FIXTURE_DIR / "fixture_deck.pdf"
EXPECTED_FLAGS = ["text", "text", "image", "image", "text", "text"]
TITLES = [
    "Medallion Architecture Basics",
    "Three Layers",
    "Data Flow",
    None,  # image only
    "A Silver Model in dbt",
    "Summary",
]


@pytest.fixture(scope="module")
def deck(tmp_path_factory):
    out = tmp_path_factory.mktemp("convert")
    return convert_file(DECK_PPTX, "slides", "deck1", out, ParseSettings(), pdf_path=DECK_PDF), out


def reordered_pdf(target: Path, order: list[int]) -> Path:
    """Copy of the fixture PDF with pages in `order` (0-based)."""
    src = pdfium.PdfDocument(str(DECK_PDF))
    new = pdfium.PdfDocument.new()
    new.import_pages(src, order)
    new.save(str(target))
    return target


# --- ids and hashes ---------------------------------------------------------------------


def test_page_ids_are_one_based_with_two_digits():
    assert page_id("deck1", 2) == "deck1-p02"
    assert page_id("deck1", 100) == "deck1-p100"


def test_source_ids_from_file_names_are_unique():
    names = ["L1 Slides.pptx", "l1-slides.pdf", "Reading (v2).docx"]
    assert unique_source_ids(names) == ["l1-slides", "l1-slides-2", "reading-v2"]


def test_same_file_same_hash(tmp_path):
    copy = tmp_path / "copy.pptx"
    shutil.copyfile(DECK_PPTX, copy)
    assert file_sha256(copy) == file_sha256(DECK_PPTX)
    assert len(file_sha256(DECK_PPTX)) == 64
    assert file_sha256(DECK_PDF) != file_sha256(DECK_PPTX)


def test_file_id_and_output_dir(deck):
    result, out = deck
    assert result.file_id == file_sha256(DECK_PPTX)
    saved = json.loads((out / result.file_id[:16] / "convert.json").read_text())
    assert saved["file_id"] == result.file_id
    assert saved["pdf"] == "slides.pdf"


# --- PPTX -------------------------------------------------------------------------------


def test_pptx_text_notes_and_ids(deck):
    result, _ = deck
    assert result.page_count == 6
    assert [p.page_id for p in result.pages] == [f"deck1-p{i:02d}" for i in range(1, 7)]
    for page, title in zip(result.pages, TITLES, strict=True):
        if title:
            assert title in page.text_layer
    assert "SELECT order_id" in result.pages[4].text_layer
    assert [bool(p.notes) for p in result.pages] == [True] * 5 + [False]
    assert result.pages[5].notes is None
    assert result.pages[1].notes.startswith("Stress that bronze")
    assert not result.pptx_repaired


def test_pptx_alignment_report(deck):
    result, _ = deck
    assert result.alignment.ok
    assert result.alignment.pages[3].overlap is None  # image-only slide has no words
    assert all(p.overlap == 1.0 for p in result.alignment.pages if p.overlap is not None)


def test_png_per_page_under_the_limit(deck):
    result, out = deck
    pngs = sorted((out / result.file_id[:16] / "pages").glob("*.png"))
    assert len(pngs) == 6
    limit = ParseSettings().png_max_bytes
    for page, png in zip(result.pages, pngs, strict=True):
        assert page.png == f"pages/{png.name}"
        assert png.stat().st_size == page.png_bytes <= limit
        assert page.png_px == (1440, 1080)  # 10 x 7.5 in at scale 2
        assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_image_page_flag_per_fixture_slide(deck):
    result, _ = deck
    assert [p.image_flag for p in result.pages] == EXPECTED_FLAGS
    # The footer bar is on every slide and is removed as template.
    assert all(p.signals.shared_objects > 0 for p in result.pages)


def test_png_downscaled_to_fit_a_small_limit(tmp_path):
    cfg = ParseSettings(png_max_bytes=30_000)
    result = convert_file(DECK_PDF, "slides", "deck1", tmp_path, cfg)
    assert all(p.png_bytes <= 30_000 for p in result.pages)
    assert any(p.render_scale < cfg.render_scale for p in result.pages)


def test_png_limit_unreachable_is_an_error(tmp_path):
    with pytest.raises(ConvertError, match="minimum scale"):
        convert_file(DECK_PDF, "slides", "deck1", tmp_path, ParseSettings(png_max_bytes=100))


def test_alignment_error_on_swapped_pages(tmp_path):
    swapped = reordered_pdf(tmp_path / "swapped.pdf", [0, 4, 2, 3, 1, 5])
    with pytest.raises(AlignmentError) as err:
        convert_file(DECK_PPTX, "slides", "deck1", tmp_path / "out", ParseSettings(), swapped)
    assert err.value.report.mismatched == [2, 5]


def test_alignment_error_on_missing_page(tmp_path):
    short = reordered_pdf(tmp_path / "short.pdf", [0, 1, 2, 3, 4])
    with pytest.raises(AlignmentError, match="6 slides but the PDF has 5 pages"):
        convert_file(DECK_PPTX, "slides", "deck1", tmp_path / "out", ParseSettings(), short)


def test_hidden_slide_flag(tmp_path):
    deck = Presentation()
    for title in ("Shown", "Hidden"):
        deck.slides.add_slide(deck.slide_layouts[5]).shapes.title.text = title
    deck.slides[1]._element.set("show", "0")
    deck.save(str(tmp_path / "hidden.pptx"))
    assert [s.hidden for s in read_pptx(tmp_path / "hidden.pptx")] == [False, True]


# --- PDF slides and references ----------------------------------------------------------


def test_pdf_slides_use_the_text_layer(tmp_path):
    result = convert_file(DECK_PDF, "slides", "deck1", tmp_path, ParseSettings())
    assert result.format == "pdf" and result.pdf is None and result.alignment is None
    assert "Three Layers" in result.pages[1].text_layer
    assert all(p.notes is None for p in result.pages)
    assert [p.image_flag for p in result.pages] == EXPECTED_FLAGS


def test_pdf_reference_gets_pngs_and_flags(tmp_path):
    result = convert_file(DECK_PDF, "reference", "reading", tmp_path, ParseSettings())
    assert result.kind == "reference"
    assert [p.page_id for p in result.pages][:2] == ["reading-p01", "reading-p02"]
    assert [p.image_flag for p in result.pages] == EXPECTED_FLAGS


def test_docx_reference_is_passed_through(tmp_path):
    docx = tmp_path / "notes.docx"
    docx.write_bytes(b"PK\x03\x04 not parsed locally")
    result = convert_file(docx, "reference", "notes", tmp_path / "out", ParseSettings())
    assert (result.format, result.page_count, result.pages) == ("docx", None, [])
    assert result.file_id == file_sha256(docx)


@pytest.mark.parametrize(
    ("name", "kind"), [("notes.docx", "slides"), ("deck.pptx", "reference"), ("a.key", "slides")]
)
def test_wrong_format_for_kind_is_an_error(tmp_path, name, kind):
    path = tmp_path / name
    path.write_bytes(b"x")
    with pytest.raises(ConvertError, match="must be one of"):
        convert_file(path, kind, "x", tmp_path / "out", ParseSettings())


def test_convert_files_batch_and_source(tmp_path):
    results = convert_files([DECK_PDF], [DECK_PDF], tmp_path, ParseSettings())
    assert [r.source_id for r in results] == ["fixture-deck", "fixture-deck-2"]
    assert [r.kind for r in results] == ["slides", "reference"]
    one = convert_files([DECK_PDF], [], tmp_path, ParseSettings(), source="Deck 1")
    assert one[0].source_id == "deck-1"
    with pytest.raises(ConvertError, match="exactly one file"):
        convert_files([DECK_PDF], [DECK_PDF], tmp_path, ParseSettings(), source="deck1")
    with pytest.raises(ConvertError, match="not found"):
        convert_files([tmp_path / "missing.pdf"], [], tmp_path, ParseSettings())


# --- LibreOffice repair path (mocked) ---------------------------------------------------


def test_load_failure_retries_with_a_resaved_copy(tmp_path, monkeypatch):
    calls = []

    def fake(pptx, work_dir, image, timeout):
        calls.append(pptx.name)
        if len(calls) == 1:
            raise LibreOfficeError("source file could not be loaded", "load")
        return DECK_PDF

    monkeypatch.setattr(convert, "pptx_to_pdf", fake)
    pdf, repaired = pdf_for_pptx(DECK_PPTX, tmp_path, ParseSettings())
    assert (pdf, repaired) == (DECK_PDF, True)
    assert calls == ["fixture_deck.pptx", "repaired.pptx"]


@pytest.mark.parametrize("kind", ["timeout", "docker"])
def test_timeout_and_missing_docker_are_not_retried(tmp_path, monkeypatch, kind):
    def fake(*_args):
        raise LibreOfficeError("no", kind)

    monkeypatch.setattr(convert, "pptx_to_pdf", fake)
    with pytest.raises(LibreOfficeError) as err:
        pdf_for_pptx(DECK_PPTX, tmp_path, ParseSettings())
    assert err.value.kind == kind


# --- CLI --------------------------------------------------------------------------------


def test_cli_prep_convert(tmp_path, capsys):
    with pytest.raises(SystemExit) as code:
        main(["prep", "convert", str(DECK_PDF), "--source", "deck1", "--out", str(tmp_path)])
    assert code.value.code == 0
    printed = capsys.readouterr().out
    assert "deck1-p03 image" in printed
    assert len(list(tmp_path.glob("*/convert.json"))) == 1


def test_cli_prep_convert_reports_errors(tmp_path, capsys):
    with pytest.raises(SystemExit) as code:
        main(["prep", "convert", str(tmp_path / "missing.pdf"), "--out", str(tmp_path)])
    assert code.value.code == 1
    assert "not found" in capsys.readouterr().out


# --- LibreOffice in Docker (skipped when unavailable) -----------------------------------

needs_libreoffice = pytest.mark.skipif(
    not docker_ready(ParseSettings().libreoffice_image),
    reason="LibreOffice Docker image not available (scripts/libreoffice/build.sh)",
)


@needs_libreoffice
def test_libreoffice_converts_the_fixture_deck(tmp_path):
    result = convert_file(DECK_PPTX, "slides", "deck1", tmp_path, ParseSettings())
    assert result.page_count == 6
    assert result.alignment.ok
    assert [p.image_flag for p in result.pages] == EXPECTED_FLAGS


@needs_libreoffice
def test_libreoffice_exports_hidden_slides(tmp_path):
    deck = Presentation()
    for title in ("Shown slide", "Hidden slide"):
        deck.slides.add_slide(deck.slide_layouts[5]).shapes.title.text = title
    deck.slides[1]._element.set("show", "0")
    deck.save(str(tmp_path / "hidden.pptx"))
    result = convert_file(
        tmp_path / "hidden.pptx", "slides", "h", tmp_path / "out", ParseSettings()
    )
    assert result.page_count == 2
    assert [p.hidden for p in result.pages] == [False, True]
