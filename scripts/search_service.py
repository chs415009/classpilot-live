"""Resume, suspend, or show the state of the agent's Cortex Search service.

python scripts/search_service.py status
python scripts/search_service.py resume    # ALTER CORTEX SEARCH SERVICE <name> RESUME
python scripts/search_service.py suspend   # ALTER CORTEX SEARCH SERVICE <name> SUSPEND

Without INDEXING or SERVING, both layers are resumed or suspended (Snowflake docs,
ALTER CORTEX SEARCH SERVICE). Needs OPERATE on the service. Only these three fixed
statements can run, on `objects.search_service` from config/settings.yaml.
"""

import argparse

from classpilot.adapters.snowflake import connect
from classpilot.settings import load_settings


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
    args = parser.parse_args()
    service = load_settings().objects.search_service

    conn = connect()
    try:
        cursor = conn.cursor()
        if args.action != "status":
            cursor.execute(f"ALTER CORTEX SEARCH SERVICE {service} {args.action.upper()}")
            print(f"{args.action}: {cursor.fetchone()}")
        print(state(cursor, service))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
