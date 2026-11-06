"""Prep adapters for a backend: mock (offline) or Cortex (shared by the CLI and the service)."""

from pathlib import Path

from classpilot.prep.generate import GenerateDeps, LessonMaterial
from classpilot.prep.parse import ParseDeps
from classpilot.prep.tables import PrepTables
from classpilot.settings import Settings


def make_tables(settings: Settings, mock_dir: Path) -> PrepTables:
    from classpilot.prep.tables import LocalTables, SnowflakeTables

    if settings.backend == "mock":
        return LocalTables(mock_dir)
    from classpilot.adapters.snowflake import shared_connection

    return SnowflakeTables(shared_connection(), settings.objects)


def make_parse_deps(settings: Settings, tables_dir: Path, convert_root: Path) -> ParseDeps:
    """Mock adapters and local tables, or Snowflake (backend cortex)."""
    from classpilot.adapters import parse as adapters

    cfg = settings.parse
    if settings.backend == "mock":
        stage = adapters.MockStage()
        return ParseDeps(
            stage,
            adapters.MockParser(stage),
            adapters.MockVision(),
            make_tables(settings, tables_dir),
            cfg,
            convert_root,
        )
    from classpilot.adapters.snowflake import shared_connection

    conn, stage_name = shared_connection(), settings.objects.raw_stage
    return ParseDeps(
        adapters.SnowflakeStage(conn, stage_name),
        adapters.CortexParser(conn, stage_name, cfg.parse_timeout_seconds),
        adapters.CortexVision(
            conn, stage_name, cfg.vision_model, cfg.vision_max_tokens, cfg.vision_timeout_seconds
        ),
        make_tables(settings, tables_dir),
        cfg,
        convert_root,
    )


def make_generate_deps(settings: Settings, material: LessonMaterial) -> GenerateDeps:
    """Mock generators and retrieval, or DSPy on Cortex and Cortex Search."""
    from classpilot.adapters.retrieval import CortexSearchRetriever, MockRetriever

    if settings.backend == "mock":
        from classpilot.adapters.mock_prep import MockPrepLLM

        llm, retriever = MockPrepLLM(), MockRetriever(material.retrieval_rows())
    else:
        from classpilot.adapters.cortex_engine import make_prep_lm
        from classpilot.agents.compiled import prep_agents

        llm = prep_agents(settings, make_prep_lm(settings))
        retriever = CortexSearchRetriever(settings, service_name=settings.objects.search_service)
    return GenerateDeps(llm, retriever, settings.prep, settings.poll)
