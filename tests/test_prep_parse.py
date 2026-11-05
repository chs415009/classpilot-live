"""Parse flow (prep/parse.py) with mock adapters and local tables; no SQL is executed."""

import json
import shutil
from pathlib import Path

import pytest

from classpilot import cli
from classpilot.adapters.parse import (
    MockParser,
    MockStage,
    MockVision,
    ParsedPageText,
    SnowflakeStepError,
)
from classpilot.prep.parse import ParseDeps, ParseError, parse_lesson
from classpilot.prep.tables import LocalTables, SnowflakeTables
from classpilot.settings import ObjectNames, ParseSettings

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "deck"
DECK_PPTX = FIXTURE_DIR / "fixture_deck.pptx"
DECK_PDF = FIXTURE_DIR / "fixture_deck.pdf"

# Fixture deck: text slides 1, 2, 5, 6; diagram 3 (text + vision); image-only 4 (notes +
# vision); slide 6 has no notes.
EXPECTED_DECK_CHUNKS = [
    ("deck1-p01-c1", "text_layer"),
    ("deck1-p02-c1", "text_layer"),
    ("deck1-p03-c1", "text_layer"),
    ("deck1-p03-c2", "llm_description"),
    ("deck1-p04-c1", "text_layer"),
    ("deck1-p04-c2", "llm_description"),
    ("deck1-p05-c1", "text_layer"),
    ("deck1-p06-c1", "text_layer"),
]


def make_deps(tmp_path, vision=None, parser=None):
    stage = MockStage()
    return ParseDeps(
        stage=stage,
        parser=parser or MockParser(stage),
        vision=vision or MockVision(),
        tables=LocalTables(tmp_path / "tables"),
        cfg=ParseSettings(),
        convert_root=tmp_path / "convert",
        pdf_for={DECK_PPTX: DECK_PDF},
    )


def copy_as(tmp_path, source: Path, name: str) -> Path:
    target = tmp_path / "in" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


@pytest.fixture
def docx(tmp_path):
    path = tmp_path / "in" / "Reading Notes.docx"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PK\x03\x04 synthetic docx bytes")
    return path


def test_mock_end_to_end_fixture_deck(tmp_path, docx):
    deps = make_deps(tmp_path)
    reports = parse_lesson("lesson-a", [DECK_PPTX], [docx], deps, source=None)
    assert [r.source_id for r in reports] == ["fixture-deck", "reading-notes"]
    chunks = deps.tables.lesson_chunks("lesson-a")
    deck = [(c.chunk_id.replace("fixture-deck", "deck1"), c.origin) for c in chunks[:8]]
    assert deck == EXPECTED_DECK_CHUNKS
    assert [c.chunk_id for c in chunks[8:]] == ["reading-notes-p01-c1"]
    p04 = next(c for c in chunks if c.chunk_id == "fixture-deck-p04-c1")
    assert p04.text.startswith("Speaker notes: The chart shows")
    parsed = deps.tables.known_file(reports[0].file_id)
    assert [p.parse_method for p in parsed.pages] == [
        "local_text",
        "local_text",
        "local_text+vision",
        "local_text+vision",
        "local_text",
        "local_text",
    ]
    assert deps.tables.refreshes == 1
    raw = deps.tables.raw_files()
    assert [(r["lesson_id"], r["kind"], r["format"]) for r in raw] == [
        ("lesson-a", "slides", "pptx"),
        ("lesson-a", "reference", "docx"),
    ]


def test_only_image_and_unsure_pages_reach_vision(tmp_path):
    vision = MockVision()
    deps = make_deps(tmp_path, vision=vision)
    reports = parse_lesson("lesson-a", [DECK_PPTX], [DECK_PDF], deps)
    deck_id, ref_id = (r.file_id for r in reports)
    assert vision.calls == [
        f"{deck_id}/pages/p03.png",
        f"{deck_id}/pages/p04.png",
        f"{ref_id}/pages/p03.png",
        f"{ref_id}/pages/p04.png",
    ]
    # Only the flagged PNGs and the originals were uploaded; one refresh after all uploads.
    pngs = sorted(p for p in deps.stage.files if p.endswith(".png"))
    assert len(pngs) == 4 and deps.stage.refreshes == 1
    assert reports[1].parse_calls == 1 and reports[0].parse_calls == 0


