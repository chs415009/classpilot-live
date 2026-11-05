"""Resume, suspend, or show the state of the agent's Cortex Search service.

python scripts/search_service.py status
python scripts/search_service.py resume    # ALTER CORTEX SEARCH SERVICE <name> RESUME
python scripts/search_service.py suspend   # ALTER CORTEX SEARCH SERVICE <name> SUSPEND

Without INDEXING or SERVING, both layers are resumed or suspended (Snowflake docs,
ALTER CORTEX SEARCH SERVICE). Needs OPERATE on the service. Only these three fixed
statements can run; the service name is a choice, not free text.
"""

import argparse

from classpilot.adapters.snowflake import connect

SERVICES = ["LESSON_SEARCH_V2", "LESSON_SEARCH"]  # v2 (objects.search_service), v1


def state(cursor, name: str) -> dict:
    cursor.execute(f"SHOW CORTEX SEARCH SERVICES LIKE '{name}'")
    columns = [c[0].lower() for c in cursor.description]
    row = cursor.fetchone()
    if row is None:
        return {"name": name, "found": False}
    values = dict(zip(columns, row, strict=True))
    keys = ("name", "indexing_state", "serving_state", "attribute_columns")
    return {k: values.get(k) for k in keys}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["status", "resume", "suspend"])
    parser.add_argument("--service", choices=SERVICES, default=SERVICES[0])
    args = parser.parse_args()

    conn = connect()
    try:
        cursor = conn.cursor()
        if args.action != "status":
            cursor.execute(f"ALTER CORTEX SEARCH SERVICE {args.service} {args.action.upper()}")
            print(f"{args.action}: {cursor.fetchone()}")
        print(state(cursor, args.service))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
