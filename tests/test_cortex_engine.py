"""Route B engine with a fake Snowflake connection (no network)."""

import json
from typing import Literal

import dspy
import pytest

from classpilot.adapters.cortex_engine import CortexCompleteEngine, flatten, make_cortex_lm
from classpilot.settings import Settings


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        self.conn.calls.append((sql, params))
        if sql.startswith("ALTER SESSION"):
            return self
        reply = self.conn.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        self.reply = reply
        return self

    def fetchone(self):
        return (self.reply,)

    def close(self):
        pass


class FakeConnection:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def cursor(self):
        return FakeCursor(self)


def ok(value):
    return json.dumps({"value": value, "error": None})


class Echo(dspy.Signature):
    """Repeat the word."""

    word: str = dspy.InputField()
    category: Literal["a", "b"] = dspy.OutputField()


def predict(conn, timeout=10):
    settings = Settings(llm={"model": "mistral-large3", "timeout_seconds": timeout})
    lm = make_cortex_lm(settings, connection=conn)
    with dspy.context(lm=lm, adapter=dspy.ChatAdapter(use_json_adapter_fallback=False)):
        return dspy.Predict(Echo)(word="x")


def test_sets_statement_timeout_in_whole_seconds():
    conn = FakeConnection()
    CortexCompleteEngine(conn, timeout_s=2.5)
    assert conn.calls == [("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 3", None)]
    CortexCompleteEngine(conn, timeout_s=0.2)
    assert conn.calls[-1][0].endswith("= 1")


def test_prediction_goes_through_ai_complete_with_bound_model_and_prompt():
    conn = FakeConnection(ok("[[ ## category ## ]]\nb\n\n[[ ## completed ## ]]"))
    assert predict(conn).category == "b"
    sql, params = conn.calls[1]
    assert "AI_COMPLETE" in sql and "'max_tokens': 1024" in sql
    assert params[0] == "mistral-large3"
    assert "Repeat the word." in params[1] and "word" in params[1]
    assert len(conn.calls) == 2  # one ALTER SESSION, one call: no retries


@pytest.mark.parametrize(
    "reply",
    [
        None,
        json.dumps({"value": None, "error": "model overloaded"}),
        RuntimeError("000630 (57014): Statement reached its statement timeout"),
        RuntimeError("250001: connection reset"),
        ok("no field markers at all"),
    ],
)
def test_failures_raise(reply):
    with pytest.raises(Exception):  # noqa: B017 - call_llm maps every exception to llm_error
        predict(FakeConnection(reply))


def test_timeout_code_becomes_lm_timeout():
    from dspy import lm15

    engine = CortexCompleteEngine(FakeConnection(RuntimeError("000630: timeout")), 1)
    request = lm15.Request(model="m", messages=(lm15.Message.user("hi"),))
    with pytest.raises(lm15.TimeoutError):
        engine.complete(request)


def test_flatten_keeps_system_and_roles():
    from dspy import lm15

    request = lm15.Request(
        model="m", system="Be strict.", messages=(lm15.Message.user("Question?"),)
    )
    assert flatten(request) == "System:\nBe strict.\n\nUser:\nQuestion?"


def test_needs_a_model():
    with pytest.raises(ValueError):
        make_cortex_lm(Settings(llm={"model": None}), connection=FakeConnection())
