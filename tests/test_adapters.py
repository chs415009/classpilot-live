import json
from types import SimpleNamespace

import pytest

from classpilot.adapters import make_adapters
from classpilot.adapters.llm import CortexLLM, LLMError, MockLLM, call_llm, response_format
from classpilot.adapters.retrieval import (
    CortexSearchRetriever,
    MockRetriever,
    RetrievalError,
    RetrievedChunk,
)
from classpilot.contracts import AnalystOutput, GuardianOutput, ResponderOutput
from classpilot.settings import Settings


def test_mock_retriever_ranks_best_chunk_first(content):
    results = MockRetriever(content.chunks).search(
        "What does ref() do in a dbt model?", 3, "lesson-dbt-medallion"
    )
    assert results[0].chunk_id == "chunk-04"
    assert len(results) <= 3
    assert all(r.score > 0 for r in results)


def test_mock_retriever_returns_nothing_for_unrelated_query(content):
    assert MockRetriever(content.chunks).search("pizza recipe", 3, "lesson-dbt-medallion") == []


def test_mock_retriever_filters_by_lesson(content):
    retriever = MockRetriever(content.chunks)
    query = "What do dbt snapshots record over time?"
    own = [c.chunk_id for c in retriever.search(query, 3, "lesson-dbt-medallion")]
    other = [c.chunk_id for c in retriever.search(query, 3, "lesson-dbt-advanced")]
    assert "adv-chunk-01" not in own
    assert other == ["adv-chunk-01"]
    assert retriever.search(query, 3, "no-such-lesson") == []


def test_call_llm_timeout_raises_llm_error():
    with pytest.raises(LLMError, match="timed out"):
        call_llm(MockLLM(delays={"analyst": 0.5}), "analyst", "", {}, timeout_s=0.1)


def test_call_llm_wraps_unexpected_exceptions():
    class Broken:
        def complete_json(self, task, prompt, payload):
            raise RuntimeError("boom")

    with pytest.raises(LLMError, match="boom"):
        call_llm(Broken(), "analyst", "", {}, timeout_s=1)


def test_call_llm_rejects_non_dict():
    class ReturnsText:
        def complete_json(self, task, prompt, payload):
            return "not json"

    with pytest.raises(LLMError):
        call_llm(ReturnsText(), "analyst", "", {}, timeout_s=1)


def test_mock_backend_makes_mock_adapters(content):
    llm, retriever = make_adapters(Settings(), content)
    assert isinstance(llm, MockLLM)
    assert isinstance(retriever, MockRetriever)


# ---------- Cortex adapters, with fake Snowflake objects (no network) ----------


class FakeCursor:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def execute(self, sql, params, timeout=None):
        self.calls.append((sql, params, timeout))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self

    def fetchone(self):
        return (self.reply,)

    def close(self):
        pass


class FakeConnection:
    def __init__(self, reply):
        self.cursor_obj = FakeCursor(reply)

    def cursor(self):
        return self.cursor_obj


def cortex_llm(reply, timeout_seconds=10):
    settings = Settings(llm={"model": "mistral-large3", "timeout_seconds": timeout_seconds})
    return CortexLLM(settings, connection=FakeConnection(reply))


def test_cortex_llm_returns_value_and_binds_model_prompt_schema():
    llm = cortex_llm(json.dumps({"value": {"verdict": "pass", "reason": "ok"}, "error": None}))
    assert llm.complete_json("guardian", "the prompt", {}) == {"verdict": "pass", "reason": "ok"}

    sql, params, timeout = llm.connection.cursor_obj.calls[0]
    assert "AI_COMPLETE" in sql and "%s" in sql
    assert params[0] == "mistral-large3"
    assert params[1] == "the prompt"
    assert json.loads(params[2]) == response_format("guardian")
    assert timeout == 10


@pytest.mark.parametrize(
    "reply",
    [
        None,  # AI_COMPLETE returned NULL
        json.dumps({"value": None, "error": "model overloaded"}),
        json.dumps({"value": "plain text", "error": None}),
        RuntimeError("000604: query was canceled"),
    ],
)
def test_cortex_llm_failures_raise_llm_error(reply):
    with pytest.raises(LLMError):
        cortex_llm(reply).complete_json("analyst", "p", {})


def test_cortex_llm_timeout_is_whole_seconds_at_least_one():
    llm = cortex_llm(json.dumps({"value": {}, "error": None}), timeout_seconds=0.5)
    llm.complete_json("analyst", "p", {})
    assert llm.connection.cursor_obj.calls[0][2] == 1


def test_cortex_llm_needs_a_model():
    with pytest.raises(ValueError):
        CortexLLM(Settings(llm={"model": None}), connection=FakeConnection(None))


@pytest.mark.parametrize(
    ("task", "model"),
    [("analyst", AnalystOutput), ("responder", ResponderOutput), ("guardian", GuardianOutput)],
)
def test_response_format_matches_contract(task, model):
    schema = response_format(task)["schema"]
    assert set(schema["properties"]) == set(model.model_fields)
    assert schema["required"] == list(schema["properties"])
    assert schema["additionalProperties"] is False


class FakeSearchService:
    def __init__(self, rows=None, error=None):
        self.rows, self.error = rows or [], error
        self.kwargs = None

    def search(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(results=self.rows)


def test_cortex_search_maps_rows_and_cosine_score():
    service = FakeSearchService(
        [
            {
                "CHUNK_ID": "chunk-01",
                "CHUNK_TEXT": "Bronze keeps raw data.",
                "@scores": {"cosine_similarity": 0.72715},
            },
            {"CHUNK_ID": "chunk-02", "CHUNK_TEXT": "Silver holds cleaned data."},
        ]
    )
    results = CortexSearchRetriever(Settings(), service=service).search("why bronze", 2, "lesson-x")
    assert results == [
        RetrievedChunk("chunk-01", "Bronze keeps raw data.", 0.727),
        RetrievedChunk("chunk-02", "Silver holds cleaned data.", 0.0),
    ]
    assert service.kwargs == {
        "query": "why bronze",
        "columns": ["CHUNK_ID", "CHUNK_TEXT"],
        "filter": {"@eq": {"LESSON_ID": "lesson-x"}},
        "limit": 2,
    }


def test_cortex_search_error_raises_retrieval_error():
    service = FakeSearchService(error=RuntimeError("503"))
    with pytest.raises(RetrievalError):
        CortexSearchRetriever(Settings(), service=service).search("q", 3, "lesson-x")
