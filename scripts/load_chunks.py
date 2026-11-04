"""Load content/lesson_chunks.json into LESSON_CHUNKS (replaces all rows).

Run after sql/02_lesson_chunks_table.sql:
    python scripts/load_chunks.py
"""

import json

from classpilot.adapters.snowflake import connect
from classpilot.settings import PROJECT_ROOT


def main() -> None:
    lesson = json.loads((PROJECT_ROOT / "content" / "lesson_chunks.json").read_text())
    rows = [
        (chunk["chunk_id"], lesson["lesson_id"], chunk["objective_id"], chunk["text"])
        for chunk in lesson["chunks"]
    ]

    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("DELETE FROM LESSON_CHUNKS")
        cur.executemany(
            "INSERT INTO LESSON_CHUNKS (CHUNK_ID, LESSON_ID, OBJECTIVE_ID, CHUNK_TEXT)"
            " VALUES (%s, %s, %s, %s)",
            rows,
        )
        cur.execute("COMMIT")
        count = cur.execute("SELECT COUNT(*) FROM LESSON_CHUNKS").fetchone()[0]
        print(f"Loaded {len(rows)} chunks; table now has {count} rows.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
