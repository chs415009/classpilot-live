"""Vision schema/prompt sync and the parse-layer adapters. A fake connection records SQL
strings; no SQL is executed."""

import json
import re
from pathlib import Path

import pytest

from classpilot.adapters.parse import (
    CortexParser,
    CortexVision,
    MockParser,
    MockStage,
    MockVision,
    SnowflakeStage,
    SnowflakeStepError,
)
from classpilot.prep.vision import (
    VisionDescription,
    VisionReplyError,
    build_prompt,
    json_shape,
    parse_reply,
)

DECK_PDF = Path(__file__).parent / "fixtures" / "deck" / "fixture_deck.pdf"


class FakeCursor:
    def __init__(self, log, row=None, error=None):
        self.log, self.row, self.error = log, row, error

    def execute(self, sql, params=None):
        self.log.append((sql, params))
        if self.error and not sql.startswith("ALTER SESSION"):
            raise self.error
        return self

    def fetchone(self):
        return self.row

    def close(self):
        pass


class FakeConnection:
    def __init__(self, row=None, error=None):
        self.log, self.row, self.error = [], row, error

    def cursor(self):
        return FakeCursor(self.log, self.row, self.error)


# --- schema sync ------------------------------------------------------------------------


def test_prompt_shape_matches_the_model():
    shape = json.loads(json_shape())
    schema = VisionDescription.model_json_schema()
    assert list(shape) == list(VisionDescription.model_fields)
    # Every field is asked for; only has_visuals has a default (for older stored rows).
    assert set(schema["required"]) == set(shape) - {"has_visuals"}
    assert isinstance(shape["key_concepts"], list)
    assert shape["has_visuals"].startswith("true or false")
    assert json_shape() in build_prompt("text", None)


def test_prompt_rules_and_inputs():
    prompt = build_prompt("Bronze keeps raw data", "Say it twice")
    assert "Describe only what is visible" in prompt
    assert "Do not add outside knowledge" in prompt
    assert "Bronze keeps raw data" in prompt and "Say it twice" in prompt
    assert "Speaker notes:\n(none)" in build_prompt("x", None)


@pytest.mark.parametrize(
    "raw",
    [
        '{"slide_text": "a", "diagram_description": "b", "key_concepts": ["c"]}',
        '```json\n{"slide_text": "a", "diagram_description": "b", "key_concepts": ["c"]}\n```',
        json.dumps('{"slide_text": "a", "diagram_description": "b", "key_concepts": ["c"]}'),
    ],
)
def test_parse_reply_accepts_plain_fenced_and_double_encoded(raw):
    assert parse_reply(raw) == VisionDescription(
        slide_text="a", diagram_description="b", key_concepts=["c"]
    )


@pytest.mark.parametrize(("value", "expected"), [(False, False), ("false", False), ("true", True)])
def test_parse_reply_reads_has_visuals(value, expected):
    raw = json.dumps(
        {"has_visuals": value, "slide_text": "", "diagram_description": "", "key_concepts": []}
    )
    assert parse_reply(raw).has_visuals is expected


def test_older_descriptions_without_has_visuals_count_as_visual():
    old = {"slide_text": "a", "diagram_description": "b", "key_concepts": []}
    assert VisionDescription.model_validate(old).has_visuals is True


@pytest.mark.parametrize("raw", ["", "not json", '{"slide_text": "a"}', "[1, 2]"])
def test_parse_reply_rejects_other_replies(raw):
    with pytest.raises(VisionReplyError):
        parse_reply(raw)


# --- mocks ------------------------------------------------------------------------------


def test_mock_parser_reads_the_pdf_text_layer():
    stage = MockStage()
    path = stage.put(DECK_PDF, "abc")
    pages = MockParser(stage).parse(path)
    assert [p.page_index for p in pages] == [1, 2, 3, 4, 5, 6]
    assert "Three Layers" in pages[1].content


def test_mock_vision_reply_parses():
    vision = MockVision()
    reply = parse_reply(vision.describe("abc/pages/p03.png", "prompt"))
    assert reply.diagram_description == "Mock description of page p03."
    assert vision.calls == ["abc/pages/p03.png"]


# --- Cortex adapters (SQL text only) ----------------------------------------------------


def test_cortex_parser_sql_and_one_based_pages():
    reply = {"metadata": {"pageCount": 2}, "pages": [{"index": 0, "content": "A"}, {"index": 1}]}
    conn = FakeConnection(row=(json.dumps(reply),))
    pages = CortexParser(conn, "RAW_MATERIALS", 300).parse("f1/original.pdf")
    assert [(p.page_index, p.content) for p in pages] == [(1, "A"), (2, "")]
    (timeout_sql, _), (sql, params) = conn.log
    assert timeout_sql == "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 300"
    assert "AI_PARSE_DOCUMENT(TO_FILE('@RAW_MATERIALS', %s)" in sql
    assert "'page_split': TRUE" in sql and params == ("f1/original.pdf",)


def test_cortex_errors_are_classified():
    timeout = FakeConnection(error=RuntimeError("000630 (57014): Statement reached its timeout"))
    with pytest.raises(SnowflakeStepError) as err:
        CortexParser(timeout, "RAW_MATERIALS", 5).parse("x.pdf")
    assert err.value.kind == "timeout"
    broken = FakeConnection(error=RuntimeError("100351: model not available"))
    with pytest.raises(SnowflakeStepError) as err:
        CortexVision(broken, "RAW_MATERIALS", "m", 800, 30).describe("p.png", "q")
    assert err.value.kind == "error"


def test_cortex_vision_sql_and_reply():
    conn = FakeConnection(row=(json.dumps("```json\n{}\n```"),))
    raw = CortexVision(conn, "RAW_MATERIALS", "claude-haiku-4-5", 800, 60).describe("p.png", "q")
    assert raw == "```json\n{}\n```"
    sql, params = conn.log[1]
    assert re.search(
        r"AI_COMPLETE\(%s, %s, TO_FILE\('@RAW_MATERIALS', %s\), .*'max_tokens': 800", sql
    )
    assert params == ("claude-haiku-4-5", "q", "p.png")


def test_snowflake_stage_put_and_refresh(tmp_path):
    conn = FakeConnection()
    stage = SnowflakeStage(conn, "RAW_MATERIALS")
    local = tmp_path / "p01.png"
    local.write_bytes(b"x")
    assert stage.put(local, "abc/pages") == "abc/pages/p01.png"
    stage.refresh()
    put_sql, refresh_sql = conn.log[0][0], conn.log[1][0]
    assert put_sql.startswith("PUT 'file://") and "@RAW_MATERIALS/abc/pages" in put_sql
    assert "AUTO_COMPRESS = FALSE" in put_sql
    assert refresh_sql == "ALTER STAGE RAW_MATERIALS REFRESH"


def test_snowflake_stage_rejects_unsafe_names(tmp_path):
    bad = tmp_path / "it's.png"
    bad.write_bytes(b"x")
    stage = SnowflakeStage(FakeConnection(), "RAW_MATERIALS")
    with pytest.raises(ValueError, match="unsafe path"):
        stage.put(bad, "abc")
    with pytest.raises(ValueError, match="unsafe path"):
        stage.put(tmp_path, "abc; DROP")
    with pytest.raises(ValueError, match="plain identifier"):
        SnowflakeStage(FakeConnection(), "RAW; DROP")
