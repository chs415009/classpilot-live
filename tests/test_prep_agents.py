"""Prep generators and prep Guardian as DSPy modules (fake engine) and the prep mock."""

import dspy
import pytest
from dspy import lm15
from test_agents import FakeEngine, chat_reply

from classpilot.adapters.llm import LLMError, MalformedReplyError, call_llm
from classpilot.adapters.mock_prep import MockPrepLLM, ScriptedPrepLLM
from classpilot.agents.prep_program import DSPyPrepAgents, prep_signature_inputs
from classpilot.agents.prep_signatures import GENERATORS, PREP_SIGNATURES
from classpilot.contracts.prep import PollOutput
from classpilot.rules.prep import (
    check_prep_guardian,
    explanation_problems,
    poll_problems,
    script_problems,
    segmenter_problems,
)

CHUNK_A = {
    "chunk_id": "d-p02-c1",
    "slide_id": "d-p02",
    "text": "Three Layers\nBronze keeps raw data exactly as it arrived\nSilver holds clean rows",
}
CHUNK_REF = {"chunk_id": "ref-p01-c1", "slide_id": None, "text": "Raw data is kept for replay."}
OPTIONS = {"A": "Raw data", "B": "Clean data", "C": "Aggregates", "D": "Nothing"}
MISCONCEPTIONS = [{"option": o, "label": f"L{o}", "description": f"D{o}"} for o in ("B", "C", "D")]
CLAIMS = [{"claim": "Bronze keeps raw data.", "chunk_id": "d-p02-c1"}]

INPUTS = {
    "segmenter": {"slides": [{"slide_id": "d-p02", "chunks": [CHUNK_A]}], "feedback": ""},
    "script_writer": {
        "objective": "Explain the layers",
        "slide_id": "d-p02",
        "position": "slide 2 of 6; first slide of seg-01",
        "chunks": [CHUNK_A, CHUNK_REF],
        "feedback": "Not supported by the cited chunks: 'Gold is free'",
    },
    "poll_placer": {
        "segments": [
            {"segment_id": "seg-01", "objective": "Explain", "slides": ["d-p01", "d-p02"]}
        ],
        "poll_count": 5,
        "feedback": "",
    },
    "poll_writer": {"objective": "Explain the layers", "chunks": [CHUNK_A], "feedback": ""},
    "explanation_writer": {
        "question": "What does Bronze keep?",
        "options": OPTIONS,
        "correct_option": "A",
        "wrong_option": "B",
        "misconception": {"label": "LB", "description": "DB"},
        "chunks": [CHUNK_A],
        "feedback": "",
    },
    "script_guardian": {"script": "Bronze keeps raw data.", "cited_chunks": [CHUNK_A]},
    "poll_guardian": {
        "question": "What does Bronze keep?",
        "options": OPTIONS,
        "correct_option": "A",
        "cited_chunks": [CHUNK_A],
    },
    "explanation_guardian": {
        "question": "What does Bronze keep?",
        "options": OPTIONS,
        "wrong_option": "B",
        "explanation": "Bronze keeps raw data.",
        "cited_chunks": [CHUNK_A],
    },
}
REPLIES = {
    "segmenter": chat_reply(segments=[{"slides": ["d-p02"], "objective": "Explain the layers"}]),
    "script_writer": chat_reply(script="Bronze keeps raw data.", citations=["d-p02-c1"]),
    "poll_placer": chat_reply(segment_ids=["seg-01"], reason="Only segment."),
    "poll_writer": chat_reply(
        question="What does Bronze keep?",
        options=OPTIONS,
        correct_option="A",
        misconceptions=MISCONCEPTIONS,
        citations=["d-p02-c1"],
    ),
    "explanation_writer": chat_reply(
        title="Bronze is raw",
        text="Bronze keeps raw data.",
        show_slide="d-p02",
        citations=["d-p02-c1"],
    ),
    "script_guardian": chat_reply(claims=CLAIMS, verdict="pass", reason="ok"),
    "poll_guardian": chat_reply(
        claims=CLAIMS,
        wrong_options=[{"option": o, "chunk_id": "d-p02-c1"} for o in ("B", "C", "D")],
        verdict="pass",
        reason="ok",
    ),
    "explanation_guardian": chat_reply(
        claims=[{"claim": "Bronze keeps raw data.", "chunk_id": "None"}],
        verdict="fail",
        reason="no",
    ),
}


