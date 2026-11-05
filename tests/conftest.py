import pytest

from classpilot.adapters.llm import MockLLM
from classpilot.adapters.retrieval import MockRetriever
from classpilot.content import load_content
from classpilot.contracts import PollEvidence, StudentQuestion
from classpilot.graph import Deps
from classpilot.settings import Settings


@pytest.fixture(autouse=True)
def force_mock_backend(monkeypatch):
    # Tests never call Snowflake, even if the shell has BACKEND=cortex set.
    monkeypatch.setenv("BACKEND", "mock")
    monkeypatch.delenv("AGENT_MODE", raising=False)


@pytest.fixture
def content():
    return load_content()


@pytest.fixture
def settings():
    # Defaults from code, not the yaml file, so tests do not depend on local edits.
    return Settings()


@pytest.fixture
def deps(settings, content):
    return Deps(settings, content, MockLLM(), MockRetriever(content.chunks))


@pytest.fixture
def make_evidence():
    def _make(option_counts, answers=None, correct="A", poll_id="q-01"):
        return PollEvidence(
            session_id="session-001",
            poll_id=poll_id,
            objective_id="seg-02",
            question_id=poll_id,
            snapshot_time="2026-10-22T18:30:40Z",
            connected_students=24,
            answers_received=answers if answers is not None else sum(option_counts.values()),
            option_counts=option_counts,
            correct_option=correct,
        )

    return _make


@pytest.fixture
def make_question():
    def _make(text):
        return StudentQuestion(
            session_id="session-001",
            event_id="evt-test",
            anonymous_learner_id="learner-001",
            question_text=text,
            submitted_at="2026-10-22T18:31:05Z",
        )

    return _make
