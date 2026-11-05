"""Run a read-only SQL file statement by statement with the agent's connection (.env).

    python scripts/probes/readonly_sql.py sql/probes/stage7_account_inventory.sql

Only SHOW, DESC/DESCRIBE, SELECT, and USE WAREHOUSE run; any other statement is refused
before anything runs. `USE ROLE` lines are skipped: the service role is used as is, so
statements it may not run (for example SHOW USERS) are reported and the file continues.
Output goes to the terminal only; it can hold account-specific names, so do not paste it
into committed files.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from classpilot.adapters.snowflake import connect, load_env  # noqa: E402

READ_ONLY = re.compile(r"^(SHOW|DESC|DESCRIBE|SELECT|USE\s+WAREHOUSE)\b", re.IGNORECASE)
SKIP = re.compile(r"^USE\s+ROLE\b", re.IGNORECASE)
CELL = 60


def statements(sql: str) -> list[str]:
    lines = [re.sub(r"--.*$", "", line) for line in sql.splitlines()]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def show(cursor) -> None:
    columns = [d[0] for d in cursor.description or []]
    rows = cursor.fetchall()
    print(f"   {len(rows)} row(s)")
    for row in rows:
        cells = [
            f"{c}={str(v)[:CELL]}" for c, v in zip(columns, row, strict=True) if v not in (None, "")
        ]
        print("   - " + "; ".join(cells))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    todo = statements(args.file.read_text())
    refused = [s for s in todo if not (READ_ONLY.match(s) or SKIP.match(s))]
    if refused:
        raise SystemExit(f"refused, not read-only: {refused[0][:80]!r}")

    load_env()
    conn = connect()
    try:
        for sql in todo:
            first = " ".join(sql.split())[:100]
            if SKIP.match(sql):
                print(f"\n>> skipped: {first}")
                continue
            print(f"\n>> {first}")
            cursor = conn.cursor()
            try:
                cursor.execute(sql)
                show(cursor)
            except Exception as exc:
                print(f"   error: {str(exc).splitlines()[0][:200]}")
            finally:
                cursor.close()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
