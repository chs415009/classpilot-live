"""Render a SQL template with the configured object names; print it, or run it.

    python scripts/run_sql.py sql/04_parse_objects.sql            # print only
    python scripts/run_sql.py sql/04_parse_objects.sql --execute  # run (after review)

Placeholders {{NAME}}: ROLE, WAREHOUSE, DATABASE, SCHEMA from .env (SNOWFLAKE_*), and
RAW_STAGE, RAW_FILES, PARSED_PAGES, CHUNKS, SEARCH_SERVICE from config/settings.yaml
`objects` (classpilot/sql_template.py).
"""

import argparse
from pathlib import Path

from classpilot.adapters.snowflake import load_env
from classpilot.settings import load_settings
from classpilot.sql_template import object_names, render


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("template", type=Path)
    parser.add_argument("--execute", action="store_true", help="run the rendered SQL")
    args = parser.parse_args()
    load_env()
    sql = render(args.template.read_text(), object_names(load_settings().objects))
    print(sql)
    if not args.execute:
        print("-- printed only; add --execute to run")
        return

    from classpilot.adapters.snowflake import connect

    conn = connect()
    try:
        for cursor in conn.execute_string(sql, remove_comments=True):
            print(f"-- ok: {cursor.query.strip().splitlines()[0][:80]} -> {cursor.fetchall()}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
