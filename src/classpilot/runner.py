"""Run scenario files, the labeled eval set, and the Guardian eval. Used by the CLI."""

import json
import statistics
from pathlib import Path

from classpilot.adapters import make_adapters
from classpilot.adapters.llm import MockLLM
from classpilot.adapters.retrieval import MockRetriever
from classpilot.content import Content, load_content
from classpilot.contracts import PollEvidence, StudentQuestion
from classpilot.contracts.trace import PROMPT_VERSION
from classpilot.eval_sets import QuestionSet, load_question_set
from classpilot.guardian_cases import V1_CASES_PATH, load_cases, run_case_eval
from classpilot.live.poll import run_poll
from classpilot.live.question_graph import Deps, run_question
from classpilot.settings import PROJECT_ROOT, Settings, load_settings
from classpilot.trace import DEFAULT_DECISION_LOG_PATH, DEFAULT_TRACE_PATH, write_run

SCENARIO_DIR = PROJECT_ROOT / "scenarios"
EVAL_PATH = PROJECT_ROOT / "eval" / "test_questions.json"
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
    path: Path,
    trace_path: Path | None = DEFAULT_TRACE_PATH,
    log_path: Path = DEFAULT_DECISION_LOG_PATH,
) -> dict:
    """Run one scenario file. `trace_path=None` writes neither traces nor the decision log."""
    scenario = json.loads(Path(path).read_text())
    settings = load_settings(overrides=scenario.get("settings_overrides"))
    content = load_content()
    deps = make_deps(settings, content, scenario.get("mock_overrides"))

    if scenario["path"] == "poll":
        evidence = PollEvidence.model_validate(scenario["input"])
        output = run_poll(evidence, content.manifest, settings.backend)
    else:
        question = StudentQuestion.model_validate(scenario["input"])
        output = run_question(question, deps)

    if trace_path is not None:
        write_run(output, trace_path, log_path)

    expected = scenario.get("expected", {})
    actual = output.decision.model_dump()
    matches = all(actual.get(key) == value for key, value in expected.items())
    excluded = set(scenario.get("expected_retrieved_excludes", []))
    matches = matches and not excluded & set(output.retrieved_chunk_ids)
    return {
        "file": Path(path).name,
        "name": scenario["name"],
        "description": scenario.get("description", ""),
        "input": scenario["input"],
        "expected": expected,
        "matches_expected": matches,
        "decision": actual,
        "trace": output.summary(),
        "records": [r.model_dump() for r in output.records],
        "decision_log": output.log.model_dump(),
    }


def scenario_files() -> list[Path]:
    return sorted(SCENARIO_DIR.glob("*.json"))


def set_deps(settings: Settings, qset: QuestionSet) -> Deps:
    """Deps for a question set: the backend's LLM; retrieval per the set's `retrieval`."""
    llm, _ = make_adapters(settings, qset.content)
    if qset.retrieval == "search" and settings.backend == "cortex":
        from classpilot.adapters.retrieval import CortexSearchRetriever

        retriever = CortexSearchRetriever(settings, service_name=settings.objects.search_service)
    else:
        retriever = MockRetriever(qset.content.chunks)
    return Deps(settings, qset.content, llm, retriever)


def run_eval(
    trace_path: Path | None = None,
    log_path: Path | None = None,
    set_path: Path | None = None,
    overrides: dict | None = None,
) -> dict:
    """Run a labeled question set; without `set_path`, the v1 set on the fixture lesson."""
    settings = load_settings(overrides=overrides)
    if set_path is None:
        content = load_content()
        deps = make_deps(settings, content)
        questions = json.loads(EVAL_PATH.read_text())
        set_id, split = "v1-fixture", None
    else:
        qset = load_question_set(set_path)
        content, deps = qset.content, set_deps(settings, qset)
        questions = [q.model_dump() for q in qset.questions]
        set_id, split = qset.set_id, qset.split
    for out in (trace_path, log_path):
        if out is not None and out.exists():
            out.unlink()

    rows = []
    for item in questions:
        question = StudentQuestion(
            session_id="eval-session",
            event_id=item["id"],
            lesson_id=content.lesson_id,
            anonymous_learner_id="eval-learner",
            objective_id=item.get("objective_id"),
            question_text=item["question_text"],
            submitted_at="2026-10-22T00:00:00Z",
        )
        details: dict = {}
        output = run_question(question, deps, details)
        decision = output.decision
        if trace_path is not None and log_path is not None:
            write_run(output, trace_path, log_path)
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
                "llm_calls": output.llm_calls,
                "latency_ms": output.latency_ms,
                "nodes_run": output.nodes_run,
                "details": details,
            }
        )
    return {
        "backend": settings.backend,
        "set_id": set_id,
        "split": split,
        "prompt_version": getattr(deps.llm, "prompt_version", PROMPT_VERSION),
        "summary": summarize(rows),
        "rows": rows,
    }


def run_guardian_eval(cases_path: Path | None = None, overrides: dict | None = None) -> dict:
    """Send labeled answers and prep items straight to the Guardian, so its catch rate
    does not depend on a generator happening to make a mistake. Default: the v1 cases."""
    settings = load_settings(overrides=overrides)
    return run_case_eval(load_cases(cases_path or V1_CASES_PATH), settings)


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
