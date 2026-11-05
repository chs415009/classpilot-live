"""SQL templates with {{NAME}} placeholders for object names (scripts/run_sql.py).

Client-side rendering instead of IDENTIFIER($var), which Snowflake does not document for
every statement used here (Stage 0 finding). Every value must be a plain identifier, so
nothing else can be injected.
"""

import os
import re

from classpilot.settings import ObjectNames

IDENTIFIER = re.compile(r"^[A-Z_][A-Z0-9_$]*$")
PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


def object_names(objects: ObjectNames, env: dict[str, str] | None = None) -> dict[str, str]:
    """Placeholder values: account objects from .env (SNOWFLAKE_*), parse-layer objects
    from settings."""
    env = os.environ if env is None else env
    values = {
        "ROLE": env.get("SNOWFLAKE_ROLE", ""),
        "WAREHOUSE": env.get("SNOWFLAKE_WAREHOUSE", ""),
        "DATABASE": env.get("SNOWFLAKE_DATABASE", ""),
        "SCHEMA": env.get("SNOWFLAKE_SCHEMA", ""),
        "RAW_STAGE": objects.raw_stage,
        "RAW_FILES": objects.raw_files,
        "PARSED_PAGES": objects.parsed_pages,
        "CHUNKS": objects.chunks,
        "SEARCH_SERVICE": objects.search_service,
    }
    return {key: value.upper() for key, value in values.items()}


def render(template: str, values: dict[str, str]) -> str:
    used = set(PLACEHOLDER.findall(template))
    missing = sorted(used - values.keys())
    if missing:
        raise ValueError(f"unknown placeholders: {missing}")
    bad = sorted(key for key in used if not IDENTIFIER.match(values[key]))
    if bad:
        raise ValueError(f"not a plain identifier (check .env / settings): {bad}")
    return PLACEHOLDER.sub(lambda match: values[match.group(1)], template)
