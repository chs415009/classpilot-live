"""Connection smoke test. Reads .env, runs trivial queries, prints results.

python scripts/smoke_test.py                       # connection + context + chunk count
python scripts/smoke_test.py --search l1 "query"   # also query the Cortex Search service

Object names come from `objects` in config/settings.yaml (LESSON_CHUNKS_V2,
LESSON_SEARCH_V2). Search needs the service resumed (scripts/search_service.py).
"""

import argparse
import json

from classpilot.adapters.snowflake import connect
from classpilot.settings import load_settings

DEFAULT_QUERY = "What is a stack?"


def sql_string(text: str) -> str:
    """Quote text as a SQL string literal (SEARCH_PREVIEW needs constant arguments)."""
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--search", nargs="+", metavar=("LESSON_ID", "QUERY"))
    args = parser.parse_args()
    objects = load_settings().objects

    conn = connect()
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT CURRENT_ACCOUNT(), CURRENT_REGION(), CURRENT_USER(), CURRENT_ROLE(),"
            " CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA()"
        ).fetchone()
        labels = ["account", "region", "user", "role", "warehouse", "database", "schema"]
        for label, value in zip(labels, row, strict=True):
            print(f"{label:>10}: {value}")

        rows = cur.execute(
            f"SELECT LESSON_ID, COUNT(*) FROM {objects.chunks} GROUP BY LESSON_ID ORDER BY 1"
        ).fetchall()
        print(f"{'chunks':>10}: " + (", ".join(f"{lesson} {n}" for lesson, n in rows) or "none"))

        if args.search:
            lesson_id = args.search[0]
            query = " ".join(args.search[1:]) or DEFAULT_QUERY
            db, schema = row[5], row[6]
            request = json.dumps(
                {
                    "query": query,
                    "columns": ["CHUNK_ID"],
                    "filter": {"@eq": {"LESSON_ID": lesson_id}},
                    "limit": 3,
                }
            )
            result = cur.execute(
                "SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW("
                f"{sql_string(f'{db}.{schema}.{objects.search_service}')}, {sql_string(request)})"
            ).fetchone()[0]
            print(f"\nsearch ({lesson_id}): {query}")
            for hit in json.loads(result)["results"]:
                print(f"  {hit['CHUNK_ID']}")

        print("\nSmoke test passed.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
