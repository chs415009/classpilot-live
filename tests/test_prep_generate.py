"""Generation flow (prep/generate.py): retry with feedback, fallbacks, poll drop, manifest.

The fixture deck is parsed once with the mock parse adapters (no SQL). The mock deck
gives 3 segments of 2 slides (seg-01 p01-p02, seg-02 p03-p04, seg-03 p05-p06).
"""

import copy
from collections import defaultdict
from pathlib import Path

import pytest

from classpilot.adapters.llm import LLMError
from classpilot.adapters.mock_prep import MockPrepLLM
from classpilot.adapters.parse import MockParser, MockStage, MockVision
from classpilot.adapters.retrieval import MockRetriever
from classpilot.contracts.manifest import Manifest
from classpilot.prep.generate import (
    GenerateDeps,
    Generator,
    generate_lesson,
    load_material,
    with_retries,
)
from classpilot.prep.parse import ParseDeps, parse_lesson
from classpilot.prep.tables import LocalTables
from classpilot.settings import ParseSettings, PollSettings, PrepSettings

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "deck"
DECK_PPTX = FIXTURE_DIR / "fixture_deck.pptx"
DECK_PDF = FIXTURE_DIR / "fixture_deck.pdf"
LESSON = "lesson-gen"
P = "fixture-deck-p"  # slide id prefix

UNSUPPORTED = {
    "claims": [{"claim": "An invented fact.", "chunk_id": None}],
    "verdict": "fail",
    "reason": "Not supported.",
}
POLL_UNSUPPORTED = {
    **UNSUPPORTED,
    "wrong_options": [{"option": o, "chunk_id": None} for o in "ABCD"],
}


@pytest.fixture(scope="module")
def tables(tmp_path_factory):
    root = tmp_path_factory.mktemp("gen")
    stage = MockStage()
    deps = ParseDeps(
        stage,
        MockParser(stage),
        MockVision(),
        LocalTables(root / "tables"),
        ParseSettings(),
        root / "convert",
        {DECK_PPTX: DECK_PDF},
    )
    parse_lesson(LESSON, [DECK_PPTX], [], deps)
    return deps.tables


class Rigged:
    """The prep mock, with chosen calls replaced.

    `rules[task]` is a function (inputs, n) -> reply | Exception | None, where n counts
    that task's calls from 1; None means "use the mock".
    """

    def __init__(self, **rules):
        self.rules, self.mock = rules, MockPrepLLM()
        self.calls: list[tuple[str, dict]] = []
        self.n = defaultdict(int)

    def complete(self, task, inputs):
        self.calls.append((task, inputs))
        self.n[task] += 1
        rule = self.rules.get(task)
        reply = rule(inputs, self.n[task]) if rule else None
        if isinstance(reply, Exception):
            raise reply
        return reply if reply is not None else self.mock.complete(task, inputs)

    def inputs_of(self, task):
        return [i for t, i in self.calls if t == task]


def for_slide(slide, reply, times=99):
    """Rule: `reply` for calls about one slide (script writer/guardian), `times` times."""
    seen = []

    def rule(inputs, n):
        about = inputs.get("slide_id") or (inputs.get("cited_chunks") or [{}])[0].get("slide_id")
        if about == f"{P}{slide}" and len(seen) < times:
            seen.append(n)
            return reply
        return None

    return rule


def first_calls(reply, times):
    return lambda inputs, n: reply if n <= times else None


def run(tables, llm, material=None, **prep):
    settings = PrepSettings(**{"llm_timeout_seconds": 5, **prep})
    material = material or load_material(LESSON, tables)
    deps = GenerateDeps(llm, MockRetriever(material.retrieval_rows()), settings, PollSettings())
    return Generator(material, deps).run()


def item(result, name):
    return next(i for i in result.report.items if i.item == name)


# ---------- the happy path ----------


def test_mock_generation_gives_a_valid_manifest(tables):
    result = run(tables, MockPrepLLM())
    m = result.manifest
    Manifest.model_validate_json(m.model_dump_json())  # round trip through the model
    assert [s.segment_id for s in m.segments] == ["seg-01", "seg-02", "seg-03"]
    assert [s.active_poll for s in m.segments] == ["q-01", "q-02", "q-03"]
    assert sorted(m.misconceptions) == [f"M-{n:02d}" for n in range(1, 10)]
    assert {s.status for s in m.slides.values()} == {"ok"}
    assert m.slides[f"{P}01"].image_ref == f"slides/{P}01.png"
    for rem in m.remediations.values():
        assert rem.show_slide in m.slides and rem.citations
    assert result.report.llm_calls == 1 + 6 * 2 + 1 + 3 * (2 + 3 * 2)