def test_known_hash_is_never_parsed_again(tmp_path):
    vision = MockVision()
    stage = MockStage()
    parser = MockParser(stage)
    deps = make_deps(tmp_path, vision=vision, parser=parser)
    deps.stage = stage
    parse_lesson("lesson-a", [DECK_PPTX], [DECK_PDF], deps)
    calls = (len(vision.calls), len(parser.calls), len(stage.files))

    reports = parse_lesson("lesson-b", [DECK_PPTX], [DECK_PDF], deps)
    assert all(r.reused for r in reports)
    assert (len(vision.calls), len(parser.calls), len(stage.files)) == calls
    ids_a = [c.chunk_id for c in deps.tables.lesson_chunks("lesson-a")]
    ids_b = [c.chunk_id for c in deps.tables.lesson_chunks("lesson-b")]
    assert ids_a == ids_b and len(ids_a) == len(set(ids_a))

    # A re-run for the same lesson replaces that file's chunks instead of adding copies;
    # chunks of the lesson's other files stay.
    parse_lesson("lesson-a", [DECK_PPTX], [], deps)
    again = [c.chunk_id for c in deps.tables.lesson_chunks("lesson-a")]
    assert sorted(again) == sorted(ids_a)


def test_source_ids_are_unique_across_files_and_kept_with_the_hash(tmp_path):
    deps = make_deps(tmp_path)
    first = copy_as(tmp_path, DECK_PDF, "Week 1.pdf")
    parse_lesson("lesson-a", [first], [], deps)
    other = tmp_path / "other" / "Week 1.pdf"  # same name, different file
    other.parent.mkdir()
    other.write_bytes(DECK_PDF.read_bytes() + b"\n% changed")
    second = parse_lesson("lesson-b", [other], [], deps)
    assert second[0].source_id == "week-1-2"
    renamed = copy_as(tmp_path, DECK_PDF, "renamed.pdf")  # known hash, new name
    assert parse_lesson("lesson-c", [renamed], [], deps)[0].source_id == "week-1"


def test_failed_vision_keeps_the_page_text(tmp_path):
    class FlakyVision(MockVision):
        def describe(self, stage_path, prompt):
            if stage_path.endswith("p03.png"):
                raise SnowflakeStepError("000630 timeout", "timeout")
            if stage_path.endswith("p04.png"):
                return "Sorry, I cannot help with that."
            return super().describe(stage_path, prompt)

    deps = make_deps(tmp_path, vision=FlakyVision())
    report = parse_lesson("lesson-a", [DECK_PPTX], [], deps)[0]
    assert report.vision_failed == ["fixture-deck-p03", "fixture-deck-p04"]
    pages = deps.tables.known_file(report.file_id).pages
    assert pages[2].parse_method == "local_text+vision_failed"
    assert pages[2].llm_description is None
    origins = {c.chunk_id: c.origin for c in deps.tables.lesson_chunks("lesson-a")}
    assert origins["fixture-deck-p03-c1"] == "text_layer"
    assert "fixture-deck-p03-c2" not in origins


def test_pdf_reference_parse_failure_falls_back_to_local_text(tmp_path, docx):
    class FailingParser:
        def parse(self, stage_path):
            raise SnowflakeStepError("100xyz parse error", "error")

    deps = make_deps(tmp_path, parser=FailingParser())
    report = parse_lesson("lesson-a", [], [DECK_PDF], deps)[0]
    assert report.parse_fallback
    pages = deps.tables.known_file(report.file_id).pages
    assert pages[0].parse_method == "local_text_fallback"
    assert "Medallion" in pages[0].text_layer
    with pytest.raises(ParseError, match="AI_PARSE_DOCUMENT failed"):
        parse_lesson("lesson-a", [], [docx], deps)


def test_parse_page_count_must_match_the_pdf(tmp_path):
    class ShortParser:
        def parse(self, stage_path):
            return [ParsedPageText(1, "only one page")]

    with pytest.raises(ParseError, match="returned 1 pages, the PDF has 6"):
        parse_lesson("lesson-a", [], [DECK_PDF], make_deps(tmp_path, parser=ShortParser()))


def test_input_errors(tmp_path, docx):
    deps = make_deps(tmp_path)
    with pytest.raises(ParseError, match="not found"):
        parse_lesson("lesson-a", [tmp_path / "missing.pdf"], [], deps)
    with pytest.raises(ParseError, match="exactly one file"):
        parse_lesson("lesson-a", [DECK_PDF], [docx], deps, source="x")


