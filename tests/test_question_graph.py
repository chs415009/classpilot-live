import time

import pytest

from classpilot.adapters.llm import MockLLM
from classpilot.adapters.retrieval import MockRetriever, RetrievalError
from classpilot.contracts.trace import LLMCallRecord, NodeRecord
from classpilot.live.question_graph import (
    MIN_GUARDIAN_SECONDS,
    Deps,
    guardian_timeout,
    run_question,
)
from classpilot.runner import run_eval, run_guardian_eval, run_scenario, scenario_files

KAFKA = "How does the Bronze layer handle streaming data from Kafka?"
REF = "What does ref() do in a dbt model?"
ALL_NODES = ["retrieval", "analyst", "responder", "guardian", "validator"]


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


def test_out_of_scope_question_stops_at_the_analyst(deps, make_question):
    question = make_question("What time is the midterm exam next week?")
    out = run_question(question, deps)
    assert out.decision.escalation_reason == "out_of_scope"
    assert out.llm_calls == 1
    # Stage 12: retrieval runs first so the Analyst sees the lesson material.
    assert out.nodes_run == ["retrieval", "analyst", "validator"]
    assert out.retrieved_chunk_ids


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
    assert out.nodes_run == ["retrieval", "analyst", "responder", "validator"]


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
    assert out.llm_calls == 0  # retrieval runs first; nothing after it
    assert out.nodes_run == ["retrieval", "validator"]
    statuses = {n.node_name: n.status for n in out.of_type(NodeRecord)}
    assert statuses["retrieval"] == "fail" and statuses["analyst"] == "skip"
    assert out.run.deciding_node == "retrieval"


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


# ---------- Stage 12: Guardian timeout and the per-question deadline ----------


def test_guardian_timeout_is_capped_by_the_deadline():
    now = time.perf_counter()
    assert guardian_timeout(15, 30, now) == pytest.approx(15, abs=0.1)
    assert guardian_timeout(15, 30, now - 22) == pytest.approx(8, abs=0.1)
    assert guardian_timeout(15, 30, now - 40) == MIN_GUARDIAN_SECONDS


def test_slow_guardian_escalates_within_its_own_timeout(content, make_question):
    from classpilot.settings import load_settings

    settings = load_settings(
        overrides={
            "llm": {"compiled_program": None, "timeout_seconds": 5},
            "question": {"guardian_timeout_seconds": 0.3, "deadline_seconds": 30},
        }
    )
    deps = Deps(settings, content, MockLLM(delays={"guardian": 1.5}), MockRetriever(content.chunks))
    start = time.perf_counter()
    out = run_question(make_question(REF), deps)
    assert out.decision.escalation_reason == "llm_error"
    assert out.run.deciding_node == "guardian"
    assert time.perf_counter() - start < 1.4  # did not wait for the slow Guardian


def test_guardian_gets_only_what_is_left_of_the_deadline(content, make_question):
    from classpilot.settings import load_settings

    settings = load_settings(
        overrides={
            "llm": {"compiled_program": None, "timeout_seconds": 5},
            "question": {"guardian_timeout_seconds": 15, "deadline_seconds": 1.5},
        }
    )
    llm = MockLLM(delays={"responder": 0.4, "guardian": 3})
    deps = Deps(settings, content, llm, MockRetriever(content.chunks))
    start = time.perf_counter()
    out = run_question(make_question(REF), deps)
    assert out.decision.escalation_reason == "llm_error"
    assert out.run.deciding_node == "guardian"
    assert time.perf_counter() - start < 2.0  # about the 1.5 s deadline, not 3 s


# ---------- Stage 12: one repeat after a malformed reply ----------


def test_malformed_guardian_reply_is_asked_again(settings, content, make_question):
    deps = Deps(
        settings, content, MockLLM(malformed={"guardian": 1}), MockRetriever(content.chunks)
    )
    out = run_question(make_question(REF), deps)
    assert out.decision.action == "answer"
    assert out.llm_calls == 4  # analyst, responder, guardian twice
    calls = {c.node_name: c for c in out.of_type(LLMCallRecord)}
    assert (calls["guardian"].retry_count, calls["guardian"].error_count) == (1, 1)
    nodes = {n.node_name: n for n in out.of_type(NodeRecord)}
    assert nodes["guardian"].llm_call_count == 2


def test_second_malformed_reply_escalates(settings, content, make_question):
    deps = Deps(settings, content, MockLLM(malformed={"analyst": 2}), MockRetriever(content.chunks))
    out = run_question(make_question(REF), deps)
    assert out.decision.escalation_reason == "llm_error"
    assert out.run.deciding_node == "analyst" and out.llm_calls == 2


def test_no_repeat_when_too_little_of_the_deadline_is_left(content, make_question):
    from classpilot.settings import load_settings

    settings = load_settings(
        overrides={
            "llm": {"compiled_program": None},
            "question": {"deadline_seconds": 30, "min_retry_seconds": 60},
        }
    )
    deps = Deps(
        settings, content, MockLLM(malformed={"guardian": 1}), MockRetriever(content.chunks)
    )
    out = run_question(make_question(REF), deps)
    assert out.decision.escalation_reason == "llm_error"
    assert out.llm_calls == 3


def test_call_node_never_repeats_a_timeout():
    from classpilot.nodes import RetryPolicy, call_node

    policy = RetryPolicy(max_retries=1, min_seconds=0, seconds_left=lambda: 30)
    result = call_node(MockLLM(delays={"analyst": 0.5}), "analyst", {}, 0.1, policy)
    assert result.error and "timed out" in result.error and result.retries == 0