def agents(engine):
    return DSPyPrepAgents(dspy.LM("fake-model", engine=engine, cache=False, num_retries=0))


# ---------- signatures ----------


@pytest.mark.parametrize("task", list(PREP_SIGNATURES))
def test_signature_output_fields_match_pydantic_model(task):
    signature, model = PREP_SIGNATURES[task]
    sig_fields = {name: f.annotation for name, f in signature.output_fields.items()}
    assert sig_fields == {name: f.annotation for name, f in model.model_fields.items()}


@pytest.mark.parametrize("task", GENERATORS)
def test_every_generator_accepts_feedback(task):
    assert "feedback" in PREP_SIGNATURES[task][0].input_fields


@pytest.mark.parametrize("task", ["script_guardian", "poll_guardian", "explanation_guardian"])
def test_guardians_see_only_chunks_and_the_item(task):
    fields = set(PREP_SIGNATURES[task][0].input_fields)
    assert "chunks" in fields and "feedback" not in fields and "objective" not in fields


@pytest.mark.parametrize("task", list(PREP_SIGNATURES))
def test_instructions_carry_no_output_format(task):
    assert "JSON" not in PREP_SIGNATURES[task][0].instructions


def test_spoken_rules_in_script_and_explanation_writers():
    for task in ("script_writer", "explanation_writer"):
        assert "no Markdown, bullets, backticks, or code" in PREP_SIGNATURES[task][0].instructions
    assert "transitions" in PREP_SIGNATURES["script_guardian"][0].instructions.lower()
    assert "each wrong option" in PREP_SIGNATURES["poll_writer"][0].instructions.lower()


# ---------- DSPy module round trip ----------


@pytest.mark.parametrize("task", list(PREP_SIGNATURES))
def test_reply_parses_into_the_output_model(task):
    engine = FakeEngine(REPLIES[task])
    raw = call_llm(agents(engine), task, INPUTS[task], timeout_s=5)
    PREP_SIGNATURES[task][1].model_validate(raw)
    assert len(engine.requests) == 1  # one call per prediction


def test_null_chunk_id_string_is_normalized():
    raw = call_llm(
        agents(FakeEngine(REPLIES["explanation_guardian"])),
        "explanation_guardian",
        INPUTS["explanation_guardian"],
        5,
    )
    assert raw["claims"][0]["chunk_id"] is None
    assert check_prep_guardian(raw, ["d-p02-c1"], require_claims=True).passed is False


def test_feedback_and_chunks_reach_the_prompt():
    engine = FakeEngine(REPLIES["script_writer"])
    call_llm(agents(engine), "script_writer", INPUTS["script_writer"], 5)
    prompt = str(engine.requests[0].messages)
    assert "Gold is free" in prompt
    assert "[d-p02-c1] (d-p02) Three Layers | Bronze keeps raw data" in prompt
    assert "[ref-p01-c1] (reference) Raw data is kept" in prompt


def test_first_attempt_feedback_is_none_marker():
    fields = prep_signature_inputs("poll_writer", INPUTS["poll_writer"])
    assert fields["feedback"] == "(none)"


def test_rules_come_first_in_the_system_message():
    engine = FakeEngine(REPLIES["poll_guardian"])
    call_llm(agents(engine), "poll_guardian", INPUTS["poll_guardian"], 5)
    system = engine.requests[0].system
    text = system if isinstance(system, str) else "".join(getattr(p, "text", "") for p in system)
    assert text.startswith("You check a multiple-choice poll")


@pytest.mark.parametrize(
    "engine",
    [
        FakeEngine(REPLIES["poll_writer"], delay=0.5),
        FakeEngine(error=lm15.TimeoutError("000630")),
        FakeEngine(error=lm15.ServerError("503")),
        FakeEngine("not the field format"),
    ],
)
def test_timeout_error_or_bad_reply_is_llm_error(engine):
    with pytest.raises(LLMError):
        call_llm(agents(engine), "poll_writer", INPUTS["poll_writer"], timeout_s=0.1)


