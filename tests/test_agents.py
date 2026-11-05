"""DSPy agents with a fake engine (no network): signature sync, parsing, and errors."""

import json
import time
import typing

import dspy
import pytest
from dspy import lm15

from classpilot import rules
from classpilot.adapters.llm import LLMError, call_llm
from classpilot.agents.program import DSPyAgents, signature_inputs
from classpilot.agents.signatures import SIGNATURES
from classpilot.contracts import AnalystOutput, GuardianOutput, ResponderOutput
from classpilot.nodes.analyst import run_analyst
from classpilot.nodes.guardian import run_guardian
from classpilot.nodes.responder import run_responder


class FakeEngine:
    """Replies with fixed text (or raises), and records what it was sent."""

    def __init__(self, reply="", error=None, delay=0.0):
        self.reply, self.error, self.delay, self.requests = reply, error, delay, []

    def complete(self, request):
        self.requests.append(request)
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        return lm15.Response(
            id=None,
            model=request.model,
            message=lm15.Message.assistant(self.reply),
            finish_reason="stop",
            usage=lm15.Usage(),
        )


def chat_reply(**fields) -> str:
    """A reply in ChatAdapter's field format."""
    parts = []
    for name, value in fields.items():
        text = value if isinstance(value, str) else json.dumps(value)
        parts.append(f"[[ ## {name} ## ]]\n{text}")
    return "\n\n".join(parts + ["[[ ## completed ## ]]"])


def agents(engine):
    return DSPyAgents(dspy.LM("fake-model", engine=engine, cache=False, num_retries=0))


ANALYST_INPUTS = {
    "question_text": "Why keep raw data in Bronze?",
    "objectives": [{"objective_id": "seg-02", "title": "Why Bronze keeps raw data"}],
}
RESPONDER_INPUTS = {
    "question_text": "Why keep raw data in Bronze?",
    "chunks": [{"chunk_id": "chunk-01", "text": "Bronze keeps raw data.", "score": 0.7}],
}
GUARDIAN_INPUTS = {
    "question_text": "Why keep raw data in Bronze?",
    "answer_text": "Bronze keeps raw data.",
    "cited_chunks": [{"chunk_id": "chunk-01", "text": "Bronze keeps raw data."}],
}
GOOD = {
    "analyst": (
        ANALYST_INPUTS,
        chat_reply(category="in_scope", objective_id="seg-02", reason="About Bronze."),
    ),
    "responder": (
        RESPONDER_INPUTS,
        chat_reply(
            answer_text="Bronze keeps raw data.",
            citations=["chunk-01"],
            confidence="0.9",
            grounded="True",
        ),
    ),
    "guardian": (
        GUARDIAN_INPUTS,
        chat_reply(
            claims=[{"claim": "Bronze keeps raw data.", "chunk_id": "chunk-01"}],
            reveals_graded_work="False",
            verdict="pass",
            reason="Supported.",
        ),
    ),
}
MODELS = {"analyst": AnalystOutput, "responder": ResponderOutput, "guardian": GuardianOutput}


# ---------- signatures match the pydantic models ----------


@pytest.mark.parametrize("task", list(SIGNATURES))
def test_signature_output_fields_match_pydantic_model(task):
    signature, model = SIGNATURES[task]
    assert model is MODELS[task]
    sig_fields = {name: f.annotation for name, f in signature.output_fields.items()}
    model_fields = {name: f.annotation for name, f in model.model_fields.items()}
    assert sig_fields == model_fields


@pytest.mark.parametrize("task", list(SIGNATURES))
def test_signature_instructions_are_the_v1_text(task):
    signature, _ = SIGNATURES[task]
    first_line = {
        "analyst": "You help run a class session on this lesson.",
        "responder": "Answer the student question using ONLY the approved lesson chunks below.",
        "guardian": "You review an answer before a student sees it.",
    }[task]
    assert signature.instructions.startswith(first_line)
    assert "JSON" not in signature.instructions  # the adapter defines the format now


def test_literal_values_match_contract():
    analyst, _ = SIGNATURES["analyst"]
    assert typing.get_args(analyst.output_fields["category"].annotation) == (
        "in_scope",
        "out_of_scope",
        "assignment_like",
    )


# ---------- parsing ----------


@pytest.mark.parametrize("task", list(GOOD))
def test_good_reply_parses_into_the_contract_model(task):
    inputs, reply = GOOD[task]
    engine = FakeEngine(reply)
    raw = call_llm(agents(engine), task, inputs, timeout_s=5)
    MODELS[task].model_validate(raw)
    assert len(engine.requests) == 1  # one call per prediction: no retry, no fallback