def test_generation_reads_only_the_stored_parse(tables):
    class ReadOnly:
        def __init__(self, inner):
            self.inner, self.used = inner, set()

        def __getattr__(self, name):
            assert name in {"lesson_files", "lesson_chunks", "known_file"}, name
            self.used.add(name)
            return getattr(self.inner, name)

    spy = ReadOnly(tables)
    deps = GenerateDeps(MockPrepLLM(), MockRetriever([]), PrepSettings(), PollSettings())
    generate_lesson(LESSON, spy, deps)
    assert spy.used == {"lesson_files", "lesson_chunks"}


def test_poll_count_change_regenerates_without_parsing(tables):
    # Same stored parse, two poll counts; the parse adapters are never handed over.
    five = run(tables, MockPrepLLM(), poll_count=5).manifest
    one = run(tables, MockPrepLLM(), poll_count=1).manifest
    assert sum(s.active_poll is not None for s in five.segments) == 3
    assert [s.active_poll for s in one.segments] == ["q-01", None, None]
    assert len(one.misconceptions) == 3


def test_fewer_usable_segments_than_poll_count(tables):
    placer = first_calls({"segment_ids": ["seg-02"], "reason": "only one fits"}, 1)
    result = run(tables, Rigged(poll_placer=placer), poll_count=5)
    assert [s.active_poll for s in result.manifest.segments] == [None, "q-01", None]


def test_poll_count_zero_places_no_polls(tables):
    llm = Rigged()
    result = run(tables, llm, poll_count=0)
    assert all(s.active_poll is None for s in result.manifest.segments)
    assert "poll_placer" not in {t for t, _ in llm.calls}


# ---------- retry with feedback ----------


def test_fail_then_pass_is_ok_after_retry_and_feedback_reaches_the_retry(tables):
    llm = Rigged(script_guardian=for_slide("02", UNSUPPORTED, times=1))
    result = run(tables, llm)
    assert result.manifest.slides[f"{P}02"].status == "ok_after_retry"
    assert [a.outcome for a in item(result, f"script {P}02").attempts] == ["guardian", "pass"]
    p02 = [i for i in llm.inputs_of("script_writer") if i["slide_id"] == f"{P}02"]
    assert p02[0]["feedback"] == ""
    assert p02[1]["feedback"] == "- Not supported by the cited chunks: 'An invented fact.'"


def test_structure_problem_is_fed_back_without_calling_the_guardian(tables):
    markdown = {"script": "**Bronze** keeps raw data.", "citations": [f"{P}02-c1"]}
    llm = Rigged(script_writer=for_slide("02", markdown, times=1))
    result = run(tables, llm)
    attempts = item(result, f"script {P}02").attempts
    assert [a.outcome for a in attempts] == ["structure", "pass"]
    p02 = [i for i in llm.inputs_of("script_writer") if i["slide_id"] == f"{P}02"]
    assert "read aloud" in p02[1]["feedback"] and "Markdown emphasis" in p02[1]["feedback"]
    guarded = [i for i in llm.inputs_of("script_guardian") if i["script"].startswith("**")]
    assert guarded == []


def test_guardian_pass_verdict_with_unsupported_claim_still_fails(tables):
    lying = {**UNSUPPORTED, "verdict": "pass"}
    result = run(tables, Rigged(script_guardian=for_slide("01", lying, times=1)))
    assert result.manifest.slides[f"{P}01"].status == "ok_after_retry"


def test_guardian_quote_not_in_the_chunk_fails_the_attempt(tables):
    invented = {
        "claims": [{"claim": "x", "chunk_id": f"{P}03-c1", "quote": "words the chunk lacks"}],
        "verdict": "pass",
        "reason": "ok",
    }
    result = run(tables, Rigged(script_guardian=for_slide("03", invented, times=1)))
    first = item(result, f"script {P}03").attempts[0]
    assert first.outcome == "guardian" and "quote" in first.problems[0]


def test_every_attempt_keeps_its_draft(tables):
    llm = Rigged(script_guardian=for_slide("02", UNSUPPORTED, times=1))
    attempts = item(run(tables, llm), f"script {P}02").attempts
    assert all(a.draft and a.draft["script"] and "citations" in a.draft for a in attempts)
    failing = Rigged(script_writer=first_calls(LLMError("timeout"), 1))
    first = item(run(tables, failing), f"script {P}01").attempts[0]
    assert first.outcome == "llm_error" and first.draft is None


