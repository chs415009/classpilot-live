import json

import pytest

from classpilot.adapters.llm import MockLLM
from classpilot.adapters.retrieval import MockRetriever, RetrievalError
from classpilot.live.question_graph import Deps, run_question
from classpilot.runner import run_eval, run_guardian_eval, run_scenario, scenario_files
from classpilot.trace import write_trace

KAFKA = "How does the Bronze layer handle streaming data from Kafka?"
REF = "What does ref() do in a dbt model?"
ALL_NODES = ["analyst", "retrieval", "responder", "guardian", "validator"]


def test_question_answer_has_citations_and_trace(deps, make_question):
    decision, trace = run_question(
        make_question("Why do we keep raw data in Bronze if it has errors?"), deps
    )
    assert decision.action == "answer"
    assert decision.citations == ["chunk-01"]
    assert decision.escalation_reason is None
    assert trace.nodes_run == ALL_NODES
    assert trace.llm_calls == 3
    assert "chunk-01" in trace.retrieved_chunk_ids
    assert {"analyst", "retrieval", "responder", "guardian", "total"} <= trace.latency_ms.keys()


def test_assignment_question_stops_at_the_analyst(deps, make_question):
    question = make_question(
        "Can you write the dbt model that deduplicates the orders table for Assignment 1?"
    )
    decision, trace = run_question(question, deps)
    assert decision.escalation_reason == "assignment_like"
    assert trace.llm_calls == 1
    assert trace.nodes_run == ["analyst", "validator"]
    assert trace.retrieved_chunk_ids == []


def test_details_keep_raw_node_outputs(deps, make_question):
    details: dict = {}
    run_question(make_question(KAFKA), deps, details)
    assert details["analyst"]["category"] == "in_scope"
    assert "answer_text" in details["responder"]
    assert details["guardian"]["verdict"] == "fail"
    assert details["llm_errors"] == []


def test_skips_guardian_when_escalation_is_certain(deps, make_question):
    # Mock responder gives low confidence for an uncovered question.
    decision, trace = run_question(
        make_question("How does dbt handle snapshots for slowly changing dimensions?"), deps
    )
    assert decision.action == "escalate"
    assert trace.nodes_run == ["analyst", "retrieval", "responder", "validator"]


def test_guardian_catches_what_self_check_misses(deps, make_question):
    decision, trace = run_question(make_question(KAFKA), deps)
    assert decision.escalation_reason == "unsupported"
    assert "guardian" in trace.nodes_run


def test_retrieval_is_filtered_by_lesson(deps, make_question):
    text = "What do dbt snapshots record over time?"
    own, own_trace = run_question(make_question(text), deps)
    other, other_trace = run_question(make_question(text, lesson_id="lesson-dbt-advanced"), deps)
    assert "adv-chunk-01" not in own_trace.retrieved_chunk_ids
    assert own.action == "escalate"
    assert other_trace.retrieved_chunk_ids == ["adv-chunk-01"]
    assert other.action == "answer" and other.citations == ["adv-chunk-01"]


@pytest.mark.parametrize("task", ["analyst", "responder", "guardian"])
def test_any_llm_error_escalates(settings, content, make_question, task):
    deps = Deps(settings, content, MockLLM(errors={task: "down"}), MockRetriever(content.chunks))
    decision, _ = run_question(make_question(REF), deps)
    assert decision.action == "escalate"
    assert decision.escalation_reason == "llm_error"


def test_retrieval_error_escalates_without_responder(settings, content, make_question):
    class DownRetriever:
        def search(self, query, top_k, lesson_id):
            raise RetrievalError("search down")

    deps = Deps(settings, content, MockLLM(), DownRetriever())
    decision, trace = run_question(make_question(REF), deps)
    assert decision.escalation_reason == "llm_error"
    assert trace.llm_calls == 1  # analyst only
    assert trace.nodes_run == ["analyst", "retrieval", "validator"]


def test_bad_llm_output_escalates(settings, content, make_question):
    deps = Deps(settings, content, MockLLM(bad_output={"responder"}), MockRetriever(content.chunks))
    decision, trace = run_question(make_question(REF), deps)
    assert decision.escalation_reason == "llm_error"
    assert "guardian" not in trace.nodes_run


# ---------- scenarios, eval, trace file ----------


@pytest.mark.parametrize("path", scenario_files(), ids=lambda p: p.name)
def test_scenarios_match_expected(path):
    assert run_scenario(path, trace_path=None)["matches_expected"]


def test_eval_runs_every_question():
    result = run_eval()
    summary = result["summary"]
    assert summary["questions"] == len(result["rows"]) > 0
    assert summary["unsupported_let_through"] == 0


def test_guardian_eval_runs_every_case():
    result = run_guardian_eval()
    assert result["summary"]["cases"] == len(result["rows"]) > 0
    assert result["summary"]["errors"] == []
    assert all(r["verdict"] in {"pass", "fail"} for r in result["rows"])


def test_write_trace_appends_jsonl(tmp_path, deps, make_question):
    path = tmp_path / "traces.jsonl"
    for _ in range(2):
        _, trace = run_question(make_question(REF), deps)
        write_trace(trace, path)
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["backend"] == "mock"
