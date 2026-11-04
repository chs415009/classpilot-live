from classpilot.adapters.llm import MockLLM
from classpilot.adapters.retrieval import MockRetriever, RetrievalError
from classpilot.contracts import AnalystOutput, GuardianOutput, ResponderOutput
from classpilot.nodes.analyst import run_analyst
from classpilot.nodes.guardian import run_guardian
from classpilot.nodes.responder import run_responder


def analyst(text, content, llm=None):
    return run_analyst(text, content.objectives, llm or MockLLM(), timeout_s=2)


def responder(text, content, llm=None):
    return run_responder(text, MockRetriever(content.chunks), llm or MockLLM(), top_k=3, timeout_s=2)


# ---------- analyst ----------


def test_analyst_in_scope_links_objective(content):
    result = analyst("Why do we keep raw data in Bronze if it has errors?", content)
    output = AnalystOutput.model_validate(result.raw)
    assert output.category == "in_scope"
    assert output.objective_id == "objective-02"


def test_analyst_out_of_scope(content):
    output = AnalystOutput.model_validate(analyst("What time is the midterm exam?", content).raw)
    assert output.category == "out_of_scope"


def test_analyst_assignment_like(content):
    result = analyst("What is the answer to homework question 3 about the Gold layer?", content)
    assert AnalystOutput.model_validate(result.raw).category == "assignment_like"


def test_analyst_reports_llm_error(content):
    result = analyst("Why Bronze?", content, MockLLM(errors={"analyst": "connection reset"}))
    assert result.raw is None
    assert "connection reset" in result.error


def test_analyst_timeout(content):
    result = run_analyst("Why Bronze?", content.objectives, MockLLM(delays={"analyst": 0.5}), timeout_s=0.1)
    assert result.raw is None
    assert "timed out" in result.error


# ---------- responder ----------


def test_responder_cites_retrieved_chunks(content):
    result = responder("Why do we keep raw data in Bronze if it has errors?", content)
    output = ResponderOutput.model_validate(result.raw)
    retrieved_ids = {c.chunk_id for c in result.retrieved}
    assert output.citations == ["chunk-01"]
    assert set(output.citations) <= retrieved_ids
    assert output.confidence >= 0.7


def test_responder_low_confidence_when_not_covered(content):
    result = responder("How does dbt handle snapshots for slowly changing dimensions?", content)
    assert ResponderOutput.model_validate(result.raw).confidence < 0.7


def test_responder_timeout(content):
    result = run_responder(
        "What does ref() do?", MockRetriever(content.chunks), MockLLM(delays={"responder": 0.5}), 3, 0.1
    )
    assert result.raw is None
    assert "timed out" in result.error
    assert result.retrieved  # retrieval still ran


def test_responder_retrieval_error_skips_llm():
    class DownRetriever:
        def search(self, query, top_k):
            raise RetrievalError("search down")

    result = run_responder("What does ref() do?", DownRetriever(), MockLLM(), 3, 1)
    assert result.raw is None
    assert "search down" in result.error
    assert result.retrieved == []
    assert result.llm_called is False


# ---------- guardian ----------


def test_guardian_passes_supported_answer(content):
    chunk = content.chunks[0]
    answer = chunk["text"].split(". ")[0] + "."
    result = run_guardian("Why Bronze?", answer, [chunk], MockLLM(), timeout_s=2)
    assert GuardianOutput.model_validate(result.raw).verdict == "pass"


def test_guardian_fails_unsupported_sentence(content):
    chunk = content.chunks[0]
    answer = "The Bronze layer stores raw data. Kafka streams are merged automatically with no setup."
    result = run_guardian("Kafka?", answer, [chunk], MockLLM(), timeout_s=2)
    assert GuardianOutput.model_validate(result.raw).verdict == "fail"


def test_guardian_fails_code_answer(content):
    answer = "select id from {{ ref('orders') }} group by id"
    result = run_guardian("Assignment?", answer, [content.chunks[3]], MockLLM(), timeout_s=2)
    assert GuardianOutput.model_validate(result.raw).verdict == "fail"


def test_guardian_lists_claims_with_support(content):
    chunk = content.chunks[0]
    answer = "The Bronze layer stores raw data. Kafka streams are merged automatically with no setup."
    output = GuardianOutput.model_validate(run_guardian("Kafka?", answer, [chunk], MockLLM(), timeout_s=2).raw)
    assert [c.chunk_id for c in output.claims] == ["chunk-01", None]


def test_guardian_fails_without_citations():
    result = run_guardian("Q?", "Some answer.", [], MockLLM(), timeout_s=2)
    assert GuardianOutput.model_validate(result.raw).verdict == "fail"