# ---------- script fallbacks ----------


def test_script_fails_twice_falls_back_to_slide_text(tables):
    result = run(tables, Rigged(script_guardian=for_slide("06", UNSUPPORTED)))
    slide = result.manifest.slides[f"{P}06"]
    assert slide.status == "fallback"
    assert slide.script == (
        "Summary. Keep bronze unchanged for replay. Clean once in silver. "
        "Aggregate for consumers in gold."  # the footer on every slide is left out
    )
    assert item(result, f"script {P}06").detail == "slide_text"


def test_code_slide_fallback_is_cleaned_for_tts(tables):
    result = run(tables, Rigged(script_guardian=for_slide("05", UNSUPPORTED)))
    script = result.manifest.slides[f"{P}05"].script
    assert "order id" in script and "{{" not in script and "_" not in script


def test_slide_without_text_falls_back_to_the_vision_description(tables):
    # p04 is image only: no text layer, a vision description.
    result = run(tables, Rigged(script_guardian=for_slide("04", UNSUPPORTED)))
    assert result.manifest.slides[f"{P}04"].script == "Mock description of page p04."
    assert item(result, f"script {P}04").detail == "vision_description"


def test_slide_without_text_or_vision_gets_the_fixed_sentence(tables):
    material = load_material(LESSON, tables)
    p04 = next(s for s in material.slides if s.slide_id == f"{P}04")
    p04.page = p04.page.model_copy(update={"llm_description": None})
    result = run(tables, Rigged(script_guardian=for_slide("04", UNSUPPORTED)), material)
    assert result.manifest.slides[f"{P}04"].script == "Please look at the slide on screen."
    assert item(result, f"script {P}04").detail == "fixed_sentence"


def test_slide_without_chunks_skips_the_writer(tables):
    material = load_material(LESSON, tables)
    p04 = next(s for s in material.slides if s.slide_id == f"{P}04")
    p04.chunks = []
    llm = Rigged()
    result = run(tables, llm, material)
    assert result.manifest.slides[f"{P}04"].status == "fallback"
    assert f"{P}04" not in [i["slide_id"] for i in llm.inputs_of("script_writer")]
    assert item(result, f"script {P}04").detail == "vision_description (no chunks)"


# ---------- polls ----------


def test_one_explanation_fails_twice_drops_the_poll_and_tries_the_next_segment(tables):
    def first_poll_first_explanation(inputs, n):
        return UNSUPPORTED if n <= 2 else None

    llm = Rigged(explanation_guardian=first_poll_first_explanation)
    result = run(tables, llm, poll_count=1)
    m = result.manifest
    dropped = m.segments[0].questions["q-01"]
    assert dropped.status == "dropped" and dropped.known_wrong == {}
    assert dropped.text  # the poll itself passed; its text stays for the report
    assert m.segments[0].active_poll is None
    assert m.segments[1].active_poll == "q-02"
    assert sorted(m.misconceptions) == ["M-01", "M-02", "M-03"]
    assert all(r.status == "ok" for r in m.remediations.values())
    # q-01 stopped at its failing explanation: 2 attempts, the other 2 not generated.
    assert len(llm.inputs_of("explanation_writer")) == 2 + 3
    assert item(result, "poll q-01 seg-01").detail == "an explanation failed"
    assert result.report.statuses("explanation q-01") == ["dropped"]


def test_explanation_failing_after_one_passed_drops_them_all(tables):
    llm = Rigged(explanation_guardian=lambda inputs, n: UNSUPPORTED if n in (2, 3) else None)
    result = run(tables, llm, poll_count=1)
    assert result.report.statuses("explanation q-01") == ["dropped", "dropped"]
    assert result.manifest.segments[1].active_poll == "q-02"


def test_poll_fails_twice_is_dropped_and_the_next_segment_is_tried(tables):
    llm = Rigged(poll_guardian=first_calls(POLL_UNSUPPORTED, 2))
    result = run(tables, llm, poll_count=2)
    segs = result.manifest.segments
    assert segs[0].questions["q-01"].status == "dropped"
    assert [s.active_poll for s in segs] == [None, "q-02", "q-03"]
    assert item(result, "poll q-01 seg-01").detail == "poll failed"
    retry = llm.inputs_of("poll_writer")[1]["feedback"]
    assert "is not shown to be wrong by the cited chunks" in retry


