"""TTS cleanup (prep/tts.py): one rule table for the script lint and the fallback text."""

import pytest

from classpilot.prep.tts import clean_for_tts, tts_issues

FIXTURE_CODE_SLIDE = (
    "A Silver Model in dbt\n"
    "SELECT order_id,\n"
    "       customer_id,\n"
    "       CAST(amount AS NUMBER(10, 2)) AS amount\n"
    "FROM {{ source('shop', 'raw_orders') }}\n"
    "WHERE status IS NOT NULL"
)


def test_code_slide_is_spelled_out_for_tts():
    assert clean_for_tts(FIXTURE_CODE_SLIDE) == (
        "A Silver Model in dbt. SELECT order id, customer id, CAST amount AS NUMBER 10, 2 "
        "AS amount. FROM source shop, raw orders. WHERE status IS NOT NULL."
    )


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("Open model.sql", "Open model dot s q l."),
        ("amount >= 10", "amount greater than or equal to 10."),
        ("a <= b and c != d", "a less than or equal to b and c not equal to d."),
        ("status = 'ok'", "status equals ok."),
        ("raw -> clean", "raw to clean."),
        ("50% of rows", "50 percent of rows."),
        ("ELT/ETL", "ELT slash ETL."),
        ("SELECT * FROM t;", "SELECT star FROM t."),
        ("Use `ref()` here", "Use ref here."),
        ("## Title\n- **Bronze** keeps raw data", "Title. Bronze keeps raw data."),
        ("See [the docs](https://example.com)", "See the docs."),
    ],
)
def test_symbols_and_markdown(text, spoken):
    assert clean_for_tts(text) == spoken
    assert tts_issues(text)  # the lint flags every one of them


@pytest.mark.parametrize(
    "text",
    [
        "Today we look at three layers: Bronze, Silver, and Gold.",
        "It's the students' answers that count. Ready? Let's go!",
        "A well-known pattern keeps raw data, then cleans it.",
    ],
)
def test_plain_speech_has_no_issues_and_is_unchanged(text):
    assert tts_issues(text) == []
    assert clean_for_tts(text) == text


def test_issue_names_describe_the_problem():
    assert tts_issues("```sql\nSELECT 1\n```") == ["code fence"]
    assert tts_issues("x >= 1") == ["comparison"]  # not also reported as an equals sign


def test_lines_become_sentences_and_empty_lines_vanish():
    assert clean_for_tts("Summary\n\nKeep bronze unchanged\nClean once,") == (
        "Summary. Keep bronze unchanged. Clean once,"
    )
    assert clean_for_tts("   \n\n") == ""
