"""Vision probe (live, 6 AI_COMPLETE calls): 3 slide PNGs (text-only, image, mixed) x 2
models, single-file AI_COMPLETE with the slide's text layer in the prompt. Structured
output is not available with images, so the reply is parsed as JSON in code.

History only: needs `pip install pymupdf` (AGPL-3.0, removed from the project
dependencies in Stage 4) and the Stage 1 materials file `materials/L1_slide.pdf`."""

import json
import os
import re
import time

from common import OUT_DIR, save

from classpilot.adapters.snowflake import shared_connection

SLIDES = dict(
    kv.split("=")
    for kv in os.environ.get("PROBE_SLIDES", "text_only=7,image=5,mixed=12").split(",")
)
SLIDES = {k: int(v) for k, v in SLIDES.items()}
MAX_TOKENS = str(int(os.environ.get("PROBE_MAX_TOKENS", "800")))
MODELS = os.environ.get("PROBE_VISION_MODELS", "claude-haiku-4-5,openai-gpt-5-nano").split(",")
PAGES = {p["index"]: p for p in json.loads((OUT_DIR / "pages.json").read_text())["pages"]}
PROMPT = """You describe one lecture slide image for a teaching system.
Describe only what is visible on the slide. Do not add outside knowledge.
The slide's extracted text layer is given below; use it to read text exactly.

Text layer:
{text}

Reply with JSON only, no Markdown fences:
{{"slide_text": "<all text on the slide>", "diagram_description": "<what the images or diagrams show, or empty if none>", "key_concepts": ["..."]}}"""

conn = shared_connection()
cur = conn.cursor()
cur.execute("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 30")
for idx in SLIDES.values():
    png = OUT_DIR / "slides" / f"p{idx:02d}.png"
    cur.execute(f"PUT 'file://{png}' @PROBE_STAGE/slides AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
cur.execute("ALTER STAGE PROBE_STAGE REFRESH")

import pymupdf  # noqa: E402

from classpilot.settings import PROJECT_ROOT  # noqa: E402

doc = pymupdf.open(PROJECT_ROOT / "materials" / "L1_slide.pdf")
results = []
for kind, idx in SLIDES.items():
    text = doc[idx].get_text().strip()
    for model in MODELS:
        start = time.perf_counter()
        row = {"kind": kind, "index": idx, "model": model}
        try:
            raw = cur.execute(
                "SELECT AI_COMPLETE(%s, %s, TO_FILE('@PROBE_STAGE', %s), "
                "{'temperature': 0, 'max_tokens': " + MAX_TOKENS + "})",
                (model, PROMPT.format(text=text), f"slides/p{idx:02d}.png"),
            ).fetchone()[0]
            row["query_id"] = cur.sfqid
            reply = json.loads(raw) if isinstance(raw, str) and raw.startswith('"') else raw
            row["reply"] = reply
            body = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(reply).strip())
            try:
                parsed = json.loads(body)
                row["json_ok"] = isinstance(parsed, dict) and {
                    "slide_text",
                    "diagram_description",
                    "key_concepts",
                } <= set(parsed)
                row["parsed"] = parsed
                row["fenced"] = body != str(reply).strip()
            except json.JSONDecodeError:
                row["json_ok"] = False
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        row["seconds"] = round(time.perf_counter() - start, 2)
        results.append(row)

print(save("vision_" + "_".join(MODELS), results))
for r in results:
    p = r.get("parsed") or {}
    print(
        f"[{r['kind']:9} p{r['index']:02d}] {r['model']:17} {r['seconds']:5}s json_ok={r.get('json_ok')} "
        f"fenced={r.get('fenced')} err={r.get('error', '')[:120]}"
    )
    if p:
        print("   diagram:", (p.get("diagram_description") or "")[:220])
        print("   concepts:", p.get("key_concepts"))
