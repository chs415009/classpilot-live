"""Contract test for the trace v2 records and the decision log (draft, Q-21)."""

import json

import pytest

from classpilot.adapters.llm import MockLLM
from classpilot.adapters.retrieval import MockRetriever
from classpilot.contracts.trace import (
    PROMPT_VERSION,
    RECORD_MODELS,
    ClaimRecord,
    DecisionLogEntry,
    NodeRecord,
    RunRecord,
)
from classpilot.live.poll import run_poll
from classpilot.live.question_graph import Deps, run_question
from classpilot.trace import write_run

# Fields removed from the data model by agreement (IMPLEMENTATION_NOTES 6.3), plus v1 leftovers.
REMOVED = [
    "scenario_key",
    "assignment_key",
    "max_reteach",
    "matches_expected",
    "support_score",
    "is_approved",
    "token",
    "agent_mode",
    "remediations_used",
]
EXPLAIN_COUNTS = {"A": 3, "B": 13, "C": 4, "D": 1}
REF = "What does ref() do in a dbt model?"
KAFKA = "How does the Bronze layer handle streaming data from Kafka?"


def write_and_read(output, tmp_path):
    trace_path, log_path = tmp_path / "traces.jsonl", tmp_path / "decision_log.jsonl"
    write_run(output, trace_path, log_path)
    lines = [json.loads(line) for line in trace_path.read_text().splitlines()]
    logs = [json.loads(line) for line in log_path.read_text().splitlines()]
    return lines, logs


def assert_valid_records(lines, run_id):
    for line in lines:
        model = RECORD_MODELS[line["record_type"]]
        model.model_validate(line)  # extra="forbid": no unplanned field
        assert line["run_id"] == run_id
        assert line["schema_version"] == "v2-draft"
        for key in line:
            assert not any(removed in key for removed in REMOVED), key


def test_poll_run_writes_run_node_and_poll_evidence_records(content, make_evidence, tmp_path):
    output = run_poll(make_evidence(EXPLAIN_COUNTS), content.manifest, "mock")
    lines, logs = write_and_read(output, tmp_path)
    assert_valid_records(lines, output.decision.decision_id)

    types = [line["record_type"] for line in lines]
    assert set(types) == {"run", "node", "poll_evidence"}
    assert types.count("run") == 1
    run = RunRecord.model_validate(lines[0])
    assert (run.path, run.final_action, run.deciding_node) == ("poll", "explain", "decide_poll")
    assert (run.segment_id, run.misconception_id, run.remediation_id) == ("seg-02", "M-01", "R-01")
    nodes = [NodeRecord.model_validate(x) for x in lines if x["record_type"] == "node"]
    assert [(n.node_seq, n.node_name, n.status) for n in nodes] == [
        (1, "threshold_check", "pass"),
        (2, "decide_poll", "pass"),
        (3, "explanation_lookup", "pass"),
    ]
    evidence = {x["option"]: x for x in lines if x["record_type"] == "poll_evidence"}
    assert {o: x["response_count"] for o, x in evidence.items()} == EXPLAIN_COUNTS
    assert [o for o, x in evidence.items() if x["is_correct"]] == ["A"]

    entry = DecisionLogEntry.model_validate(logs[0])
    assert entry.decision.remediation_text and entry.decision.show_slide == "dbt-medallion-p03"
    assert entry.poll_evidence.poll_id == "q-01" and entry.question is None


def test_reveal_marks_explanation_lookup_as_skipped(content, make_evidence):
    output = run_poll(make_evidence({"A": 8, "B": 9, "C": 3, "D": 1}), content.manifest, "mock")
    statuses = {n.node_name: n.status for n in output.of_type(NodeRecord)}
    assert statuses["explanation_lookup"] == "skip"
    assert output.run.remediation_id is None


def test_question_run_writes_every_question_record_type(deps, make_question, tmp_path):
    output = run_question(make_question(REF), deps)
    lines, logs = write_and_read(output, tmp_path)
    assert_valid_records(lines, output.decision.decision_id)

    types = [line["record_type"] for line in lines]
    assert set(types) == {"run", "node", "llm_call", "retrieval", "claim"}
    assert types.count("run") == 1
    assert types.count("node") == 5
    calls = [x for x in lines if x["record_type"] == "llm_call"]
    assert [c["node_name"] for c in calls] == ["analyst", "responder", "guardian"]
    assert all(c["prompt_version"] == PROMPT_VERSION == "uncompiled-v1" for c in calls)
    assert all(c["model"] == "mock" and c["retry_count"] == 0 for c in calls)
    retrieval = [x for x in lines if x["record_type"] == "retrieval"]
    assert [r["rank"] for r in retrieval] == list(range(1, len(retrieval) + 1))
    assert {r["chunk_id"] for r in retrieval if r["cited"]} == set(output.decision.citations)
    assert len({r["query_hash"] for r in retrieval}) == 1
    assert REF not in json.dumps(lines)  # the trace holds hashes, not the question text

    run = RunRecord.model_validate(lines[0])
    assert (run.final_action, run.deciding_node, run.segment_id) == (
        "answer",
        "validator",
        "seg-03",
    )
    entry = DecisionLogEntry.model_validate(logs[0])
    assert entry.question.question_text == REF
    assert entry.decision.answer_text and entry.lesson_id == "lesson-dbt-medallion"


def test_unsupported_claim_is_recorded(deps, make_question):
    output = run_question(make_question(KAFKA), deps)
    claims = output.of_type(ClaimRecord)
    assert any(not c.supported and c.supporting_chunk_id is None for c in claims)
    assert output.run.deciding_node == "guardian"
    statuses = {n.node_name: n.status for n in output.of_type(NodeRecord)}
    assert statuses["guardian"] == "block"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "What time is the midterm exam next week?",
            {"analyst": "block", "retrieval": "skip", "responder": "skip", "guardian": "skip"},
        ),
        (
            "How does dbt handle snapshots for slowly changing dimensions?",
            {"analyst": "pass", "retrieval": "pass", "responder": "block", "guardian": "skip"},
        ),
    ],
)
def test_node_status_on_escalation(deps, make_question, text, expected):
    output = run_question(make_question(text), deps)
    statuses = {n.node_name: n.status for n in output.of_type(NodeRecord)}
    assert {k: statuses[k] for k in expected} == expected
    assert statuses["validator"] == "pass"
    assert output.run.deciding_node == next(k for k, v in expected.items() if v == "block")
    assert output.llm_calls == sum(n.llm_call_count for n in output.of_type(NodeRecord))


def test_llm_error_is_a_failed_node_and_call(settings, content, make_question):
    deps = Deps(
        settings, content, MockLLM(errors={"responder": "down"}), MockRetriever(content.chunks)
    )
    output = run_question(make_question(REF), deps)
    statuses = {n.node_name: n.status for n in output.of_type(NodeRecord)}
    assert statuses["responder"] == "fail"
    assert output.run.deciding_node == "responder"
    assert output.run.escalation_reason == "llm_error"
    calls = {c.node_name: c.error_count for c in output.records if c.record_type == "llm_call"}
    assert calls == {"analyst": 0, "responder": 1}


def test_write_run_appends(tmp_path, deps, make_question):
    trace_path, log_path = tmp_path / "t.jsonl", tmp_path / "d.jsonl"
    outputs = [run_question(make_question(REF), deps) for _ in range(2)]
    for output in outputs:
        write_run(output, trace_path, log_path)
    assert len(trace_path.read_text().splitlines()) == sum(len(o.records) for o in outputs)
    assert len(log_path.read_text().splitlines()) == 2
