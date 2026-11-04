"""Stage 2 connection smoke test. Reads .env, runs trivial queries, prints results.

python scripts/smoke_test.py            # connection + context + chunk count
python scripts/smoke_test.py --search   # also query the Cortex Search service
"""

import argparse
import json

from classpilot.adapters.snowflake import connect

SEARCH_SERVICE = "LESSON_SEARCH"
DEFAULT_QUERY = "Why do we keep raw data in Bronze if it has errors?"


def sql_string(text: str) -> str:
    """Quote text as a SQL string literal (SEARCH_PREVIEW needs constant arguments)."""
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--search", nargs="?", const=DEFAULT_QUERY, metavar="QUERY")
    args = parser.parse_args()

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

        count = cur.execute("SELECT COUNT(*) FROM LESSON_CHUNKS").fetchone()[0]
        print(f"{'chunks':>10}: {count} rows in LESSON_CHUNKS")

        if args.search:
            db, schema = row[5], row[6]
            request = json.dumps(
                {"query": args.search, "columns": ["CHUNK_ID", "OBJECTIVE_ID"], "limit": 3}
            )
            result = cur.execute(
                "SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW("
                f"{sql_string(f'{db}.{schema}.{SEARCH_SERVICE}')}, {sql_string(request)})"
            ).fetchone()[0]
            print(f"\nsearch: {args.search}")
            for hit in json.loads(result)["results"]:
                print(f"  {hit['CHUNK_ID']}  ({hit['OBJECTIVE_ID']})")

        print("\nSmoke test passed.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