def test_poll_that_never_passes_structure_is_dropped_empty(tables):
    bad = {
        "question": "Q?",
        "options": {"A": "x"},
        "correct_option": "A",
        "misconceptions": [],
        "citations": [],
    }
    result = run(tables, Rigged(poll_writer=first_calls(bad, 2)), poll_count=1)
    q = result.manifest.segments[0].questions["q-01"]
    assert (q.status, q.text, q.options) == ("dropped", "", {})


def test_explanation_show_slide_problem_is_fed_back(tables):
    def wrong_slide(inputs, n):
        if n == 1:
            chunk = inputs["chunks"][0]
            return {
                "title": "t",
                "text": "x.",
                "show_slide": f"{P}06",
                "citations": [chunk["chunk_id"]],
            }
        return None

    llm = Rigged(explanation_writer=wrong_slide)
    result = run(tables, llm, poll_count=1)
    assert result.manifest.segments[0].active_poll == "q-01"
    assert (
        "show_slide must be the slide of a cited chunk"
        in (llm.inputs_of("explanation_writer")[1]["feedback"])
    )
    assert result.manifest.remediations["R-01"].status == "ok_after_retry"


def test_all_polls_dropped_gives_a_valid_manifest_without_polls(tables):
    result = run(tables, Rigged(poll_guardian=lambda i, n: POLL_UNSUPPORTED))
    m = result.manifest
    assert all(s.active_poll is None for s in m.segments)
    assert [q.status for s in m.segments for q in s.questions.values()] == ["dropped"] * 3
    assert m.misconceptions == {} and m.remediations == {}


# ---------- segments and placement ----------


def test_segmenter_failing_twice_uses_fixed_groups(tables):
    bad = {"segments": [{"slides": [f"{P}01"], "objective": "x"}]}  # misses slides
    llm = Rigged(segmenter=first_calls(bad, 2))
    result = run(tables, llm, fallback_segment_slides=3)
    segs = result.manifest.segments
    assert [s.slides for s in segs] == [
        [f"{P}01", f"{P}02", f"{P}03"],
        [f"{P}04", f"{P}05", f"{P}06"],
    ]
    assert segs[0].objective == "Understand Medallion Architecture Basics"
    assert item(result, "segments").status == "fallback"
    assert "missing" in llm.inputs_of("segmenter")[1]["feedback"]


def test_placement_failing_twice_uses_deck_order(tables):
    llm = Rigged(poll_placer=first_calls({"segment_ids": ["seg-09"], "reason": ""}, 2))
    result = run(tables, llm, poll_count=2)
    assert [s.active_poll for s in result.manifest.segments] == ["q-01", "q-02", None]
    assert item(result, "placement").detail == "deck order"


def test_placement_order_is_used_and_capped_at_poll_count(tables):
    placer = first_calls({"segment_ids": ["seg-03", "seg-01", "seg-02"], "reason": ""}, 1)
    result = run(tables, Rigged(poll_placer=placer), poll_count=2)
    assert [s.active_poll for s in result.manifest.segments] == ["q-02", None, "q-01"]


# ---------- retry limits and LLM errors ----------


@pytest.mark.parametrize("max_retries", [0, 1, 2])
def test_never_more_than_max_retries(tables, max_retries):
    llm = Rigged(
        script_guardian=lambda i, n: UNSUPPORTED,
        poll_guardian=lambda i, n: POLL_UNSUPPORTED,
    )
    result = run(tables, llm, max_retries=max_retries)
    attempts = 1 + max_retries
    assert len(llm.inputs_of("script_writer")) == 6 * attempts
    assert len(llm.inputs_of("poll_writer")) == 3 * attempts
    assert all(len(i.attempts) <= attempts for i in result.report.items)
    assert {s.status for s in result.manifest.slides.values()} == {"fallback"}


def test_llm_timeout_takes_the_same_safe_path(tables):
    llm = MockPrepLLM(delays={"script_writer": 0.5, "poll_writer": 0.5})
    result = run(tables, llm, llm_timeout_seconds=0.05)
    assert {s.status for s in result.manifest.slides.values()} == {"fallback"}
    outcomes = {a.outcome for i in result.report.items for a in i.attempts if i.item != "segments"}
    assert "llm_error" in outcomes
    timed_out = item(result, f"script {P}01").attempts
    assert [a.outcome for a in timed_out] == ["llm_error", "llm_error"]
    assert "timed out" in timed_out[0].problems[0]
    assert all(s.active_poll is None for s in result.manifest.segments)


