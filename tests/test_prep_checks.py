"""Stage 7 checks on a generated manifest, the review sheet, and the report readings."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from test_prep_generate import UNSUPPORTED, Rigged, for_slide, run, tables  # noqa: F401

from classpilot.adapters.mock_prep import MockPrepLLM
from classpilot.prep.checks import manifest_check_problems
from classpilot.prep.review import render_review

GOLDEN = Path(__file__).parent / "fixtures" / "deck" / "manifest_mock.json"
P = "fixture-deck-p"


@pytest.fixture
def generated(tables):  # noqa: F811
    result = run(tables, MockPrepLLM())
    report = {**asdict(result.report), "summary": result.report.summary()}
    chunks = tables.lesson_chunks("lesson-gen")
    return result.manifest, report, {c.chunk_id: c.page_id for c in chunks}, chunks


def test_generated_manifest_passes_every_check(generated):
    manifest, report, pages, _ = generated
    assert manifest_check_problems(manifest, report, pages, poll_count=5) == []


def test_citation_missing_from_the_lesson_chunks(generated):
    manifest, report, pages, _ = generated
    del pages[f"{P}02-c1"]
    problems = manifest_check_problems(manifest, report, pages, 5)
    assert any(f"citation '{P}02-c1' is not a chunk of the lesson" in p for p in problems)


def test_show_slide_not_among_the_cited_slides(generated):
    manifest, report, pages, _ = generated
    manifest.remediations["R-01"].show_slide = f"{P}06"
    problems = manifest_check_problems(manifest, report, pages, 5)
    assert problems == [f"R-01: show_slide '{P}06' is not a slide of its citations"]


def test_script_failing_the_tts_lint(generated):
    manifest, report, pages, _ = generated
    manifest.slides[f"{P}03"].script = "Use `ref()`."
    problems = manifest_check_problems(manifest, report, pages, 5)
    assert problems == [f"script {P}03: TTS lint (backtick, bracket)"]


def test_item_without_a_report_entry(generated):
    manifest, report, pages, _ = generated
    report["items"] = [i for i in report["items"] if i["item"] != f"script {P}01"]
    assert manifest_check_problems(manifest, report, pages, 5) == [f"script {P}01: no report entry"]


def test_active_poll_pointing_to_a_dropped_question(generated):
    manifest, report, pages, _ = generated
    manifest.segments[0].questions["q-01"].status = "dropped"  # bypasses the validator
    problems = manifest_check_problems(manifest, report, pages, 5)
    assert "seg-01: active_poll q-01 is dropped" in problems


def test_too_many_active_polls_for_poll_count(generated):
    manifest, report, pages, _ = generated
    assert manifest_check_problems(manifest, report, pages, poll_count=2) == [
        "3 active polls, at most 2 allowed."
    ]


# ---------- report readings ----------


def test_report_records_calls_latency_citations_and_the_guardian_reply(tables):  # noqa: F811
    result = run(tables, Rigged(script_guardian=for_slide("02", UNSUPPORTED, times=1)))
    by_name = {i.item: i for i in result.report.items}
    p02 = by_name[f"script {P}02"]
    assert [a.calls for a in p02.attempts] == [2, 2]  # writer + Guardian each time
    assert p02.attempts[0].guardian == UNSUPPORTED
    assert all(a.latency_ms >= 0 for a in p02.attempts)
    assert p02.citations == [f"{P}02-c1"]
    assert by_name["placement"].detail.startswith("ranked: seg-01, seg-02, seg-03")
    summary = result.report.summary()
    assert summary["script"]["statuses"] == {"ok": 5, "ok_after_retry": 1}
    assert summary["script"]["retries"] == 1 and summary["script"]["calls"] == 14
    assert sum(row["calls"] for row in summary.values()) == result.report.llm_calls


def test_llm_errors_are_counted_per_kind(tables):  # noqa: F811
    from classpilot.adapters.llm import LLMError

    llm = Rigged(poll_placer=lambda i, n: LLMError("503"))
    summary = run(tables, llm).report.summary()
    assert summary["placement"]["llm_errors"] == 2
    assert summary["placement"]["statuses"] == {"fallback": 1}


# ---------- review sheet ----------


def test_review_sheet_has_every_section(generated):
    manifest, report, _, chunks = generated
    text = render_review(manifest, report, {c.chunk_id: c.text for c in chunks})
    for heading in [
        "## Readings per item type",
        "## Segments and placement",
        "## Scripts",
        "## Polls",
        "## Guardian decisions",
        "## Cited chunks",
    ]:
        assert heading in text
    assert text.count("| fixture-deck-p0") == len(manifest.slides)
    assert "(correct)" in text and "show_slide `fixture-deck-p0" in text


def test_review_sheet_lists_guardian_fails_and_dropped_polls(tables):  # noqa: F811
    poll_fail = {**UNSUPPORTED, "wrong_options": []}
    llm = Rigged(poll_guardian=lambda i, n: poll_fail if n <= 2 else None)
    result = run(tables, llm, poll_count=1)
    report = asdict(result.report)
    text = render_review(result.manifest, report, {})
    assert "### q-01 (seg-01): `dropped`" in text and "Dropped: poll failed." in text
    assert "**poll q-01 seg-01**, attempt 1: rule says `guardian`" in text
    assert "- claim: An invented fact. -> `None`" in text


def test_golden_manifest_still_passes_the_checks(generated):
    _, report, pages, _ = generated
    from classpilot.contracts.manifest import Manifest

    golden = Manifest.model_validate(json.loads(GOLDEN.read_text()))
    # The golden file is the CLI lesson; same deck, so same slide and chunk ids.
    assert manifest_check_problems(golden, report, pages, 5) == []
