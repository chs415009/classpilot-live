import json

import pytest

from classpilot.eval_sets import (
    DEV_SET_PATH,
    TRAIN_SET_PATH,
    load_question_set,
    split_overlap,
)
from classpilot.runner import run_eval


def write_set(tmp_path, name, split, questions, chunk_text="Stacks are LIFO."):
    data = {
        "set_id": name,
        "split": split,
        "retrieval": "inline",
        "lesson": {
            "lesson_id": "les-x",
            "objectives": [{"objective_id": "seg-01", "title": "Stacks", "keywords": ["stack"]}],
            "chunks": [{"chunk_id": "x-c1", "text": chunk_text}],
        },
        "questions": questions,
    }
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(data))
    return path


def q(qid, text, action="answer", reason=None, objective="seg-01"):
    row = {"id": qid, "objective_id": objective, "question_text": text, "expected_action": action}
    if reason:
        row["expected_reason"] = reason
    return row


def test_train_set_is_valid_and_balanced():
    train = load_question_set(TRAIN_SET_PATH)
    assert train.split == "train" and train.retrieval == "inline"
    assert 15 <= len(train.questions) <= 30
    reasons = {q.expected_reason for q in train.questions if q.expected_action == "escalate"}
    assert reasons == {"out_of_scope", "low_confidence", "unsupported"}
    assert any(q.expected_action == "answer" for q in train.questions)


def test_train_set_holds_no_real_course_names():
    text = TRAIN_SET_PATH.read_text().lower()
    for marker in ("info 6205", "info6205", "northeastern", "carrano", "pearson", "l1-"):
        assert marker not in text


@pytest.mark.skipif(not DEV_SET_PATH.exists(), reason="dev set is local only (materials/)")
def test_train_and_dev_do_not_overlap():
    assert split_overlap(load_question_set(TRAIN_SET_PATH), load_question_set(DEV_SET_PATH)) == []


def test_overlap_is_found_by_id_and_text(tmp_path):
    train = load_question_set(write_set(tmp_path, "t", "train", [q("a-1", "What is a stack?")]))
    dev = load_question_set(
        write_set(tmp_path, "d", "dev", [q("a-1", "Other?"), q("d-2", "what is a STACK")])
    )
    assert split_overlap(train, dev) == ["a-1", "d-2"]


def test_wrong_split_is_reported(tmp_path):
    a = load_question_set(write_set(tmp_path, "a", "dev", [q("a-1", "One?")]))
    b = load_question_set(write_set(tmp_path, "b", "dev", [q("b-1", "Two?")]))
    assert split_overlap(a, b) == ["splits are 'dev' and 'dev'"]


@pytest.mark.parametrize(
    "bad",
    [
        q("a-1", "Why?", action="escalate"),  # no reason
        q("a-1", "Why?", reason="out_of_scope"),  # answer with a reason
        q("a-1", "Why?", action="escalate", reason="nope"),
        q("a-1", "Why?", objective="seg-99"),
    ],
)
def test_bad_labels_are_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        load_question_set(write_set(tmp_path, "t", "train", [bad]))


def test_duplicate_ids_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        load_question_set(write_set(tmp_path, "t", "train", [q("a", "One?"), q("a", "Two?")]))


def test_run_eval_on_a_set_uses_its_lesson(tmp_path):
    path = write_set(tmp_path, "t", "train", [q("a-1", "Why is a stack LIFO?")])
    result = run_eval(set_path=path)
    assert result["set_id"] == "t" and result["split"] == "train"
    row = result["rows"][0]
    assert row["action"] == "answer" and row["citations"] == ["x-c1"]
    assert result["prompt_version"] == "uncompiled-v4"