def test_llm_errors_in_every_step_still_give_a_valid_manifest(tables):
    def boom(inputs, n):
        return LLMError("503")

    tasks = ["segmenter", "script_writer", "poll_placer", "poll_writer", "explanation_writer"]
    result = run(tables, Rigged(**dict.fromkeys(tasks, boom)))
    m = result.manifest
    assert item(result, "segments").status == "fallback"
    assert item(result, "placement").status == "fallback"
    assert {s.status for s in m.slides.values()} == {"fallback"}
    assert all(s.active_poll is None for s in m.segments)


def test_guardian_error_fails_the_attempt(tables):
    llm = Rigged(script_guardian=for_slide("01", LLMError("guardian timed out"), times=1))
    result = run(tables, llm)
    attempts = item(result, f"script {P}01").attempts
    assert [a.outcome for a in attempts] == ["llm_error", "pass"]
    p01 = [i for i in llm.inputs_of("script_writer") if i["slide_id"] == f"{P}01"]
    assert p01[1]["feedback"] == ""  # nothing for the writer to fix


def test_with_retries_statuses():
    from classpilot.prep.generate import Attempt

    answers = iter([Attempt("structure", ["Fix it."]), Attempt("pass")])
    seen = []

    def generate(feedback):
        seen.append(feedback)
        return {"x": 1}

    out, status, attempts = with_retries(generate, lambda raw: (raw, next(answers)), 1)
    assert (out, status, len(attempts)) == ({"x": 1}, "ok_after_retry", 2)
    assert seen == ["", "- Fix it."]
    fail = with_retries(generate, lambda raw: (None, Attempt("guardian", ["No."])), 0)
    assert fail[:2] == (None, None)


def test_material_needs_parsed_slides(tmp_path):
    from classpilot.prep.generate import GenerateError

    with pytest.raises(GenerateError, match="no parsed slides"):
        load_material("unknown-lesson", LocalTables(tmp_path))


def test_dropped_poll_ids_stay_sequential(tables):
    llm = Rigged(poll_guardian=first_calls(POLL_UNSUPPORTED, 2))
    m = run(tables, llm, poll_count=5).manifest
    qids = [q for s in m.segments for q in s.questions]
    assert qids == ["q-01", "q-02", "q-03"]
    assert sorted(m.segments[1].questions["q-02"].known_wrong.values()) == ["M-01", "M-02", "M-03"]


def test_manifest_is_independent_of_material_mutation(tables):
    # Generating twice from one material gives the same manifest (no shared state).
    material = load_material(LESSON, tables)
    a = run(tables, MockPrepLLM(), copy.deepcopy(material)).manifest
    b = run(tables, MockPrepLLM(), copy.deepcopy(material)).manifest
    assert a == b


def test_scripts_get_reference_chunks_beyond_the_top_hits(tables):
    material = load_material(LESSON, tables)
    for n in (1, 2, 3):
        material.chunks[f"ref-p0{n}-c1"] = {
            "chunk_id": f"ref-p0{n}-c1",
            "slide_id": None,
            "text": f"Reading {n}: like a library, the bronze layer keeps every raw copy.",
        }
    llm = Rigged()
    run(tables, llm, material, retrieval_top_k=1, script_reference_chunks=2)
    p02 = next(i for i in llm.inputs_of("script_writer") if i["slide_id"] == f"{P}02")
    refs = [c["chunk_id"] for c in p02["chunks"] if c["slide_id"] is None]
    assert len(refs) == 2
    assert p02["objective"] == "Explain Medallion Architecture Basics"


def test_no_reference_chunks_needed_keeps_the_top_hits_only(tables):
    material = load_material(LESSON, tables)
    llm = Rigged()
    run(tables, llm, material, retrieval_top_k=1, script_reference_chunks=0)
    p02 = next(i for i in llm.inputs_of("script_writer") if i["slide_id"] == f"{P}02")
    assert len(p02["chunks"]) <= 2  # its own chunk + 1 retrieved


def test_generation_progress_counts_items(tables):
    events = []
    material = load_material(LESSON, tables)
    deps = GenerateDeps(
        MockPrepLLM(), MockRetriever(material.retrieval_rows()), PrepSettings(), PollSettings()
    )
    Generator(material, deps, progress=lambda *e: events.append(e)).run()
    assert events[0][:2] == ("generating", 0)
    assert [e[3] for e in events[1:3]] == ["segments", f"script {P}01"]
    assert events[-1][1:3] == (11, 11)  # segments + 6 scripts + placement + 3 polls
    assert all(step == "generating" and done <= total for step, done, total, _ in events)