def test_fenced_field_value_parses():
    claims = '```json\n[{"claim": "Bronze keeps raw data.", "chunk_id": "d-p02-c1"}]\n```'
    reply = chat_reply(claims=claims, verdict="pass", reason="ok")
    engine = FakeEngine(reply)
    raw = call_llm(agents(engine), "explanation_guardian", INPUTS["explanation_guardian"], 5)
    assert raw["claims"][0]["chunk_id"] == "d-p02-c1"


@pytest.mark.parametrize("reply", ["[[ ", "not the field format"])
def test_unparseable_reply_is_a_malformed_reply_error(reply):
    with pytest.raises(MalformedReplyError):
        call_llm(agents(FakeEngine(reply)), "poll_writer", INPUTS["poll_writer"], 5)


# ---------- mock ----------


def test_mock_outputs_pass_their_structure_checks():
    llm = MockPrepLLM()
    allowed = {CHUNK_A["chunk_id"], CHUNK_REF["chunk_id"]}
    seg = PREP_SIGNATURES["segmenter"][1].model_validate(
        llm.complete("segmenter", INPUTS["segmenter"])
    )
    assert segmenter_problems(seg, ["d-p02"]) == []
    script = PREP_SIGNATURES["script_writer"][1].model_validate(
        llm.complete("script_writer", INPUTS["script_writer"])
    )
    assert script_problems(script, allowed) == []
    poll = PollOutput.model_validate(llm.complete("poll_writer", INPUTS["poll_writer"]))
    assert poll_problems(poll, allowed) == []
    expl = PREP_SIGNATURES["explanation_writer"][1].model_validate(
        llm.complete(
            "explanation_writer",
            {
                **INPUTS["explanation_writer"],
                "options": poll.options,
                "correct_option": poll.correct_option,
            },
        )
    )
    chunk_slide = {"d-p02-c1": "d-p02", "ref-p01-c1": None}
    assert explanation_problems(expl, allowed, chunk_slide, {"d-p02"}) == []


def test_mock_guardian_fails_an_invented_sentence():
    raw = MockPrepLLM().complete(
        "script_guardian",
        {"script": "Bronze keeps raw data. Gold is always free.", "cited_chunks": [CHUNK_A]},
    )
    check = check_prep_guardian(raw, ["d-p02-c1"], require_claims=False)
    assert check.passed is False and "Gold is always free" in check.problems[0]


def test_mock_error_injection():
    with pytest.raises(LLMError):
        MockPrepLLM(errors={"segmenter": "boom"}).complete("segmenter", INPUTS["segmenter"])


def test_scripted_llm_replays_then_falls_back_and_records_calls():
    llm = ScriptedPrepLLM({"poll_placer": [LLMError("x"), {"segment_ids": [], "reason": ""}]})
    with pytest.raises(LLMError):
        llm.complete("poll_placer", INPUTS["poll_placer"])
    assert llm.complete("poll_placer", INPUTS["poll_placer"])["segment_ids"] == []
    assert llm.complete("poll_placer", INPUTS["poll_placer"])["segment_ids"] == ["seg-01"]
    assert llm.count("poll_placer") == 3


def _words(text: str) -> str:
    return " ".join(text.split())


def test_closed_list_rule_is_the_same_in_poll_and_explanation_guardians():
    from classpilot.agents.prep_signatures import CLOSED_LIST_RULE

    for task in ("poll_guardian", "explanation_guardian"):
        instructions = _words(PREP_SIGNATURES[task][0].instructions)
        assert _words(CLOSED_LIST_RULE) in instructions, task


def test_writers_say_nothing_about_later_lessons_and_guardians_ask_for_quotes():
    for task in ("script_writer", "explanation_writer"):
        assert "later lessons" in _words(PREP_SIGNATURES[task][0].instructions)
    for task in ("script_guardian", "poll_guardian", "explanation_guardian"):
        assert "quote" in PREP_SIGNATURES[task][0].instructions
