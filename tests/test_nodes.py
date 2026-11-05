from classpilot.adapters.llm import MockLLM
from classpilot.adapters.retrieval import MockRetriever, RetrievalError
from classpilot.contracts import AnalystOutput, GuardianOutput, ResponderOutput
from classpilot.nodes.analyst import run_analyst
from classpilot.nodes.guardian import run_guardian
from classpilot.nodes.responder import run_responder
from classpilot.nodes.retrieval import run_retrieval


def analyst(text, content, llm=None):
    return run_analyst(text, content.objectives, llm or MockLLM(), timeout_s=2)


LESSON = "lesson-dbt-medallion"


def retrieve(text, content):
    return MockRetriever(content.chunks).search(text, 3, LESSON)


def responder(text, content, llm=None):
    return run_responder(text, retrieve(text, content), llm or MockLLM(), timeout_s=2)


# ---------- analyst ----------


def test_analyst_in_scope_links_objective(content):
    result = analyst("Why do we keep raw data in Bronze if it has errors?", content)
    output = AnalystOutput.model_validate(result.raw)
    assert output.category == "in_scope"
    assert output.objective_id == "seg-02"


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
    result = run_analyst(
        "Why Bronze?", content.objectives, MockLLM(delays={"analyst": 0.5}), timeout_s=0.1
    )
    assert result.raw is None
    assert "timed out" in result.error


# ---------- responder ----------


def test_responder_cites_retrieved_chunks(content):
    text = "Why do we keep raw data in Bronze if it has errors?"
    result = responder(text, content)
    output = ResponderOutput.model_validate(result.raw)
    assert output.citations == ["chunk-01"]
    assert set(output.citations) <= {c.chunk_id for c in retrieve(text, content)}
    assert output.confidence >= 0.7


def test_responder_low_confidence_when_not_covered(content):
    result = responder("How does dbt handle snapshots for slowly changing dimensions?", content)
    assert ResponderOutput.model_validate(result.raw).confidence < 0.7


def test_responder_without_chunks_has_low_confidence():
    result = run_responder("What does ref() do?", [], MockLLM(), 2)
    output = ResponderOutput.model_validate(result.raw)
    assert output.citations == [] and output.confidence < 0.7


def test_responder_timeout(content):
    result = run_responder(
        "What does ref() do?",
        retrieve("What does ref() do?", content),
        MockLLM(delays={"responder": 0.5}),
        0.1,
    )
    assert result.raw is None
    assert "timed out" in result.error


# ---------- retrieval ----------


def test_retrieval_returns_lesson_chunks(content):
    result = run_retrieval(MockRetriever(content.chunks), "What does ref() do?", 3, LESSON)
    assert result.error is None
    assert result.chunks[0].chunk_id == "chunk-04"


def test_retrieval_error_is_reported():
    class DownRetriever:
        def search(self, query, top_k, lesson_id):
            raise RetrievalError("search down")

    result = run_retrieval(DownRetriever(), "What does ref() do?", 3, LESSON)
    assert result.chunks == []
    assert "search down" in result.error


# ---------- guardian ----------


def test_guardian_passes_supported_answer(content):
    chunk = content.chunks[0]
    answer = chunk["text"].split(". ")[0] + "."
    result = run_guardian("Why Bronze?", answer, [chunk], MockLLM(), timeout_s=2)
    assert GuardianOutput.model_validate(result.raw).verdict == "pass"


def test_guardian_fails_unsupported_sentence(content):
    chunk = content.chunks[0]
    answer = (
        "The Bronze layer stores raw data. Kafka streams are merged automatically with no setup."
    )
    result = run_guardian("Kafka?", answer, [chunk], MockLLM(), timeout_s=2)
    assert GuardianOutput.model_validate(result.raw).verdict == "fail"


def test_guardian_fails_code_answer(content):
    answer = "select id from {{ ref('orders') }} group by id"
    result = run_guardian("Assignment?", answer, [content.chunks[3]], MockLLM(), timeout_s=2)
    assert GuardianOutput.model_validate(result.raw).verdict == "fail"


def test_guardian_lists_claims_with_support(content):
    chunk = content.chunks[0]
    answer = (
        "The Bronze layer stores raw data. Kafka streams are merged automatically with no setup."
    )
    output = GuardianOutput.model_validate(
        run_guardian("Kafka?", answer, [chunk], MockLLM(), timeout_s=2).raw
    )
    assert [c.chunk_id for c in output.claims] == ["chunk-01", None]


def test_guardian_fails_without_citations():
    result = run_guardian("Q?", "Some answer.", [], MockLLM(), timeout_s=2)
    assert GuardianOutput.model_validate(result.raw).verdict == "fail"
