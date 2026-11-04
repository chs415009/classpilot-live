"""Backend adapters. All Snowflake/Cortex-specific code stays in this package."""

from classpilot.adapters.llm import CortexLLM, LLMClient, MockLLM
from classpilot.adapters.retrieval import CortexSearchRetriever, MockRetriever, Retriever
from classpilot.content import Content
from classpilot.settings import Settings


def make_adapters(settings: Settings, content: Content) -> tuple[LLMClient, Retriever]:
    if settings.backend == "cortex":
        return CortexLLM(settings), CortexSearchRetriever(settings)
    return MockLLM(), MockRetriever(content.chunks)
