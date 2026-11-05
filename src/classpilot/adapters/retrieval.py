"""Retriever interface over lesson chunks, filtered by lesson: a mock and Cortex Search."""

from dataclasses import dataclass
from typing import Protocol

from classpilot.settings import Settings
from classpilot.text import coverage

SEARCH_SERVICE = "LESSON_SEARCH"


class RetrievalError(Exception):
    """Search backend failed (connection problem, service error)."""


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    score: float


class Retriever(Protocol):
    def search(self, query: str, top_k: int, lesson_id: str) -> list[RetrievedChunk]: ...


class MockRetriever:
    """Ranks the lesson's chunks by how many of the query's content words they contain."""

    def __init__(self, chunks: list[dict]):
        self.chunks = chunks

    def search(self, query: str, top_k: int, lesson_id: str) -> list[RetrievedChunk]:
        scored = [
            RetrievedChunk(c["chunk_id"], c["text"], round(coverage(query, c["text"]), 3))
            for c in self.chunks
            if c["lesson_id"] == lesson_id
        ]
        scored = [c for c in scored if c.score > 0]
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:top_k]


class CortexSearchRetriever:
    """Queries the Cortex Search service over the approved lesson chunks.

    Uses the snowflake-core Python API on the shared connector connection.
    Score = `@scores.cosine_similarity` (range -1..1); the other score fields are
    unbounded and depend on the query.

    Every query is filtered on the LESSON_ID attribute (syntax checked in Stage 1;
    the v1 LESSON_SEARCH service already has LESSON_ID as an attribute).
    """

    def __init__(self, settings: Settings, service=None):
        self.settings = settings
        if service is None:
            import os

            from snowflake.core import Root

            from classpilot.adapters.snowflake import shared_connection

            service = (
                Root(shared_connection())
                .databases[os.environ["SNOWFLAKE_DATABASE"]]
                .schemas[os.environ["SNOWFLAKE_SCHEMA"]]
                .cortex_search_services[SEARCH_SERVICE]
            )
        self.service = service

    def search(self, query: str, top_k: int, lesson_id: str) -> list[RetrievedChunk]:
        try:
            response = self.service.search(
                query=query,
                columns=["CHUNK_ID", "CHUNK_TEXT"],
                filter={"@eq": {"LESSON_ID": lesson_id}},
                limit=top_k,
            )
        except Exception as exc:
            raise RetrievalError(f"Cortex Search failed: {exc}") from exc
        return [
            RetrievedChunk(
                row["CHUNK_ID"],
                row["CHUNK_TEXT"],
                round(float(row.get("@scores", {}).get("cosine_similarity", 0.0)), 3),
            )
            for row in response.results
        ]
