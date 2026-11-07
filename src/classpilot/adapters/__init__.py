"""Backend adapters. All Snowflake/Cortex-specific code stays in this package."""

from classpilot.adapters.llm import LLMClient, MockLLM
from classpilot.adapters.retrieval import MockRetriever, Retriever
from classpilot.content import Content
from classpilot.settings import Settings


def make_adapters(settings: Settings, content: Content) -> tuple[LLMClient, Retriever]:
    """LLM and retriever for a fixture lesson (content/, scenarios, eval sets).

    Fixture chunks are not in Snowflake, so retrieval always reads them locally; with
    BACKEND=cortex only the LLM is real. Prepped lessons use CortexSearchRetriever
    (cli live_adapters, service context).
    """
    if settings.backend == "cortex":
        from classpilot.agents.compiled import cortex_live_agents

        return cortex_live_agents(settings), MockRetriever(content.chunks)
    return MockLLM(), MockRetriever(content.chunks)
