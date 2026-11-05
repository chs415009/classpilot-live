"""SQL templates render with plain identifiers only; no SQL is executed."""

from pathlib import Path

import pytest

from classpilot.settings import ObjectNames
from classpilot.sql_template import PLACEHOLDER, object_names, render

SQL_DIR = Path(__file__).parents[1] / "sql"
ENV = {
    "SNOWFLAKE_ROLE": "TEST_ROLE",
    "SNOWFLAKE_WAREHOUSE": "TEST_WH",
    "SNOWFLAKE_DATABASE": "TEST_DB",
    "SNOWFLAKE_SCHEMA": "agent",
}


@pytest.mark.parametrize("name", ["04_parse_objects.sql", "05_search_service_v2.sql"])
def test_templates_render_completely(name):
    sql = render((SQL_DIR / name).read_text(), object_names(ObjectNames(), ENV))
    assert not PLACEHOLDER.search(sql)
    assert "USE SCHEMA TEST_DB.AGENT;" in sql


def test_parse_objects_use_the_configured_names():
    objects = ObjectNames(raw_stage="MY_STAGE", chunks="MY_CHUNKS")
    sql = render((SQL_DIR / "04_parse_objects.sql").read_text(), object_names(objects, ENV))
    assert "CREATE STAGE IF NOT EXISTS MY_STAGE" in sql
    assert "CREATE TABLE IF NOT EXISTS MY_CHUNKS" in sql
    assert "ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')" in sql


@pytest.mark.parametrize("bad", ["X; DROP TABLE Y", "a.b", "", "1ABC"])
def test_non_identifiers_are_rejected(bad):
    with pytest.raises(ValueError, match="not a plain identifier"):
        render("USE ROLE {{ROLE}};", object_names(ObjectNames(), {**ENV, "SNOWFLAKE_ROLE": bad}))


def test_unknown_placeholder_is_rejected():
    with pytest.raises(ValueError, match="unknown placeholders"):
        render("SELECT {{NOPE}}", object_names(ObjectNames(), ENV))
