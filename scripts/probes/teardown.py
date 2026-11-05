"""Stage 1 teardown (approved 2026-11-04): remove the probe stage and suspend the v1
search service. No LLM calls."""

from classpilot.adapters.snowflake import shared_connection

cur = shared_connection().cursor()
for sql in [
    "REMOVE @PROBE_STAGE",
    "DROP STAGE IF EXISTS PROBE_STAGE",
    "ALTER CORTEX SEARCH SERVICE LESSON_SEARCH SUSPEND",
]:
    rows = cur.execute(sql).fetchall()
    print(f"{sql}\n  -> {len(rows)} row(s): {[r[:2] for r in rows][:5]}")
print("stages left:", [r[1] for r in cur.execute("SHOW STAGES").fetchall()])
for r in cur.execute("SHOW CORTEX SEARCH SERVICES").fetchall():
    cols = [c[0] for c in cur.description]
    d = dict(zip(cols, r, strict=True))
    print("search service:", d.get("name"), {k: v for k, v in d.items() if "state" in k.lower()})
