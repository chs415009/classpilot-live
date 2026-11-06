"""Backend adapters. All Snowflake/Cortex-specific code stays in this package."""

from classpilot.adapters.llm import LLMClient, MockLLM
from classpilot.adapters.retrieval import CortexSearchRetriever, MockRetriever, Retriever
from classpilot.content import Content
from classpilot.settings import Settings


def make_adapters(settings: Settings, content: Content) -> tuple[LLMClient, Retriever]:
    if settings.backend == "cortex":
        from classpilot.adapters.cortex_engine import make_cortex_lm
        from classpilot.agents.compiled import live_agents

        return live_agents(settings, make_cortex_lm(settings)), CortexSearchRetriever(settings)
    return MockLLM(), MockRetriever(content.chunks)
