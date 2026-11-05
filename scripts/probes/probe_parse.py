"""Parse probe (live, 2 AI_PARSE_DOCUMENT calls, 11 pages): create the approved probe
stage, PUT the two materials uncompressed, refresh, and parse both in LAYOUT mode with
page_split. Saves the full output to outputs/probes/ (gitignored; real course content)."""

import json
import time

from classpilot.adapters.snowflake import shared_connection
from classpilot.settings import PROJECT_ROOT
from common import save

MATERIALS = PROJECT_ROOT / "materials"
FILES = ["L1_pdf.pdf", "L1_slide.pdf"]
conn = shared_connection()
cur = conn.cursor()
cur.execute(
    "CREATE STAGE IF NOT EXISTS PROBE_STAGE DIRECTORY = (ENABLE = TRUE) "
    "ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE') "
    "COMMENT = 'Stage 1 probes only; dropped at the end of Stage 1'"
)
for name in FILES:
    cur.execute(f"PUT 'file://{MATERIALS / name}' @PROBE_STAGE AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
cur.execute("ALTER STAGE PROBE_STAGE REFRESH")
listing = [(r[0], r[1]) for r in cur.execute("LIST @PROBE_STAGE").fetchall()]

results = {"listing": listing}
for name in FILES:
    start = time.perf_counter()
    try:
        row = cur.execute(
            "SELECT AI_PARSE_DOCUMENT(TO_FILE('@PROBE_STAGE', %s), "
            "{'mode': 'LAYOUT', 'page_split': TRUE})",
            (name,),
        ).fetchone()
        parsed = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        results[name] = {"seconds": round(time.perf_counter() - start, 2),
                         "query_id": cur.sfqid, "output": parsed}
    except Exception as exc:
        results[name] = {"seconds": round(time.perf_counter() - start, 2),
                         "error": f"{type(exc).__name__}: {str(exc)[:300]}"}

print(save("parse", results))
print("listing:", listing)
for name in FILES:
    r = results[name]
    if "error" in r:
        print(name, "ERROR", r["error"]); continue
    out = r["output"]
    pages = out.get("pages", [])
    print(f"{name}: {r['seconds']} s, keys={list(out)}, pageCount={out.get('metadata', {}).get('pageCount')}, pages={len(pages)}")
    for p in pages:
        c = p.get("content", "")
        print(f"  page index={p.get('index')} chars={len(c)} first={c[:70]!r}")
