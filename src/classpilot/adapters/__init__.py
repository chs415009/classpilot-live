"""Backend adapters. All Snowflake/Cortex-specific code stays in this package."""

from classpilot.adapters.llm import LLMClient, MockLLM
from classpilot.adapters.retrieval import CortexSearchRetriever, MockRetriever, Retriever
from classpilot.content import Content
from classpilot.settings import Settings


def make_adapters(settings: Settings, content: Content) -> tuple[LLMClient, Retriever]:
    if settings.backend == "cortex":
        from classpilot.agents.compiled import cortex_live_agents

        return cortex_live_agents(settings), CortexSearchRetriever(settings)
    return MockLLM(), MockRetriever(content.chunks)
