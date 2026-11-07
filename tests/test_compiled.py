"""Compiled programs: saving, loading behind `llm.compiled_program`, and the program id
as `prompt_version` in the trace. Uses the committed fixture; no network."""

import json
from pathlib import Path

import dspy
import pytest
from test_agents import GOOD, FakeEngine

from classpilot.adapters.llm import MockLLM, call_llm
from classpilot.adapters.retrieval import MockRetriever
from classpilot.agents.compiled import (
    CompiledProgramError,
    apply_program,
    live_agents,
    load_program,
    save_program,
)
from classpilot.agents.program import DSPyAgents
from classpilot.agents.signatures import SIGNATURES
from classpilot.content import load_content
from classpilot.contracts import StudentQuestion
from classpilot.contracts.trace import PROMPT_VERSION
from classpilot.live.question_graph import Deps, run_question
from classpilot.settings import Settings, load_settings

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "compiled"
FIXTURE_ID = "fixture-compiled-v1"
OLD_FIXTURE_ID = "fixture-compiled-v0"  # Analyst without the Stage 12 `chunks` field


def lm(engine):
    return dspy.LM("fake-model", engine=engine, cache=False, num_retries=0)


def test_fixture_loads_and_sets_the_prompt_version():
    settings = load_settings(overrides={"llm": {"compiled_program": FIXTURE_ID}})
    agents = live_agents(settings, lm(FakeEngine()), FIXTURE_DIR)
    assert agents.prompt_version == FIXTURE_ID
    assert len(agents.modules["analyst"].demos) == 1
    assert agents.modules["guardian"].demos == []  # not in the file: uncompiled


def test_program_with_an_old_field_list_is_refused():
    settings = load_settings(overrides={"llm": {"compiled_program": OLD_FIXTURE_ID}})
    with pytest.raises(CompiledProgramError, match="recompile"):
        live_agents(settings, lm(FakeEngine()), FIXTURE_DIR)


def test_uncompiled_by_default():
    # Code defaults (config/settings.yaml may name a program).
    agents = live_agents(Settings(), lm(FakeEngine()), FIXTURE_DIR)
    assert agents.prompt_version == PROMPT_VERSION == "uncompiled-v4"
    assert all(m.demos == [] for m in agents.modules.values())


def test_demos_reach_the_prompt():
    inputs, reply = GOOD["analyst"]
    engine = FakeEngine(reply)
    agents = apply_program(DSPyAgents(lm(engine)), load_program(FIXTURE_ID, FIXTURE_DIR))
    out = call_llm(agents, "analyst", inputs, timeout_s=5)
    assert out["category"] == "in_scope"
    text = "".join(m.text for m in engine.requests[0].messages)
    assert "Why is a stack called LIFO?" in text


def test_compiled_id_is_the_prompt_version_in_the_trace():
    class Compiled(MockLLM):
        prompt_version = FIXTURE_ID

    content = load_content()
    deps = Deps(load_settings(), content, Compiled(), MockRetriever(content.chunks))
    question = StudentQuestion(
        session_id="s",
        event_id="e-1",
        lesson_id=content.lesson_id,
        anonymous_learner_id="l",
        objective_id="seg-02",
        question_text="Why do we keep raw data in Bronze if it has errors?",
        submitted_at="2026-10-22T00:00:00Z",
    )
    calls = [r for r in run_question(question, deps).records if r.record_type == "llm_call"]
    assert calls and all(c.prompt_version == FIXTURE_ID for c in calls)


def test_save_round_trip_drops_the_lm(tmp_path):
    module = dspy.Predict(SIGNATURES["guardian"][0])
    module.lm = lm(FakeEngine())
    path = save_program("p-1", {"guardian": module}, {"trainset": []}, tmp_path)
    data = json.loads(path.read_text())
    assert data["modules"]["guardian"]["lm"] is None and data["program_id"] == "p-1"
    assert load_program("p-1", tmp_path)["modules"].keys() == {"guardian"}


@pytest.mark.parametrize("program_id", ["missing", "../x", ""])
def test_bad_ids_and_missing_files_fail(program_id):
    with pytest.raises(CompiledProgramError):
        load_program(program_id, FIXTURE_DIR)


def test_mismatched_id_or_lm_state_fails(tmp_path):
    data = json.loads((FIXTURE_DIR / f"{FIXTURE_ID}.json").read_text())
    (tmp_path / "other.json").write_text(json.dumps(data))
    with pytest.raises(CompiledProgramError, match="holds program"):
        load_program("other", tmp_path)
    data["modules"]["analyst"]["lm"] = {"model": "x"}
    (tmp_path / f"{FIXTURE_ID}.json").write_text(json.dumps(data))
    with pytest.raises(CompiledProgramError, match="LM"):
        load_program(FIXTURE_ID, tmp_path)


def test_guardian_can_run_on_its_own_lm():
    main, guard = FakeEngine(GOOD["analyst"][1]), FakeEngine(GOOD["guardian"][1])
    agents = live_agents(Settings(), lm(main), FIXTURE_DIR, guardian_lm=lm(guard))
    call_llm(agents, "guardian", GOOD["guardian"][0], timeout_s=5)
    call_llm(agents, "analyst", GOOD["analyst"][0], timeout_s=5)
    assert len(guard.requests) == 1 and len(main.requests) == 1
