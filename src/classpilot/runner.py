"""Run scenario files and the labeled eval set. Shared by the CLI and the report."""

import json
import statistics
from pathlib import Path

from classpilot import rules
from classpilot.adapters import make_adapters
from classpilot.adapters.llm import MockLLM
from classpilot.content import Content, load_content
from classpilot.contracts import PollEvidence, StudentQuestion
from classpilot.graph import Deps, run_question
from classpilot.live.poll import run_poll
from classpilot.nodes.guardian import run_guardian
from classpilot.settings import PROJECT_ROOT, Settings, load_settings
from classpilot.trace import DEFAULT_TRACE_PATH, write_trace

SCENARIO_DIR = PROJECT_ROOT / "scenarios"
EVAL_PATH = PROJECT_ROOT / "eval" / "test_questions.json"
GUARDIAN_CASES_PATH = PROJECT_ROOT / "eval" / "guardian_cases.json"
OUTPUT_DIR = PROJECT_ROOT / "outputs"


def make_deps(settings: Settings, content: Content, mock_overrides: dict | None = None) -> Deps:
    llm, retriever = make_adapters(settings, content)
    if settings.backend == "mock" and mock_overrides:
        llm = MockLLM(
            delays=mock_overrides.get("delays"),
            errors=mock_overrides.get("errors"),
            bad_output=set(mock_overrides.get("bad_output", [])),
        )
    return Deps(settings, content, llm, retriever)


def run_scenario(
    path: Path, agent_mode: int | None = None, trace_path: Path | None = DEFAULT_TRACE_PATH
) -> dict:
    scenario = json.loads(Path(path).read_text())
    settings = load_settings(overrides=scenario.get("settings_overrides"))
    content = load_content()
    deps = make_deps(settings, content, scenario.get("mock_overrides"))

    if scenario["path"] == "poll":
        evidence = PollEvidence.model_validate(scenario["input"])
        decision, trace = run_poll(evidence, content.manifest, settings.backend)
    else:
        question = StudentQuestion.model_validate(scenario["input"])
        decision, trace = run_question(question, deps, agent_mode)

    if trace_path is not None:
        write_trace(trace, trace_path)

    expected = scenario.get("expected", {})
    actual = decision.model_dump()
    matches = all(actual.get(key) == value for key, value in expected.items())
    return {
        "file": Path(path).name,
        "name": scenario["name"],
        "description": scenario.get("description", ""),
        "input": scenario["input"],
        "expected": expected,
        "matches_expected": matches,
        "decision": actual,
        "trace": trace.model_dump(),
    }


def scenario_files() -> list[Path]:
    return sorted(SCENARIO_DIR.glob("*.json"))


def run_eval(agent_mode: int, trace_path: Path | None = None) -> dict:
    settings = load_settings(overrides={"agent_mode": agent_mode})
    deps = make_deps(settings, load_content())
    questions = json.loads(EVAL_PATH.read_text())
    if trace_path is not None and trace_path.exists():
        trace_path.unlink()

    rows = []
    for item in questions:
        question = StudentQuestion(
            session_id="eval-session",
            event_id=item["id"],
            anonymous_learner_id="eval-learner",
            objective_id=item.get("objective_id"),
            question_text=item["question_text"],
            submitted_at="2026-10-22T00:00:00Z",
        )
        details: dict = {}
        decision, trace = run_question(question, deps, agent_mode, details)
        if trace_path is not None:
            write_trace(trace, trace_path)
        rows.append(
            {
                "id": item["id"],
                "question_text": item["question_text"],
                "expected_action": item["expected_action"],
                "expected_reason": item.get("expected_reason"),
                "action": decision.action,
                "escalation_reason": decision.escalation_reason,
                "confidence": decision.confidence,
                "citations": decision.citations,
                "answer_text": decision.answer_text,
                "llm_calls": trace.llm_calls,
                "latency_ms": trace.latency_ms,
                "nodes_run": trace.nodes_run,
                "details": details,
            }
        )
    return {
        "agent_mode": agent_mode,
        "backend": settings.backend,
        "summary": summarize(rows),
        "rows": rows,
    }


def run_guardian_eval() -> dict:
    """Send hand-written answers straight to the Guardian, so its catch rate does not
    depend on the responder happening to make a mistake."""
    settings = load_settings()
    content = load_content()
    deps = make_deps(settings, content)
    chunks = {c["chunk_id"]: c for c in content.chunks}
    cases = json.loads(GUARDIAN_CASES_PATH.read_text())

    rows = []
    for case in cases:
        cited = [chunks[i] for i in case["cited_chunk_ids"]]
        result = run_guardian(
            case["question_text"],
            case["answer_text"],
            cited,
            deps.llm,
            settings.llm.timeout_seconds,
        )
        check = rules.check_guardian(result.raw, case["cited_chunk_ids"])
        verdict = {True: "pass", False: "fail", None: "error"}[check.passed]
        rows.append(
            {
                "id": case["id"],
                "expected": case["expected"],
                "verdict": verdict if result.error is None else "error",
                "reason": check.reason if result.error is None else result.error,
                "note": case.get("note", ""),
                "latency_ms": result.latency_ms,
                "raw": result.raw,
            }
        )

    should_fail = [r for r in rows if r["expected"] == "fail"]
    should_pass = [r for r in rows if r["expected"] == "pass"]
    summary = {
        "cases": len(rows),
        "caught": sum(r["verdict"] == "fail" for r in should_fail),
        "should_fail": len(should_fail),
        # Errors are listed on their own: in the graph they escalate as llm_error (fail-closed).
        "missed": [r["id"] for r in should_fail if r["verdict"] == "pass"],
        "false_fails": [r["id"] for r in should_pass if r["verdict"] == "fail"],
        "errors": [r["id"] for r in rows if r["verdict"] == "error"],
        "latency_ms_avg": round(statistics.mean(r["latency_ms"] for r in rows), 1),
    }
    return {"backend": settings.backend, "summary": summary, "rows": rows}


def summarize(rows: list[dict]) -> dict:
    should_escalate = [r for r in rows if r["expected_action"] == "escalate"]
    should_answer = [r for r in rows if r["expected_action"] == "answer"]
    escalated_ok = [r for r in should_escalate if r["action"] == "escalate"]
    totals = [r["latency_ms"]["total"] for r in rows]
    return {
        "questions": len(rows),
        "correct_action": sum(r["action"] == r["expected_action"] for r in rows),
        "should_escalate": len(should_escalate),
        "escalated": len(escalated_ok),
        "escalation_recall": round(len(escalated_ok) / len(should_escalate), 2)
        if should_escalate
        else None,
        "unsupported_let_through": sum(r["action"] == "answer" for r in should_escalate),
        "false_escalations": sum(r["action"] == "escalate" for r in should_answer),
        "llm_calls_total": sum(r["llm_calls"] for r in rows),
        "llm_calls_avg": round(sum(r["llm_calls"] for r in rows) / len(rows), 2),
        "latency_ms_avg": round(statistics.mean(totals), 1),
        "latency_ms_max": max(totals),
    }
