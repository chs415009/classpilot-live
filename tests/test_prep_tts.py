"""TTS cleanup (prep/tts.py): one rule table for the script lint and the fallback text."""

import pytest

from classpilot.prep.tts import clean_for_tts, strip_lines, template_lines, tts_issues

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
        ("Load raw data; clean it later", "Load raw data, clean it later."),
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
        "Summary. Keep bronze unchanged. Clean once."
    )
    assert clean_for_tts("   \n\n") == ""


REAL_STYLE_PAGES = [
    "Outline\nFall 2025\nINFO 6205 - Course\n4\n•\nIntroduction\n•\nJava Review - 1",
    "Data\nFall 2025\nINFO 6205 - Course\n5\n○\nStack of books",
    "Summary\nFall 2025\nINFO 6205  -  Course\n6",
]


def test_template_lines_are_the_lines_on_most_pages():
    assert template_lines(REAL_STYLE_PAGES) == {"fall 2025", "info 6205 - course"}
    assert template_lines(REAL_STYLE_PAGES[:2]) == set()  # needs at least 3 pages


def test_slide_text_fallback_without_footer_page_number_or_bullet_lines():
    drop = template_lines(REAL_STYLE_PAGES)
    assert clean_for_tts(strip_lines(REAL_STYLE_PAGES[0], drop)) == (
        "Outline. Introduction. Java Review - 1."
    )
    assert clean_for_tts(strip_lines(REAL_STYLE_PAGES[1], drop)) == "Data. Stack of books."


def test_urls_are_removed_and_flagged():
    text = "Image Sources\nhttps://example.com/a/b.jpg\nSee www.example.org"
    assert clean_for_tts(text) == "Image Sources. See."
    assert tts_issues("See https://example.com") == ["URL"]


def test_plain_double_quotes_are_not_a_tts_issue():
    assert tts_issues('The term "queue" means a line.') == []


def test_boilerplate_lines_are_not_read_aloud():
    # Stage 12: L1's title slide fell back to its slide text and read the ISBN line.
    from classpilot.prep.tts import clean_for_tts, strip_boilerplate

    slide = "\n".join(
        [
            "Lecture 2: Lists and Stacks",
            "Prof. Ada Example, Ph.D.",
            "Materials are edited by Prof. Example from A Data Book, 3rd edition.",
            "ISBN-13 978-0-00-000000-0 2019 Example Press, Inc.",
            "© 2020 Example Press. All rights reserved.",
        ]
    )
    spoken = clean_for_tts(strip_boilerplate(slide))
    assert spoken.startswith("Lecture 2: Lists and Stacks.")
    assert "Ada Example" in spoken
    for gone in ("ISBN", "edited", "Press", "rights"):
        assert gone not in spoken


def test_boilerplate_keeps_ordinary_lines():
    from classpilot.prep.tts import strip_boilerplate

    text = "A stack is last in, first out.\nIn 2019 the course added a lab."
    assert strip_boilerplate(text) == text


def test_generated_text_loses_brackets_but_keeps_words():
    from classpilot.prep.tts import generated_text_issues, tidy_generated

    text = tidy_generated("The instructor is Prof. Ada (Jo) Example [PhD], from **NU**.")
    assert text == "The instructor is Prof. Ada Jo Example PhD, from NU."
    assert generated_text_issues(text) == []
    assert generated_text_issues(tidy_generated("Use {{ ref }} here."))  # code stays flagged
