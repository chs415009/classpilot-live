import json

import pytest

from classpilot.adapters.llm import MockLLM
from classpilot.adapters.retrieval import MockRetriever, RetrievalError
from classpilot.graph import Deps, run_question
from classpilot.runner import run_eval, run_guardian_eval, run_scenario, scenario_files
from classpilot.trace import write_trace

KAFKA = "How does the Bronze layer handle streaming data from Kafka?"


# ---------- Path B ----------


def test_question_answer_has_citations_and_trace(deps, make_question):
    decision, trace = run_question(
        make_question("Why do we keep raw data in Bronze if it has errors?"), deps, 2
    )
    assert decision.action == "answer"
    assert decision.citations == ["chunk-01"]
    assert decision.escalation_reason is None
    assert trace.nodes_run == ["protected_check", "analyst", "responder", "validator"]
    assert trace.llm_calls == 2
    assert "chunk-01" in trace.retrieved_chunk_ids
    assert {"analyst", "retrieval", "responder", "total"} <= trace.latency_ms.keys()


def test_protected_question_makes_no_llm_call(deps, make_question):
    question = make_question(
        "Can you write the dbt model that deduplicates the orders table for Assignment 1?"
    )
    decision, trace = run_question(question, deps, 2)
    assert decision.escalation_reason == "assignment_like"
    assert trace.llm_calls == 0
    assert trace.nodes_run == ["protected_check", "validator"]


def test_details_keep_raw_node_outputs(deps, make_question):
    details: dict = {}
    run_question(make_question(KAFKA), deps, 3, details)
    assert details["analyst"]["category"] == "in_scope"
    assert "answer_text" in details["responder"]
    assert details["guardian"]["verdict"] == "fail"
    assert details["llm_errors"] == []


def test_mode_3_skips_guardian_when_escalation_is_certain(deps, make_question):
    # Mock responder gives low confidence for an uncovered question.
    decision, trace = run_question(
        make_question("How does dbt handle snapshots for slowly changing dimensions?"), deps, 3
    )
    assert decision.action == "escalate"
    assert "guardian" not in trace.nodes_run
    assert trace.nodes_run[-1] == "validator"


def test_mode_3_runs_guardian(deps, make_question):
    _, trace = run_question(make_question("What does ref() do in a dbt model?"), deps, 3)
    assert trace.nodes_run == ["protected_check", "analyst", "responder", "guardian", "validator"]
    assert trace.llm_calls == 3


def test_guardian_catches_what_self_check_misses(deps, make_question):
    two, _ = run_question(make_question(KAFKA), deps, 2)
    three, _ = run_question(make_question(KAFKA), deps, 3)
    assert two.action == "answer"
    assert three.escalation_reason == "unsupported"


@pytest.mark.parametrize("task", ["analyst", "responder", "guardian"])
def test_any_llm_error_escalates(settings, content, make_question, task):
    deps = Deps(settings, content, MockLLM(errors={task: "down"}), MockRetriever(content.chunks))
    decision, _ = run_question(make_question("What does ref() do in a dbt model?"), deps, 3)
    assert decision.action == "escalate"
    assert decision.escalation_reason == "llm_error"


def test_retrieval_error_escalates(settings, content, make_question):
    class DownRetriever:
        def search(self, query, top_k):
            raise RetrievalError("search down")

    deps = Deps(settings, content, MockLLM(), DownRetriever())
    decision, trace = run_question(make_question("What does ref() do in a dbt model?"), deps, 3)
    assert decision.escalation_reason == "llm_error"
    assert trace.llm_calls == 1  # analyst only; the responder never called the LLM
    assert "guardian" not in trace.nodes_run


def test_bad_llm_output_escalates(settings, content, make_question):
    deps = Deps(settings, content, MockLLM(bad_output={"responder"}), MockRetriever(content.chunks))
    decision, trace = run_question(make_question("What does ref() do in a dbt model?"), deps, 3)
    assert decision.escalation_reason == "llm_error"
    assert "guardian" not in trace.nodes_run


# ---------- scenarios, eval, trace file ----------


@pytest.mark.parametrize("path", scenario_files(), ids=lambda p: p.name)
def test_scenarios_match_expected_in_mode_3(path):
    assert run_scenario(path, 3, trace_path=None)["matches_expected"]


def test_eval_mode_3_beats_mode_2_on_unsupported():
    two, three = run_eval(2)["summary"], run_eval(3)["summary"]
    assert three["unsupported_let_through"] < two["unsupported_let_through"]
    assert three["llm_calls_avg"] > two["llm_calls_avg"]


def test_guardian_eval_runs_every_case():
    result = run_guardian_eval()
    assert result["summary"]["cases"] == len(result["rows"]) > 0
    assert result["summary"]["errors"] == []
    assert all(r["verdict"] in {"pass", "fail"} for r in result["rows"])


def test_report_runs_every_scenario(tmp_path):
    from classpilot.report import build_report

    seen = []
    html = build_report(tmp_path / "report.html", on_result=seen.append).read_text()
    question_files = [
        p for p in scenario_files() if json.loads(p.read_text())["path"] == "question"
    ]
    assert len(seen) == len(scenario_files()) + len(question_files)
    assert all(p.name in html for p in scenario_files())
    assert "3-agent mode" in html


def test_report_status_colors():
    from classpilot.report import _status_css

    escalated = {"decision": {"action": "escalate"}}
    assert _status_css({**escalated, "matches_expected": True, "expected": {}}) == "ok"
    reason_differs = {"action": "escalate", "escalation_reason": "unsupported"}
    assert (
        _status_css({**escalated, "matches_expected": False, "expected": reason_differs}) == "warn"
    )
    assert (
        _status_css({**escalated, "matches_expected": False, "expected": {"action": "answer"}})
        == "bad"
    )


def test_write_trace_appends_jsonl(tmp_path, deps, make_question):
    path = tmp_path / "traces.jsonl"
    for _ in range(2):
        _, trace = run_question(make_question("What does ref() do in a dbt model?"), deps, 2)
        write_trace(trace, path)
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["backend"] == "mock"
