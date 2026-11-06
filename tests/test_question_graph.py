import pytest

from classpilot.adapters.llm import MockLLM
from classpilot.adapters.retrieval import MockRetriever, RetrievalError
from classpilot.live.question_graph import Deps, run_question
from classpilot.runner import run_eval, run_guardian_eval, run_scenario, scenario_files

KAFKA = "How does the Bronze layer handle streaming data from Kafka?"
REF = "What does ref() do in a dbt model?"
ALL_NODES = ["analyst", "retrieval", "responder", "guardian", "validator"]


def test_question_answer_has_citations_and_trace(deps, make_question):
    out = run_question(make_question("Why do we keep raw data in Bronze if it has errors?"), deps)
    assert out.decision.action == "answer"
    assert out.decision.citations == ["chunk-01"]
    assert out.decision.escalation_reason is None
    assert out.nodes_run == ALL_NODES
    assert out.llm_calls == 3
    assert "chunk-01" in out.retrieved_chunk_ids
    assert {"analyst", "retrieval", "responder", "guardian", "total"} <= out.latency_ms.keys()


def test_guardian_sees_every_retrieved_chunk_cited_first(settings, content, make_question):
    class Recording(MockLLM):
        def complete(self, task, inputs):
            if task == "guardian":
                self.guardian_inputs = inputs
            return super().complete(task, inputs)

    llm = Recording()
    deps = Deps(settings, content, llm, MockRetriever(content.chunks))
    out = run_question(make_question("Why do we keep raw data in Bronze if it has errors?"), deps)
    shown = [c["chunk_id"] for c in llm.guardian_inputs["cited_chunks"]]
    assert shown[0] == out.decision.citations[0]
    assert sorted(shown) == sorted(out.retrieved_chunk_ids) and len(shown) > 1


def test_assignment_question_stops_at_the_analyst(deps, make_question):
    question = make_question(
        "Can you write the dbt model that deduplicates the orders table for Assignment 1?"
    )
    out = run_question(question, deps)
    assert out.decision.escalation_reason == "assignment_like"
    assert out.llm_calls == 1
    assert out.nodes_run == ["analyst", "validator"]
    assert out.retrieved_chunk_ids == []


def test_details_keep_raw_node_outputs(deps, make_question):
    details: dict = {}
    run_question(make_question(KAFKA), deps, details)
    assert details["analyst"]["category"] == "in_scope"
    assert "answer_text" in details["responder"]
    assert details["guardian"]["verdict"] == "fail"
    assert details["llm_errors"] == []


def test_skips_guardian_when_escalation_is_certain(deps, make_question):
    # Mock responder gives low confidence for an uncovered question.
    out = run_question(
        make_question("How does dbt handle snapshots for slowly changing dimensions?"), deps
    )
    assert out.decision.action == "escalate"
    assert out.nodes_run == ["analyst", "retrieval", "responder", "validator"]


def test_guardian_catches_what_self_check_misses(deps, make_question):
    out = run_question(make_question(KAFKA), deps)
    assert out.decision.escalation_reason == "unsupported"
    assert "guardian" in out.nodes_run


def test_retrieval_is_filtered_by_lesson(deps, make_question):
    text = "What do dbt snapshots record over time?"
    own = run_question(make_question(text), deps)
    other = run_question(make_question(text, lesson_id="lesson-dbt-advanced"), deps)
    assert "adv-chunk-01" not in own.retrieved_chunk_ids
    assert own.decision.action == "escalate"
    assert other.retrieved_chunk_ids == ["adv-chunk-01"]
    assert other.decision.action == "answer" and other.decision.citations == ["adv-chunk-01"]


@pytest.mark.parametrize("task", ["analyst", "responder", "guardian"])
def test_any_llm_error_escalates(settings, content, make_question, task):
    deps = Deps(settings, content, MockLLM(errors={task: "down"}), MockRetriever(content.chunks))
    out = run_question(make_question(REF), deps)
    assert out.decision.action == "escalate"
    assert out.decision.escalation_reason == "llm_error"


def test_retrieval_error_escalates_without_responder(settings, content, make_question):
    class DownRetriever:
        def search(self, query, top_k, lesson_id):
            raise RetrievalError("search down")

    deps = Deps(settings, content, MockLLM(), DownRetriever())
    out = run_question(make_question(REF), deps)
    assert out.decision.escalation_reason == "llm_error"
    assert out.llm_calls == 1  # analyst only
    assert out.nodes_run == ["analyst", "retrieval", "validator"]


def test_bad_llm_output_escalates(settings, content, make_question):
    deps = Deps(settings, content, MockLLM(bad_output={"responder"}), MockRetriever(content.chunks))
    out = run_question(make_question(REF), deps)
    assert out.decision.escalation_reason == "llm_error"
    assert "guardian" not in out.nodes_run


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
