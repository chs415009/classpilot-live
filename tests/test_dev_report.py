"""Stage 10 dev report: lesson folders, test-question format, `cli dev`, report sections.

Everything runs in mock mode on the committed fixture deck; nothing calls Snowflake.
"""

import copy
import json
import shutil
from pathlib import Path

import pytest

from classpilot import cli
from classpilot.contracts.trace import RECORD_MODELS, DecisionLogEntry
from classpilot.dev import report
from classpilot.dev.lessons import LessonError, load_lesson, load_questions

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "deck"
DECK_PPTX = FIXTURE_DIR / "fixture_deck.pptx"
DECK_PDF = FIXTURE_DIR / "fixture_deck.pdf"
QUESTIONS = FIXTURE_DIR / "test_questions.json"
LESSON = "fixture-lesson"


@pytest.fixture
def lessons(tmp_path, monkeypatch):
    """A lesson folder with the fixture deck, and every CLI output dir under tmp_path."""
    for name, sub in [
        ("PREP_TABLES_DIR", "tables"),
        ("CONVERT_DIR", "convert"),
        ("PARSE_REPORT_DIR", "parse"),
        ("PREP_DIR", "prep"),
        ("DEV_DIR", "dev"),
    ]:
        monkeypatch.setattr(cli, name, tmp_path / sub)
    folder = tmp_path / "lessons" / LESSON
    (folder / "slides").mkdir(parents=True)
    deck = folder / "slides" / DECK_PPTX.name
    shutil.copy(DECK_PPTX, deck)
    shutil.copy(QUESTIONS, folder / "test_questions.json")
    (folder / "lesson.yaml").write_text("title: Fixture deck\npoll_count: 3\n")
    real = cli.build_parse_deps

    def with_fixture_pdf(settings):
        deps = real(settings)
        deps.convert_root = tmp_path / "convert"
        deps.pdf_for = {deck: DECK_PDF}  # no LibreOffice in tests
        return deps

    monkeypatch.setattr(cli, "build_parse_deps", with_fixture_pdf)
    return tmp_path


def run_cli(*argv) -> int:
    with pytest.raises(SystemExit) as code:
        cli.main(list(argv))
    return code.value.code


def run_dev(root: Path, *extra) -> int:
    return run_cli(
        "dev", LESSON, "--backend", "mock", "--lessons-dir", str(root / "lessons"), *extra
    )


def only_run_dir(root: Path) -> Path:
    (run_dir,) = (root / "dev" / LESSON).iterdir()
    return run_dir


@pytest.fixture
def run_data(lessons) -> dict:
    assert run_dev(lessons) == 0
    return json.loads((only_run_dir(lessons) / "results.json").read_text())


# ---------- lesson folders and the question format ----------


def test_the_fixture_question_file_is_valid():
    qset = load_questions(QUESTIONS, LESSON)
    assert {q.category for q in qset.questions} == {"direct", "reworded", "partial", "out_of_scope"}


def write_questions(path: Path, **changes) -> Path:
    data = json.loads(QUESTIONS.read_text())
    data["questions"][0].update(changes)
    path.write_text(json.dumps(data))
    return path


@pytest.mark.parametrize(
    "changes",
    [
        {"category": "assignment"},  # not a test category
        {"expected_action": "reveal"},
        {"expected_action": "escalate", "accepted_reasons": []},
        {"accepted_reasons": ["out_of_scope"]},  # answer takes no reasons
        {"accepted_reasons": [], "expected_action": "escalate"},
        {"question_text": "  "},
        {"objective_id": "seg-01"},  # unknown field
    ],
)
def test_bad_questions_fail_the_format_check(tmp_path, changes):
    with pytest.raises(LessonError):
        load_questions(write_questions(tmp_path / "q.json", **changes), LESSON)


def test_duplicate_ids_and_another_lesson_fail(tmp_path):
    with pytest.raises(LessonError, match="duplicate"):
        load_questions(write_questions(tmp_path / "q.json", question_id="fq-02"), LESSON)
    with pytest.raises(LessonError, match="expected 'other'"):
        load_questions(QUESTIONS, "other")


def test_lesson_folder_reads_files_and_yaml(lessons):
    folder = load_lesson(LESSON, lessons / "lessons")
    assert [p.name for p in folder.slides] == ["fixture_deck.pptx"] and folder.refs == []
    assert (folder.title, folder.poll_count) == ("Fixture deck", 3)
    with pytest.raises(LessonError, match="no lesson folder"):
        load_lesson("missing", lessons / "lessons")


def test_dev_list_shows_each_lesson_folder(lessons, capsys):
    (lessons / "lessons" / "empty" / "slides").mkdir(parents=True)
    assert run_cli("dev", "--list", "--lessons-dir", str(lessons / "lessons")) == 0
    out = capsys.readouterr().out
    assert "fixture-lesson: fixture_deck.pptx · test_questions.json · last run never run" in out
    assert "empty: not usable" in out