# --- Snowflake tables (SQL text only) ---------------------------------------------------


class RecordingConnection:
    def __init__(self, error=None):
        self.sql, self.error = [], error

    def cursor(self):
        conn = self

        class Cursor:
            def execute(self, sql, params=None):
                conn.sql.append(sql)
                if conn.error:
                    raise conn.error
                return self

            def executemany(self, sql, rows):
                conn.sql.append(f"{sql} x{len(rows)}")

            def fetchall(self):
                return []

            def close(self):
                pass

        return Cursor()


def test_snowflake_tables_sql_and_missing_service(tmp_path):
    conn = RecordingConnection()
    tables = SnowflakeTables(conn, ObjectNames())
    deps = make_deps(tmp_path)
    parse_lesson("lesson-a", [DECK_PPTX], [], deps)
    chunks = deps.tables.lesson_chunks("lesson-a")
    tables.replace_chunks("lesson-a", chunks[0].file_id, chunks)
    assert conn.sql[0].startswith("DELETE FROM LESSON_CHUNKS_V2 WHERE LESSON_ID = %s")
    assert conn.sql[1].startswith("INSERT INTO LESSON_CHUNKS_V2") and conn.sql[1].endswith("x8")
    assert tables.known_file("nope") is None
    missing = SnowflakeTables(
        RecordingConnection(RuntimeError("Cortex Search Service does not exist")), ObjectNames()
    )
    assert missing.refresh_search() is False
    with pytest.raises(ValueError, match="plain identifiers"):
        SnowflakeTables(conn, ObjectNames(chunks="X; DROP"))


def test_lesson_files_in_upload_order(tmp_path, docx):
    deps = make_deps(tmp_path)
    parse_lesson("lesson-a", [DECK_PPTX], [docx], deps)
    files = deps.tables.lesson_files("lesson-a")
    assert [(f.source_id, f.kind) for f in files] == [
        ("fixture-deck", "slides"),
        ("reading-notes", "reference"),
    ]
    assert deps.tables.lesson_files("other") == []
    conn = RecordingConnection()
    assert SnowflakeTables(conn, ObjectNames()).lesson_files("lesson-a") == []
    assert conn.sql == [
        "SELECT FILE_ID FROM RAW_FILES WHERE LESSON_ID = %s ORDER BY UPLOADED_AT, FILE_ID"
    ]


# --- CLI --------------------------------------------------------------------------------


def test_cli_prep_parse_and_search_mock(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "PREP_TABLES_DIR", tmp_path / "tables")
    monkeypatch.setattr(cli, "CONVERT_DIR", tmp_path / "convert")
    monkeypatch.setattr(cli, "PARSE_REPORT_DIR", tmp_path / "parse")
    with pytest.raises(SystemExit) as code:
        cli.main(["prep", "parse", "--lesson", "l1", str(DECK_PDF)])
    assert code.value.code == 0
    report = json.loads((tmp_path / "parse" / "l1.json").read_text())
    assert report["backend"] == "mock" and len(report["chunks"]) == 7
    capsys.readouterr()
    with pytest.raises(SystemExit):
        cli.main(["prep", "search", "--lesson", "l1", "dbt model select"])
    assert "fixture-deck-p05-c1" in capsys.readouterr().out


def test_parse_progress_moves_forward_through_the_steps(tmp_path, docx):
    events = []
    deps = make_deps(tmp_path)
    parse_lesson("lesson-a", [DECK_PPTX], [docx], deps, progress=lambda *e: events.append(e))
    steps = [e[0] for e in events]
    order = ["converting", "uploading", "parsing", "chunking"]
    assert [s for i, s in enumerate(steps) if i == 0 or steps[i - 1] != s] == order
    parsing = [(done, total) for step, done, total, _ in events if step == "parsing"]
    assert parsing[0] == (0, 6) and parsing[-1] == (7, 7)  # 6 slides, then 1 DOCX page
    assert events[-1][:3] == ("chunking", 2, 2)


def test_known_files_skip_upload_and_parse_progress(tmp_path):
    deps = make_deps(tmp_path)
    parse_lesson("lesson-a", [DECK_PPTX], [], deps)
    events = []
    parse_lesson("lesson-b", [DECK_PPTX], [], deps, progress=lambda *e: events.append(e))
    assert ("uploading", 0, 0, "") in events and ("parsing", 0, 0, "") in events
    assert deps.stage.refreshes == 1  # only the first lesson uploaded anything
