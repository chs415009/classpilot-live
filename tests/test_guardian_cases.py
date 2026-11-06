import json

import pytest

from classpilot.adapters.llm import MockLLM
from classpilot.adapters.mock_prep import MockPrepLLM
from classpilot.guardian_cases import (
    TRAIN_CASES_PATH,
    V1_CASES_PATH,
    case_sheet,
    label_problems,
    load_cases,
    run_case_eval,
)
from classpilot.runner import run_guardian_eval
from classpilot.settings import load_settings

CHUNK = {"chunk_id": "x-c1", "text": "A stack removes the last item added first."}


def case(cid, kind, **fields):
    base = {"id": cid, "kind": kind, "chunks": [CHUNK], "expected": "pass"}
    return {**base, **fields}


LIVE = case(
    "l-1",
    "live",
    question_text="What is a stack?",
    answer_text="A stack removes the last item added first.",
)
SCRIPT = case("s-1", "script", script="A stack removes the last item added first.")
POLL = case(
    "p-1",
    "poll",
    question="What does a stack remove first?",
    options={"A": "The last item added", "B": "The first item added"},
    correct_option="A",
    shown_wrong={"B": True},
)
EXPLANATION = case(
    "e-1",
    "explanation",
    question="What does a stack remove first?",
    options={"A": "The last item added", "B": "The first item added"},
    wrong_option="B",
    explanation="A stack removes the last item added first.",
)


def write(tmp_path, cases, split="dev"):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"set_id": "t", "split": split, "cases": cases}))
    return path


def test_v1_cases_load_as_labeled_live_train_set():
    cases = load_cases(V1_CASES_PATH)
    assert cases.split == "train" and len(cases.cases) == 12
    assert {c.kind for c in cases.cases} == {"live"}
    assert all(c.chunks for c in cases.cases) and label_problems(cases) == []


def test_synthetic_train_cases_load():
    cases = load_cases(TRAIN_CASES_PATH)
    assert cases.split == "train" and all(c.kind == "live" for c in cases.cases)
    assert all(c.id.startswith("gs-") for c in cases.cases)


def test_missing_item_fields_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="lacks"):
        load_cases(write(tmp_path, [case("s-1", "script")]))


def test_poll_shown_wrong_must_cover_the_wrong_options(tmp_path):
    with pytest.raises(ValueError, match="shown_wrong"):
        load_cases(write(tmp_path, [{**POLL, "shown_wrong": {}}]))


def test_label_problems(tmp_path):
    cases = [
        {**SCRIPT, "expected": None},
        {**POLL, "id": "p-2", "shown_wrong": {"B": None}},
        {**POLL, "id": "p-3", "shown_wrong": {"B": False}},
    ]
    problems = label_problems(load_cases(write(tmp_path, cases)))
    assert problems == [
        "s-1: expected is not labeled",
        "p-2: shown_wrong not labeled for ['B']",
        "p-3: pass, but a wrong option is not shown wrong",
    ]


def test_unlabeled_sets_are_not_used_as_a_metric(tmp_path):
    case_set = load_cases(write(tmp_path, [{**SCRIPT, "expected": None}]))
    with pytest.raises(ValueError, match="unlabeled"):
        run_case_eval(case_set, load_settings())


def test_every_kind_runs_through_its_guardian_and_rule(tmp_path):
    case_set = load_cases(write(tmp_path, [LIVE, SCRIPT, POLL, EXPLANATION]))
    llms = {
        "live": MockLLM(),
        "script": MockPrepLLM(),
        "poll": MockPrepLLM(),
        "explanation": MockPrepLLM(),
    }
    result = run_case_eval(case_set, load_settings(), llms)
    assert [r["verdict"] for r in result["rows"]] == ["pass"] * 4
    summary = result["summary"]
    assert set(summary["by_kind"]) == {"live", "script", "poll", "explanation"}
    assert summary["poll_options"] == {
        "options": 1,
        "agree": 1,
        "accepted_but_labeled_not_shown": [],
        "rejected_but_labeled_shown": [],
    }


def test_invented_claims_fail_and_count_as_caught(tmp_path):
    bad = {
        **SCRIPT,
        "id": "s-2",
        "expected": "fail",
        "script": "A stack removes the last item added first. Stacks are faster than queues.",
    }
    case_set = load_cases(write(tmp_path, [SCRIPT, bad]))
    result = run_case_eval(case_set, load_settings(), {"script": MockPrepLLM()})
    assert result["summary"]["caught"] == 1 and result["summary"]["missed"] == []


def test_a_wrong_option_the_guardian_accepts_against_the_label_is_listed(tmp_path):
    poll = {**POLL, "expected": "fail", "shown_wrong": {"B": False}}
    result = run_case_eval(
        load_cases(write(tmp_path, [poll])), load_settings(), {"poll": MockPrepLLM()}
    )
    # The mock "shows" every wrong option with the first chunk.
    assert result["summary"]["poll_options"]["accepted_but_labeled_not_shown"] == ["p-1:B"]
    assert result["summary"]["missed"] == ["p-1"]


def test_guardian_llm_errors_are_counted(tmp_path):
    case_set = load_cases(write(tmp_path, [SCRIPT]))
    result = run_case_eval(case_set, load_settings(), {"script": _Failing()})
    assert result["summary"]["errors"] == ["s-1"] and result["summary"]["error_rate"] == 1.0


class _Failing:
    def complete(self, task, inputs):
        raise RuntimeError("malformed reply")


def test_default_guardian_eval_still_runs_the_v1_cases():
    result = run_guardian_eval()
    assert result["set_id"] == "v1-guardian-cases" and result["summary"]["cases"] == 12


def test_sheet_hides_the_stage7_verdict(tmp_path):
    poll = {**POLL, "stage7": {"verdict": "fail", "problems": ["secret"]}}
    sheet = case_sheet(load_cases(write(tmp_path, [poll])))
    assert "p-1 - poll" in sheet and "B: The first item added" in sheet
    assert "secret" not in sheet
