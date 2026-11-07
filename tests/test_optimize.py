"""Stage 12 DSPy experiment helpers (mock only, no network)."""

import json

import dspy
from test_agents import FakeEngine, chat_reply

from classpilot import optimize as opt
from classpilot.agents.program import RulesFirstChatAdapter

TRAIN = [opt.to_example(i) for i in opt.load_items(opt.TRAIN_PATH)]


def lm(engine):
    return dspy.LM("fake-model", engine=engine, cache=False, num_retries=0)


def example(label):
    return next(e for e in TRAIN if e.label == label)


def tied_pred(ex):
    chunk_id = next(iter(ex.chunk_texts))
    return dspy.Prediction(
        claims=[{"claim": "x", "chunk_id": chunk_id}], verdict="pass", reason="ok"
    )


def untied_pred():
    return dspy.Prediction(claims=[{"claim": "x", "chunk_id": None}], verdict="fail", reason="x")


def test_train_cases_are_labeled_and_synthetic():
    assert len(TRAIN) >= 40 and {e.label for e in TRAIN} == {"pass", "fail"}
    assert all(not opt.REAL_CHUNK_ID.search(cid) for e in TRAIN for cid in e.chunk_texts)


def test_metric_is_the_code_verdict_against_the_label():
    metric = opt.make_metric(0.8)
    ok, bad = example("pass"), example("fail")
    assert metric(ok, tied_pred(ok)) == 1.0
    assert metric(bad, tied_pred(bad)) == 0.0
    assert metric(bad, untied_pred()) == 1.0
    assert metric(ok, dspy.Prediction(verdict="pass")) == 0.0  # unusable output


def test_feedback_metric_explains_with_the_case_note():
    metric = opt.make_feedback_metric(0.8)
    bad = example("fail")
    out = metric(bad, tied_pred(bad))
    assert out.score == 0.0 and bad.note in out.feedback and "should fail" in out.feedback
    assert metric(bad, untied_pred()).score == 1.0


def test_evaluate_counts_catches_false_fails_and_errors():
    ok, bad = example("pass"), example("fail")
    reply = chat_reply(claims=[{"claim": "x", "chunk_id": None}], verdict="fail", reason="x")
    with dspy.context(lm=lm(FakeEngine(reply)), adapter=RulesFirstChatAdapter()):
        result = opt.evaluate(opt.GuardianProgram(), [ok, bad], 0.8)
    summary = result["summary"][ok.set_id]
    assert (summary["caught"], summary["false_fails"]) == (1, [ok.case_id])
    with dspy.context(lm=lm(FakeEngine("not a reply")), adapter=RulesFirstChatAdapter()):
        result = opt.evaluate(opt.GuardianProgram(), [ok], 0.8)
    assert result["rows"][0]["got"] == "error"


def test_leak_check_finds_real_chunk_ids_and_dev_text(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"demo": "see [l1-pdf-p02-c1] and why is a stack of books LIFO?"}))
    problems = opt.leak_problems(path, ["Why is a stack of books LIFO?"])
    assert any("l1-pdf-p02" in p for p in problems) and any("dev text" in p for p in problems)
    path.write_text(json.dumps({"demo": "[syn-p03-c3] A stack is LIFO."}))
    assert opt.leak_problems(path, ["Why is a stack of books LIFO?"]) == []


def test_new_guardian_is_saved_with_the_base_analyst_and_responder(tmp_path):
    from test_compiled import FIXTURE_DIR, FIXTURE_ID

    from classpilot.agents.compiled import load_program

    guardian = opt.guardian_predict(None)
    guardian.signature = guardian.signature.with_instructions("New instructions.")
    path = opt.save_live_program("exp-v0", FIXTURE_ID, guardian, {"optimizer": "x"}, FIXTURE_DIR)
    try:
        data = load_program("exp-v0", FIXTURE_DIR)
        assert set(data["modules"]) == {"analyst", "responder", "guardian"}
        assert data["modules"]["guardian"]["signature"]["instructions"] == "New instructions."
        assert data["meta"]["base_program"] == FIXTURE_ID
    finally:
        path.unlink()


# ---------- prep Guardians (Part B) ----------


def test_prep_train_cases_load_per_kind():
    for kind in ("script", "poll", "explanation"):
        examples = opt.prep_examples(opt.PREP_TRAIN_PATH, kind)
        assert examples and {e.label for e in examples} == {"pass", "fail"}
        assert all(not opt.REAL_CHUNK_ID.search(c) for e in examples for c in e.chunk_texts)


def test_prep_metric_uses_the_prep_rule():
    ex = opt.prep_examples(opt.PREP_TRAIN_PATH, "explanation")
    passing = next(e for e in ex if e.label == "pass")
    chunk_id, text = next(iter(passing.chunk_texts.items()))
    quote = text.split(".")[0]
    good = dspy.Prediction(
        claims=[{"claim": quote, "chunk_id": chunk_id, "quote": quote, "kind": "fact"}],
        verdict="pass",
        reason="ok",
    )
    untied = dspy.Prediction(
        claims=[{"claim": "x y z", "chunk_id": None, "quote": None, "kind": "fact"}],
        verdict="fail",
        reason="x",
    )
    metric = opt.make_prep_metric({"max_framing": 2, "rescue_coverage": 0.8})
    assert metric(passing, good) == 1.0
    assert metric(passing, untied) == 0.0


def test_prep_guardian_saved_next_to_the_base_writers(tmp_path):
    from classpilot.agents.compiled import load_program

    guardian = opt.prep_guardian_predict(None, "script")
    path = opt.save_prep_program("prep-exp-v0", None, {"script_guardian": guardian}, {}, tmp_path)
    assert set(load_program("prep-exp-v0", tmp_path)["modules"]) == {"script_guardian"}
    assert path.parent == tmp_path
