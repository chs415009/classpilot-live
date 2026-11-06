"""Compiling the prep writers (fake engine and the prep mock; no network), and the guard
that committed compiled programs hold only synthetic content."""

import json

import dspy
import pytest
from test_agents import FakeEngine, chat_reply

from classpilot.adapters.mock_prep import MockPrepLLM
from classpilot.agents.compiled import (
    COMPILED_DIR,
    CompiledProgramError,
    apply_program,
    load_program,
    prep_agents,
    save_program,
)
from classpilot.agents.prep_signatures import PREP_SIGNATURES
from classpilot.agents.program import DSPyAgents
from classpilot.compiling import compile_writer, load_prep_trainset, writer_check
from classpilot.settings import load_settings


def lm(engine):
    return dspy.LM("fake-model", engine=engine, cache=False, num_retries=0)


ITEMS = load_prep_trainset()
S03 = next(i for i in ITEMS["script_writer"] if i.item_id == "syn-s03")
SUPPORTED = "People waiting at a bus stop board in the order they arrived."


def test_trainset_is_synthetic_and_complete():
    assert len(ITEMS["script_writer"]) == 7 and len(ITEMS["explanation_writer"]) == 6
    for items in ITEMS.values():
        for item in items:
            assert all(c["chunk_id"].startswith("syn-") for c in item.chunks)
            assert any(c["slide_id"] for c in item.chunks)  # at least one slide chunk


def test_writer_check_runs_structure_guardian_and_rule():
    good = {"script": SUPPORTED, "citations": ["syn-p01-c1"]}
    assert writer_check(S03, good, MockPrepLLM(), 5) == []
    invented = {"script": f"{SUPPORTED} Buses always run on time.", "citations": ["syn-p01-c1"]}
    assert writer_check(S03, invented, MockPrepLLM(), 5)
    code = {"script": f"`{SUPPORTED}`", "citations": ["syn-p01-c1"]}
    assert "read aloud" in writer_check(S03, code, MockPrepLLM(), 5)[0]
    bold = {"script": f"**{SUPPORTED}**", "citations": ["syn-p01-c1"]}
    assert writer_check(S03, bold, MockPrepLLM(), 5) == []  # emphasis removed by code


def test_compile_keeps_only_passing_outputs_as_demos():
    reply = chat_reply(script=SUPPORTED, citations=["syn-p01-c1"])
    compiled = compile_writer(
        "script_writer", ITEMS["script_writer"], lm(FakeEngine(reply)), MockPrepLLM(), 5
    )
    assert len(compiled.demos) == 2
    assert compiled.demos[0]["script"] == SUPPORTED


def test_compile_with_no_passing_output_has_no_demos():
    reply = chat_reply(script="Buses always run on time.", citations=["syn-p01-c1"])
    compiled = compile_writer(
        "script_writer", ITEMS["script_writer"][:3], lm(FakeEngine(reply)), MockPrepLLM(), 5
    )
    assert compiled.demos == []


def test_prep_program_loads_behind_prep_compiled_program(tmp_path):
    reply = chat_reply(script=SUPPORTED, citations=["syn-p01-c1"])
    module = compile_writer(
        "script_writer", ITEMS["script_writer"], lm(FakeEngine(reply)), MockPrepLLM(), 5
    )
    save_program("prep-x", {"script_writer": module}, {}, tmp_path)
    settings = load_settings(overrides={"prep": {"compiled_program": "prep-x"}})
    agents = prep_agents(settings, lm(FakeEngine(reply)), tmp_path)
    assert agents.prompt_version == "prep-x"
    assert len(agents.modules["script_writer"].demos) == 2
    assert prep_agents(load_settings(), lm(FakeEngine())).modules["script_writer"].demos == []


def test_a_prep_program_cannot_load_into_the_live_agents(tmp_path):
    module = dspy.Predict(PREP_SIGNATURES["script_writer"][0])
    save_program("prep-y", {"script_writer": module}, {}, tmp_path)
    with pytest.raises(CompiledProgramError, match="other side"):
        apply_program(DSPyAgents(lm(FakeEngine())), load_program("prep-y", tmp_path))


def test_committed_programs_hold_only_synthetic_chunks():
    """compiled/ is public: demos may only cite synthetic chunks (syn-*)."""
    for path in sorted(COMPILED_DIR.glob("*.json")):
        text = json.dumps(json.loads(path.read_text())["modules"])
        for marker in ("l1-", "info6205", "INFO 6205"):
            assert marker not in text, f"{path.name} holds course content ({marker})"
