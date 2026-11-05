import pytest

from classpilot.live.poll import PollInputError, run_poll


def test_explain_returns_text_and_show_slide_without_llm(content, make_evidence):
    out = run_poll(make_evidence({"A": 3, "B": 13, "C": 4, "D": 1}), content.manifest, "mock")
    assert out.decision.action == "explain"
    assert (out.decision.option, out.decision.misconception_id, out.decision.remediation_id) == (
        "B",
        "M-01",
        "R-01",
    )
    assert out.decision.remediation_text == content.manifest.remediations["R-01"].text
    assert out.decision.show_slide == "dbt-medallion-p03"
    assert out.decision.correct_option == "A"
    assert out.decision.escalation_reason is None
    assert out.llm_calls == 0
    assert out.nodes_run == ["threshold_check", "decide_poll", "explanation_lookup"]


def test_reveal_below_threshold(content, make_evidence):
    out = run_poll(make_evidence({"A": 8, "B": 9, "C": 3, "D": 1}), content.manifest, "mock")
    assert out.decision.action == "reveal"
    assert out.decision.correct_option == "A"
    assert out.decision.remediation_id is None and out.decision.show_slide is None
    assert out.nodes_run == ["threshold_check", "decide_poll"]


def test_rule_uses_manifest_params(content, make_evidence):
    manifest = content.manifest.model_copy(deep=True)
    manifest.params.wrong_ratio_threshold = 0.40
    out = run_poll(make_evidence({"A": 8, "B": 9, "C": 3, "D": 1}), manifest, "mock")
    assert out.decision.action == "explain"


def test_missing_link_reveals_instead(content, make_evidence):
    manifest = content.manifest.model_copy(deep=True)
    del manifest.misconceptions["M-01"]  # bypasses validation on purpose
    out = run_poll(make_evidence({"A": 3, "B": 13, "C": 4, "D": 1}), manifest, "mock")
    assert out.decision.action == "reveal"
    assert out.decision.remediation_id is None


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"lesson_id": "lesson-dbt-advanced"}, "evidence is for lesson"),
        ({"poll_id": "q-99"}, "not in lesson"),
        ({"poll_id": "q-02"}, "dropped"),
        ({"correct": "B"}, "manifest says 'A'"),
    ],
)
def test_evidence_that_does_not_match_the_manifest_raises(content, make_evidence, kwargs, message):
    with pytest.raises(PollInputError, match=message):
        run_poll(make_evidence({"A": 3, "B": 13}, **kwargs), content.manifest, "mock")