def test_guardian_reply_passes_the_rule():
    inputs, reply = GOOD["guardian"]
    raw = call_llm(agents(FakeEngine(reply)), "guardian", inputs, timeout_s=5)
    assert rules.check_guardian(raw, ["chunk-01"]).passed is True


def test_none_string_is_normalized():
    reply = chat_reply(category="out_of_scope", objective_id="None", reason="Logistics.")
    raw = call_llm(agents(FakeEngine(reply)), "analyst", ANALYST_INPUTS, timeout_s=5)
    assert raw["objective_id"] is None
    claims = [{"claim": "Gold is fast.", "chunk_id": "null"}]
    reply = chat_reply(claims=claims, reveals_graded_work="False", verdict="fail", reason="x")
    raw = call_llm(agents(FakeEngine(reply)), "guardian", GUARDIAN_INPUTS, timeout_s=5)
    assert raw["claims"][0]["chunk_id"] is None


@pytest.mark.parametrize(
    "reply",
    [
        "I am not sure what you want.",
        chat_reply(category="maybe", objective_id="seg-02", reason="x"),  # not a Literal value
    ],
)
def test_malformed_reply_is_llm_error_and_escalates(reply):
    engine = FakeEngine(reply)
    result = run_analyst("Why Bronze?", ANALYST_INPUTS["objectives"], agents(engine), 5)
    assert result.raw is None and result.error
    assert len(engine.requests) == 1  # no JSON-adapter fallback call
    decision = rules.validate_final(
        early_reason="llm_error" if result.error else None,
        analyst_raw=result.raw,
        responder_raw=None,
        guardian_raw=None,
        retrieved_ids=[],
        confidence_threshold=0.7,
    )
    assert (decision.action, decision.escalation_reason) == ("escalate", "llm_error")


def test_prompt_carries_the_formatted_inputs():
    inputs, reply = GOOD["guardian"]
    engine = FakeEngine(reply)
    call_llm(agents(engine), "guardian", inputs, timeout_s=5)
    request = engine.requests[0]
    text = (request.system or "") + "".join(m.text for m in request.messages)
    assert "[chunk-01] Bronze keeps raw data." in text
    assert "Be strict" in text


def test_empty_chunks_are_shown_as_none():
    assert signature_inputs("responder", {"question_text": "q", "chunks": []})["chunks"] == "(none)"


# ---------- each module: success, timeout, error ----------


def node_call(task, engine, timeout_s=5):
    llm = agents(engine)
    if task == "analyst":
        return run_analyst("Why Bronze?", ANALYST_INPUTS["objectives"], llm, timeout_s)
    if task == "responder":
        from classpilot.adapters.retrieval import RetrievedChunk

        chunks = [RetrievedChunk("chunk-01", "Bronze keeps raw data.", 0.7)]
        return run_responder("Why Bronze?", chunks, llm, timeout_s)
    return run_guardian(
        "Why Bronze?", "Bronze keeps raw data.", GUARDIAN_INPUTS["cited_chunks"], llm, timeout_s
    )


@pytest.mark.parametrize("task", list(GOOD))
def test_module_success(task):
    result = node_call(task, FakeEngine(GOOD[task][1]))
    assert result.error is None
    MODELS[task].model_validate(result.raw)


@pytest.mark.parametrize("task", list(GOOD))
def test_module_timeout(task):
    result = node_call(task, FakeEngine(GOOD[task][1], delay=0.5), timeout_s=0.1)
    assert result.raw is None and "timed out" in result.error


@pytest.mark.parametrize(
    "error", [lm15.TimeoutError("000630 timeout"), lm15.ServerError("503"), ValueError("bug")]
)
@pytest.mark.parametrize("task", list(GOOD))
def test_module_engine_error(task, error):
    result = node_call(task, FakeEngine(error=error))
    assert result.raw is None and result.error


def test_call_llm_wraps_agent_errors_as_llm_error():
    with pytest.raises(LLMError):
        call_llm(agents(FakeEngine(error=lm15.ServerError("503"))), "analyst", ANALYST_INPUTS, 5)


def test_rules_come_first_in_the_system_message():
    inputs, reply = GOOD["guardian"]
    engine = FakeEngine(reply)
    call_llm(agents(engine), "guardian", inputs, timeout_s=5)
    system = engine.requests[0].system
    assert system.startswith("You review an answer before a student sees it.")
    assert system.index("Be strict") < system.index("Your input fields are")
