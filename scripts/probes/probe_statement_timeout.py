"""Does STATEMENT_TIMEOUT_IN_SECONDS cancel a running AI_COMPLETE? (live, 1 call).
Uses a separate connection so the session setting does not leak into other probes."""

import json
import time

from classpilot.adapters.snowflake import connect
from common import model_name, save

conn = connect()
cur = conn.cursor()
cur.execute("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 2")
start = time.perf_counter()
try:
    cur.execute(
        "SELECT AI_COMPLETE(%s, %s, {'max_tokens': 1024})",
        (model_name(), "Write a detailed 1500-word essay about data warehouse history."),
    )
    outcome = {"error": None, "chars": len(cur.fetchone()[0] or "")}
except Exception as exc:
    outcome = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
outcome["seconds"] = round(time.perf_counter() - start, 2)
outcome["query_id"] = cur.sfqid
conn.close()
print(save("statement_timeout", outcome))
print(json.dumps(outcome, indent=2))