# ---------- cli dev end to end ----------


def test_dev_writes_report_results_traces_and_index(run_data, lessons):
    run_dir = only_run_dir(lessons)
    assert (run_dir / "report.html").is_file() and (run_dir / "review.md").is_file()
    assert sorted(p.name for p in (run_dir / "slides").iterdir()) == [
        f"fixture-deck-p{n:02d}.png" for n in range(1, 7)
    ]
    # The real trace records and decision log of every question, valid against the contracts.
    records = [json.loads(line) for line in (run_dir / "traces.jsonl").read_text().splitlines()]
    for record in records:
        RECORD_MODELS[record["record_type"]].model_validate(record)
    log = (run_dir / "decision_log.jsonl").read_text().splitlines()
    assert len(log) == len(run_data["live"]["rows"]) == 4
    assert {DecisionLogEntry.model_validate_json(line).question.event_id for line in log} == {
        "fq-01",
        "fq-02",
        "fq-03",
        "fq-04",
    }
    index = (lessons / "dev" / "index.html").read_text()
    assert f"{LESSON}/{run_dir.name}/report.html" in index
    assert run_data["prep"]["ran"] and run_data["prep"]["extra_files"] == []
    assert "prompt_version" in run_data["prep"]["generation_report"]


def test_skip_prep_reuses_the_manifest_without_parsing(run_data, lessons, monkeypatch):
    def no_parse(settings):
        raise AssertionError("--skip-prep must not build the parse adapters")

    monkeypatch.setattr(cli, "build_parse_deps", no_parse)
    assert run_dev(lessons, "--skip-prep") == 0
    runs = sorted((lessons / "dev" / LESSON).glob("*/results.json"))
    assert len(runs) in (1, 2)  # same second: same run id
    assert json.loads(runs[-1].read_text())["prep"]["ran"] is False


def test_skip_prep_refuses_a_prep_of_another_backend(run_data, lessons, capsys):
    path = lessons / "prep" / LESSON / "generation_report.json"
    gen = json.loads(path.read_text())
    path.write_text(json.dumps({**gen, "backend": "cortex"}))
    assert run_dev(lessons, "--skip-prep") == 1
    assert "ran on cortex" in capsys.readouterr().out


def test_dev_stops_before_prep_on_a_bad_question_file(lessons, monkeypatch):
    write_questions(lessons / "lessons" / LESSON / "test_questions.json", category="other")
    monkeypatch.setattr(cli, "build_parse_deps", lambda s: pytest.fail("prep must not start"))
    assert run_dev(lessons) == 1


def test_dev_flags_lesson_files_that_are_not_in_the_folder(run_data, lessons, capsys):
    (lessons / "lessons" / LESSON / "refs").mkdir()
    shutil.copy(DECK_PDF, lessons / "lessons" / LESSON / "refs" / "extra.pdf")
    assert run_dev(lessons) == 0
    (lessons / "lessons" / LESSON / "refs" / "extra.pdf").unlink()
    assert run_dev(lessons, "--skip-prep") == 0
    assert "not in the folder: extra.pdf" in capsys.readouterr().out


# ---------- report sections ----------


def test_overview_status_counts_equal_the_manifest(run_data):
    manifest = run_data["prep"]["manifest"]
    summary = report.summarize(run_data)
    st = summary["statuses"]
    assert sum(st["scripts"].values()) == len(manifest["slides"])
    assert st["scripts"]["ok"] == sum(s["status"] == "ok" for s in manifest["slides"].values())
    polls = [q for seg in manifest["segments"] for q in seg["questions"].values()]
    assert sum(st["polls"].values()) == len(polls)
    explanation_items = [
        i
        for i in run_data["prep"]["generation_report"]["items"]
        if i["item"].startswith("explanation ")
    ]
    assert sum(st["explanations"].values()) == len(explanation_items)
    assert summary["active_polls"] == 3 and summary["missing_explanations"] == 0


def with_statuses(data: dict) -> dict:
    """The run data with a retried script, a fallback script, a dropped poll, and a
    wrong option whose explanation failed (left out of known_wrong)."""
    data = copy.deepcopy(data)
    m, gen = data["prep"]["manifest"], data["prep"]["generation_report"]
    slides = list(m["slides"].values())
    slides[0]["status"], slides[1]["status"] = "ok_after_retry", "fallback"
    seg1, seg3 = m["segments"][0], m["segments"][2]
    q1 = seg1["questions"]["q-01"]
    mid = q1["known_wrong"].pop("C")
    rid = m["misconceptions"].pop(mid)["remediation"]
    m["remediations"].pop(rid)
    for item in gen["items"]:
        if item["item"] == "explanation q-01 C":
            item["status"] = "dropped"
    (qid,) = seg3["questions"]
    seg3["questions"][qid].update(status="dropped", known_wrong={})
    seg3["active_poll"] = None
    return data


