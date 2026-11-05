from types import SimpleNamespace

import pytest

from classpilot.adapters import make_adapters
from classpilot.adapters.llm import LLMError, MockLLM, call_llm
from classpilot.adapters.retrieval import (
    CortexSearchRetriever,
    MockRetriever,
    RetrievalError,
    RetrievedChunk,
)
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
        call_llm(MockLLM(delays={"analyst": 0.5}), "analyst", {}, timeout_s=0.1)


def test_call_llm_wraps_unexpected_exceptions():
    class Broken:
        def complete(self, task, inputs):
            raise RuntimeError("boom")

    with pytest.raises(LLMError, match="boom"):
        call_llm(Broken(), "analyst", {}, timeout_s=1)


def test_call_llm_rejects_non_dict():
    class ReturnsText:
        def complete(self, task, inputs):
            return "not json"

    with pytest.raises(LLMError):
        call_llm(ReturnsText(), "analyst", {}, timeout_s=1)


def test_mock_backend_makes_mock_adapters(content):
    llm, retriever = make_adapters(Settings(), content)
    assert isinstance(llm, MockLLM)
    assert isinstance(retriever, MockRetriever)


# ---------- Cortex adapters, with fake Snowflake objects (no network) ----------


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