def test_overview_counts_retries_fallbacks_drops_and_missing_explanations(run_data):
    summary = report.summarize(with_statuses(run_data))
    st = summary["statuses"]
    assert st["scripts"]["ok_after_retry"] == 1 and st["scripts"]["fallback"] == 1
    assert st["polls"]["dropped"] == 1 and st["explanations"]["dropped"] == 1
    assert summary["active_polls"] == 2
    assert summary["missing_explanations"] == 1  # q-01 C; the dropped poll does not count
    assert summary["wrong_options"] == 6 and summary["wrong_options_explained"] == 5


def test_every_wrong_option_shows_its_explanation_or_is_marked_missing(run_data):
    data = with_statuses(run_data)
    views = report.poll_views(data["prep"]["manifest"], data["prep"]["generation_report"])
    for view in views:
        assert {w["option"] for w in view["wrong"]} == set(view["options"]) - {
            view["correct_option"]
        }
    q1 = next(v for v in views if v["poll_id"] == "q-01")
    missing = {w["option"]: w for w in q1["wrong"] if w["remediation"] is None}
    assert list(missing) == ["C"] and missing["C"]["status"] == "dropped"
    html = report.render_polls(data)
    explained = sum(1 for v in views for w in v["wrong"] if w["remediation"])
    assert html.count("<span class='ok'>explained</span>") == explained
    assert html.count("<span class='bad'>no explanation</span>") == 1
    for view in views:
        for w in view["wrong"]:
            if w["remediation"]:
                assert w["remediation"]["text"].split()[0] in html
                assert f"show_slide <b>{w['remediation']['show_slide']}</b>" in html


def test_scripts_section_lists_every_slide_with_its_script(run_data):
    html = report.render_scripts(run_data)
    for slide_id, slide in run_data["prep"]["manifest"]["slides"].items():
        assert f"src='slides/{slide_id}.png'" in html
        assert report.escape(slide["script"]) in html


def test_every_question_appears_with_expected_and_actual_mismatches_first(run_data):
    data = copy.deepcopy(run_data)
    rows = data["live"]["rows"]
    rows[2]["match"] = False  # as if fq-03 had not matched
    ordered = [r["question_id"] for r in report.ordered_rows(rows)]
    assert ordered[0] == "fq-03" and sorted(ordered) == ["fq-01", "fq-02", "fq-03", "fq-04"]
    html = report.render_questions(data, report.summarize(data))
    positions = [html.index(f"<b>{qid}</b>") for qid in ordered]
    assert positions == sorted(positions)
    for r in rows:
        assert report.escape(r["question_text"]) in html
        assert report.escape(r["why"]) in html
    assert html.count("<span class='bad'>check</span>") == 1
    summary = report.summarize(data)["questions"]
    assert (summary["total"], summary["match"], summary["to_check"]) == (4, 3, 1)


def test_answers_list_their_citations_and_retrieved_chunk_texts(run_data):
    answered = [r for r in run_data["live"]["rows"] if r["action"] == "answer"]
    assert answered
    html = report.render_questions(run_data, report.summarize(run_data))
    for r in answered:
        assert r["citations"]
        for chunk_id in r["citations"]:
            assert chunk_id in html
            assert report.escape(run_data["chunks"][chunk_id]) in html


def test_building_the_report_makes_no_llm_call(run_data, lessons, monkeypatch):
    from classpilot.adapters.llm import MockLLM
    from classpilot.adapters.mock_prep import MockPrepLLM

    def no_call(*args, **kwargs):
        raise AssertionError("the report must not call an LLM")

    monkeypatch.setattr(MockLLM, "complete", no_call)
    monkeypatch.setattr(MockPrepLLM, "complete", no_call)
    html = report.render_report(with_statuses(run_data))
    assert "<h2>Live test questions</h2>" in html and "<h2>Scripts</h2>" in html
    report.write_index(lessons / "dev")


def test_a_blocked_answer_shows_its_draft_and_the_unsupported_claim(run_data):
    data = copy.deepcopy(run_data)
    row = data["live"]["rows"][0]
    row.update(
        action="escalate",
        escalation_reason="unsupported",
        answer_text=None,
        match=False,
        rescued=["Kept by code."],
        responder={"answer_text": "Bronze is edited daily."},
        guardian={
            "verdict": "fail",
            "reason": "Not supported.",
            "claims": [
                {"claim": "Bronze is edited daily.", "chunk_id": None},
                {"claim": "Kept by code.", "chunk_id": None},
            ],
        },
    )
    html = report.render_questions(data, report.summarize(data))
    assert "Draft answer, not sent" in html and "Bronze is edited daily." in html
    assert html.count("no supporting chunk") == 1
    assert "rescued by code (words found)" in html
