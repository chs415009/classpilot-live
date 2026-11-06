"""Dev report (Stage 10): numbers and views from one run's data, and static HTML.

Input is the run's `results.json` (written by `cli dev`): the manifest, the generation
report, the check problems, the chunk texts, and the test-question rows. Everything
here is plain code over that data; no LLM is called. Large blocks are collapsed with
<details>. Theming follows the v1 report.
"""

import re
from collections import Counter
from html import escape
from pathlib import Path

STATUSES = ["ok", "ok_after_retry", "fallback", "dropped"]

# ---------- numbers and views ----------


def _items(gen_report: dict | None) -> dict[str, dict]:
    return {i["item"]: i for i in (gen_report or {}).get("items", [])}


def _items_with_prefix(gen_report: dict | None, prefix: str) -> list[dict]:
    return [i for i in (gen_report or {}).get("items", []) if i["item"].startswith(prefix)]


def _questions(manifest: dict) -> list[tuple[dict, str, dict]]:
    return [(seg, qid, q) for seg in manifest["segments"] for qid, q in seg["questions"].items()]


def status_counts(manifest: dict, gen_report: dict | None) -> dict[str, dict[str, int]]:
    """Item statuses per kind. Explanations come from the generation report when there
    is one, because a dropped explanation is not written to the manifest."""
    explanations = [i["status"] for i in _items_with_prefix(gen_report, "explanation ")]
    if not gen_report:
        explanations = [r["status"] for r in manifest["remediations"].values()]
    kinds = {
        "scripts": [s["status"] for s in manifest["slides"].values()],
        "polls": [q["status"] for _, _, q in _questions(manifest)],
        "explanations": explanations,
    }
    return {kind: {s: Counter(v)[s] for s in STATUSES} for kind, v in kinds.items()}


def missing_explanations(manifest: dict) -> list[tuple[str, str]]:
    """(poll id, option) for every wrong option of a poll in use that has no explanation."""
    out = []
    for _, qid, q in _questions(manifest):
        if q["status"] == "dropped":
            continue
        for option in q["options"]:
            if option != q["correct_option"] and option not in q["known_wrong"]:
                out.append((qid, option))
    return out


def slide_views(manifest: dict, gen_report: dict | None) -> list[dict]:
    items = _items(gen_report)
    rows = []
    for slide_id, slide in sorted(manifest["slides"].items(), key=lambda kv: kv[1]["order"]):
        item = items.get(f"script {slide_id}", {})
        rows.append(
            {
                "slide_id": slide_id,
                "order": slide["order"],
                "image_ref": slide["image_ref"],
                "status": slide["status"],
                "script": slide["script"],
                "detail": item.get("detail", ""),
                "citations": item.get("citations", []),
                "attempts": item.get("attempts", []),
            }
        )
    return rows


def poll_views(manifest: dict, gen_report: dict | None) -> list[dict]:
    items = _items(gen_report)
    views = []
    for seg, qid, q in _questions(manifest):
        poll_item = next((i for i in _items_with_prefix(gen_report, f"poll {qid} ")), {})
        wrong = []
        for option, text in q["options"].items():
            if option == q["correct_option"]:
                continue
            row = {"option": option, "text": text, "misconception": None, "remediation": None}
            mid = q["known_wrong"].get(option)
            if mid and mid in manifest["misconceptions"]:
                row["misconception"] = {"id": mid, **manifest["misconceptions"][mid]}
                rid = manifest["misconceptions"][mid]["remediation"]
                if rid in manifest["remediations"]:
                    row["remediation"] = {"id": rid, **manifest["remediations"][rid]}
            item = items.get(f"explanation {qid} {option}", {})
            row["status"] = (row["remediation"] or {}).get("status") or item.get("status")
            row["attempts"] = item.get("attempts", [])
            wrong.append(row)
        views.append(
            {
                "poll_id": qid,
                "segment_id": seg["segment_id"],
                "objective": seg["objective"],
                "active": seg["active_poll"] == qid,
                "status": q["status"],
                "text": q["text"],
                "options": q["options"],
                "correct_option": q["correct_option"],
                "detail": poll_item.get("detail", ""),
                "attempts": poll_item.get("attempts", []),
                "wrong": wrong,
            }
        )
    return views


def question_summary(rows: list[dict]) -> dict:
    by_category: dict[str, dict[str, int]] = {}
    for r in rows:
        c = by_category.setdefault(r["category"], {"total": 0, "match": 0})
        c["total"] += 1
        c["match"] += r["match"]
    latencies = [r["latency_ms"] for r in rows]
    return {
        "total": len(rows),
        "match": sum(r["match"] for r in rows),
        "to_check": sum(not r["match"] for r in rows),
        "answered": sum(r["action"] == "answer" for r in rows),
        "escalated": sum(r["action"] == "escalate" for r in rows),
        "let_through": sum(
            r["expected_action"] == "escalate" and r["action"] == "answer" for r in rows
        ),
        "false_escalations": sum(
            r["expected_action"] == "answer" and r["action"] == "escalate" for r in rows
        ),
        "llm_errors": sum(r["escalation_reason"] == "llm_error" for r in rows),
        "by_category": by_category,
        "llm_calls": sum(r["llm_calls"] for r in rows),
        "latency_ms_avg": round(sum(latencies) / len(latencies)) if latencies else None,
        "latency_ms_max": max(latencies) if latencies else None,
    }


def summarize(data: dict) -> dict:
    """The overview numbers; also what the index page lists per run."""
    manifest, gen = data["prep"]["manifest"], data["prep"]["generation_report"]
    counts = status_counts(manifest, gen)
    polls = [q for _, _, q in _questions(manifest)]
    wrong_total = sum(
        len(q["options"]) - 1 for q in polls if q["status"] != "dropped" and q["options"]
    )
    missing = missing_explanations(manifest)
    return {
        "run_id": data["run_id"],
        "lesson_id": data["lesson_id"],
        "created_at": data["created_at"],
        "backend": data["backend"],
        "statuses": counts,
        "slides": len(manifest["slides"]),
        "active_polls": sum(1 for s in manifest["segments"] if s["active_poll"]),
        "polls": len(polls),
        "wrong_options": wrong_total,
        "wrong_options_explained": wrong_total - len(missing),
        "missing_explanations": len(missing),
        "check_problems": len(data["prep"].get("check_problems", [])),
        "prep_llm_calls": (gen or {}).get("llm_calls"),
        "questions": question_summary(data["live"]["rows"]),
    }


def ordered_rows(rows: list[dict]) -> list[dict]:
    """Questions to check (not matching expected) first, then file order."""
    return [r for r in rows if not r["match"]] + [r for r in rows if r["match"]]


# ---------- HTML ----------

CSS = """
:root { --bg:#fbfbfa; --fg:#1d1d1f; --muted:#6b6b70; --line:#e3e3e0; --card:#ffffff;
        --ok:#1f7a3a; --bad:#b3261e; --warn:#8a5a00; --chip:#f0f0ed; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#151517; --fg:#ececee; --muted:#9a9aa2; --line:#2c2c31; --card:#1c1c1f;
          --ok:#5cc47a; --bad:#ff7b72; --warn:#e3b341; --chip:#26262a; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
       font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 36px 0 10px; }
h3 { font-size: 15px; margin: 0 0 6px; }
a { color: inherit; }
.muted { color: var(--muted); }
.small { font-size: 12.5px; }
.banner { border:1px solid var(--warn); color:var(--warn); border-radius:8px; padding:10px 14px;
  margin:16px 0; }
.tiles { display:grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap:10px;
  margin:16px 0; }
.tile { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:12px 14px; }
.tile .num { font-size:22px; font-weight:600; }
.table-wrap { overflow-x:auto; border:1px solid var(--line); border-radius:10px;
  background:var(--card); }
table { border-collapse: collapse; width:100%; font-size:13.5px; }
th, td { text-align:left; padding:10px 12px; border-bottom:1px solid var(--line);
  vertical-align:top; }
th { color:var(--muted); font-weight:600; white-space:nowrap; }
tr:last-child td { border-bottom:none; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:14px 16px; margin:10px 0; }
.ok { color:var(--ok); font-weight:600; } .bad { color:var(--bad); font-weight:600; }
.warn { color:var(--warn); font-weight:600; }
.chip { display:inline-block; background:var(--chip); border-radius:6px; padding:0 6px;
  font-size:12px; margin:0 2px 2px 0; }
img.thumb { width:150px; max-width:100%; border:1px solid var(--line); border-radius:6px;
  display:block; }
details { margin-top:6px; }
details summary { cursor:pointer; color:var(--muted); font-size:12.5px; }
details .body { margin-top:6px; font-size:13px; }
.quote { border-left:3px solid var(--line); padding-left:10px; margin:6px 0; white-space:pre-wrap; }
ul.tight { margin:4px 0; padding-left:18px; }
"""

STATUS_CSS = {"ok": "ok", "ok_after_retry": "warn", "fallback": "bad", "dropped": "bad"}


def _e(value) -> str:
    return escape("" if value is None else str(value))


def _status(status: str | None) -> str:
    return f"<span class='{STATUS_CSS.get(status or '', 'muted')}'>{_e(status or '-')}</span>"


def _chips(ids, marked: set[str] | None = None) -> str:
    marked = marked or set()
    return (
        "".join(f"<span class='chip'>{'✓ ' if i in marked else ''}{_e(i)}</span>" for i in ids)
        or "<span class='muted'>none</span>"
    )


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0] if text else ""


def _chunk_quotes(ids, chunks: dict[str, str]) -> str:
    return "".join(
        f"<div class='small'><b>{_e(i)}</b></div><div class='quote small'>"
        f"{_e(chunks.get(i, '(text not found)'))}</div>"
        for i in ids
    )


def _attempts(attempts: list[dict]) -> str:
    if not attempts:
        return ""
    parts = []
    for n, a in enumerate(attempts, 1):
        g = a.get("guardian") or {}
        head = f"Attempt {n}: <b>{_e(a.get('outcome'))}</b>"
        if g:
            head += f" · Guardian {_e(g.get('verdict'))}: {_e(g.get('reason'))}"
        lines = [f"<li>problem: {_e(p)}</li>" for p in a.get("problems") or []]
        for c in g.get("claims") or []:
            if isinstance(c, dict):
                kind = f" ({_e(c.get('kind'))})" if c.get("kind") else ""
                lines.append(
                    f"<li>claim{kind}: {_e(c.get('claim'))} → <code>{_e(c.get('chunk_id'))}</code>"
                    "</li>"
                )
        lines += [f"<li>rescued by code: {_e(r)}</li>" for r in a.get("rescued") or []]
        parts.append(f"<div class='small'>{head}<ul class='tight'>{''.join(lines)}</ul></div>")
    return (
        f"<details><summary>Guardian attempts ({len(attempts)})</summary>"
        f"<div class='body'>{''.join(parts)}</div></details>"
    )


def _tile(num, label: str, note: str = "", css: str = "") -> str:
    return (
        f"<div class='tile'><div class='num {css}'>{_e(num)}</div><div>{_e(label)}</div>"
        f"<div class='muted small'>{_e(note)}</div></div>"
    )


def _counts_note(counts: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in counts.items() if v) or "none"


def render_overview(data: dict, summary: dict) -> str:
    st, q = summary["statuses"], summary["questions"]
    scripts_ok = st["scripts"]["ok"] + st["scripts"]["ok_after_retry"]
    tiles = [
        _tile(
            f"{scripts_ok}/{summary['slides']}",
            "scripts generated",
            _counts_note(st["scripts"]),
            "ok" if scripts_ok == summary["slides"] else "warn",
        ),
        _tile(f"{summary['active_polls']}", "polls in use", _counts_note(st["polls"])),
        _tile(
            f"{summary['wrong_options_explained']}/{summary['wrong_options']}",
            "wrong options explained",
            _counts_note(st["explanations"]),
            "ok" if not summary["missing_explanations"] else "warn",
        ),
        _tile(
            f"{q['match']}/{q['total']}",
            "test questions as expected",
            f"{q['to_check']} to check",
            "ok" if not q["to_check"] else "warn",
        ),
        _tile(
            f"{(q['latency_ms_avg'] or 0) / 1000:.1f} s",
            "answer latency avg",
            f"max {(q['latency_ms_max'] or 0) / 1000:.1f} s",
        ),
    ]
    prep, live = data["prep"], data["live"]
    gen = prep["generation_report"] or {}
    meta = [
        ("Slides", ", ".join(data["files"]["slides"])),
        ("References", ", ".join(data["files"]["refs"]) or "none"),
        ("Backend", data["backend"]),
        (
            "Prep",
            f"{'ran now' if prep['ran'] else 'reused the last prep'} · program "
            f"{gen.get('prompt_version') or '-'} · model {prep.get('model') or '-'} · "
            f"{gen.get('llm_calls', '-')} LLM calls · {gen.get('seconds', '-')} s",
        ),
        (
            "Live",
            f"program {', '.join(live['prompt_versions']) or '-'} · model "
            f"{', '.join(live['models']) or '-'} · {q['llm_calls']} LLM calls · "
            f"{live['seconds']} s",
        ),
    ]
    html = f"<div class='tiles'>{''.join(tiles)}</div>"
    html += (
        "<div class='table-wrap'><table>"
        + "".join(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in meta)
        + "</table></div>"
    )
    extra = prep.get("extra_files") or []
    if extra:
        html += (
            "<div class='banner'>The lesson also holds files that are not in its folder "
            f"(added earlier): {_e(', '.join(extra))}. Its scripts and chunks include them.</div>"
        )
    problems = prep.get("check_problems") or []
    if problems:
        items = "".join(f"<li>{_e(p)}</li>" for p in problems)
        html += (
            f"<div class='banner'>Manifest checks: {len(problems)} problem(s)"
            f"<details><summary>list</summary><ul class='tight'>{items}</ul></details></div>"
        )
    return html


def render_scripts(data: dict) -> str:
    chunks = data["chunks"]
    rows = []
    for s in slide_views(data["prep"]["manifest"], data["prep"]["generation_report"]):
        extra = ""
        if s["detail"]:
            extra += f"<div class='small'>fallback: {_e(s['detail'])}</div>"
        body = (
            f"<div class='quote'>{_e(s['script'])}</div>{extra}"
            f"<div class='small'>cited: {_chips(s['citations'])}</div>"
            f"{_chunk_quotes(s['citations'], chunks)}"
        )
        rows.append(
            f"<tr><td><img class='thumb' loading='lazy' src='{_e(s['image_ref'])}' "
            f"alt='{_e(s['slide_id'])}'></td>"
            f"<td><b>{s['order']}</b> <span class='muted small'>{_e(s['slide_id'])}</span><br>"
            f"{_status(s['status'])}</td>"
            f"<td>{_e(_first_sentence(s['script']))}"
            f"<details><summary>full script and sources</summary><div class='body'>{body}</div>"
            "</details>"
            f"{_attempts(s['attempts'])}</td></tr>"
        )
    return (
        "<div class='table-wrap'><table><tr><th>Slide</th><th>Status</th><th>Script</th></tr>"
        + "".join(rows)
        + "</table></div>"
    )


def render_polls(data: dict) -> str:
    chunks, slides = data["chunks"], data["prep"]["manifest"]["slides"]
    cards = []
    for p in poll_views(data["prep"]["manifest"], data["prep"]["generation_report"]):
        role = "in use" if p["active"] else ("dropped" if p["status"] == "dropped" else "backup")
        head = (
            f"<h3>{_e(p['poll_id'])} · {_e(p['segment_id'])} {_e(p['objective'])}</h3>"
            f"<div class='small'>{_status(p['status'])} · {role}"
            f"{' · ' + _e(p['detail']) if p['detail'] else ''}</div>"
        )
        options = "".join(
            f"<li>{'<span class=ok>✓</span> ' if k == p['correct_option'] else ''}<b>{_e(k)}</b> "
            f"{_e(v)}</li>"
            for k, v in p["options"].items()
        )
        if p["status"] == "dropped":  # not used in class: no explanations to show
            last = (
                "<div class='muted small'>Last draft that passed the structure checks:</div>"
                f"<p>{_e(p['text'])}</p><ul class='tight'>{options}</ul>"
                if p["options"]
                else ""
            )
            cards.append(
                f"<div class='card'>{head}<div class='muted small'>Not used in class.</div>"
                f"{last}{_attempts(p['attempts'])}</div>"
            )
            continue
        wrong_rows = []
        for w in p["wrong"]:
            rem = w["remediation"]
            if rem:
                img = slides.get(rem["show_slide"], {}).get("image_ref")
                body = (
                    f"<div class='small'>misconception {_e(w['misconception']['id'])}: "
                    f"<b>{_e(w['misconception']['label'])}</b> "
                    f"{_e(w['misconception']['description'])}</div>"
                    f"<div class='quote'>{_e(rem['text'])}</div>"
                    f"<div class='small'>show_slide <b>{_e(rem['show_slide'])}</b></div>"
                    + (
                        f"<img class='thumb' loading='lazy' src='{_e(img)}' "
                        f"alt='{_e(rem['show_slide'])}'>"
                        if img
                        else ""
                    )
                    + f"<div class='small'>cited: {_chips(rem['citations'])}</div>"
                    + _chunk_quotes(rem["citations"], chunks)
                )
                cell = (
                    f"<span class='ok'>explained</span> {_status(w['status'])} · {_e(rem['title'])}"
                    f"<details><summary>explanation</summary><div class='body'>{body}</div>"
                    "</details>"
                )
            else:
                cell = (
                    f"<span class='bad'>no explanation</span> {_status(w['status'])}"
                    "<div class='muted small'>If this option triggers in class, the correct "
                    "option is only revealed.</div>"
                )
            wrong_rows.append(
                f"<tr><td><b>{_e(w['option'])}</b></td><td>{_e(w['text'])}</td>"
                f"<td>{cell}{_attempts(w['attempts'])}</td></tr>"
            )
        cards.append(
            f"<div class='card'>{head}<p>{_e(p['text'])}</p><ul class='tight'>{options}</ul>"
            f"{_attempts(p['attempts'])}"
            "<div class='table-wrap' style='margin-top:10px'><table><tr><th>Wrong</th><th>"
            "Option</th>"
            f"<th>Explanation</th></tr>{''.join(wrong_rows)}</table></div></div>"
        )
    return "".join(cards) or "<p class='muted'>No polls.</p>"


def _claim_source(claim: dict, rescued: list[str]) -> str:
    if claim.get("chunk_id"):
        return f"<code>{_e(claim['chunk_id'])}</code>"
    if claim.get("claim") in rescued:
        return "<span class='warn'>no chunk named; rescued by code (words found)</span>"
    return "<span class='bad'>no supporting chunk</span>"


def _question_body(r: dict) -> str:
    parts = [f"<div class='small'><b>Why this is expected:</b> {_e(r['why'])}</div>"]
    draft = (r.get("responder") or {}).get("answer_text")
    if r["answer_text"]:
        parts.append(f"<div class='quote'>{_e(r['answer_text'])}</div>")
    elif draft:  # written by the Responder, then blocked: the student never saw it
        parts.append(
            "<div class='small bad'>Draft answer, not sent (blocked after the Responder):</div>"
            f"<div class='quote'>{_e(draft)}</div>"
        )
    parts.append(
        f"<div class='small'>cited: {_chips(r['citations'], set(r['sources']))}"
        f" · expected sources: {_chips(r['sources'])}</div>"
    )
    a = r.get("analyst") or {}
    if a:
        parts.append(
            f"<div class='small'><b>Analyst:</b> {_e(a.get('category'))} · "
            f"{_e(a.get('objective_id') or 'no objective')} · {_e(a.get('reason'))}</div>"
        )
    if r["retrieved"]:
        rows = "".join(
            f"<tr><td>{c['rank']}</td><td>"
            f"{_e(c['chunk_id'])}{' <span class=ok>cited</span>' if c['cited'] else ''}</td>"
            f"<td>{c['score']:.3f}</td><td class='small'>{_e(c['text'])}</td></tr>"
            for c in r["retrieved"]
        )
        parts.append(
            "<div class='table-wrap'><table><tr><th>#</th><th>Chunk</th><th>Score</th><th>Text</th>"
            "</tr>"
            f"{rows}</table></div>"
        )
    g = r.get("guardian") or {}
    if g:
        claims = "".join(
            f"<li>{_e(c.get('claim'))} → {_claim_source(c, r['rescued'])}</li>"
            for c in g.get("claims") or []
            if isinstance(c, dict)
        )
        parts.append(
            f"<div class='small'><b>Guardian:</b> {_e(g.get('verdict'))} · {_e(g.get('reason'))}"
            f"<ul class='tight'>{claims}</ul></div>"
        )
    if r["llm_errors"]:
        parts.append(f"<div class='small bad'>LLM errors: {_e('; '.join(r['llm_errors']))}</div>")
    nodes = " → ".join(
        f"{_e(n['name'])} <span "
        f"class='{ {'pass': 'ok', 'skip': 'muted'}.get(n['status'], 'bad') }'>"
        f"{_e(n['status'])}</span>"
        f" {n['latency_ms']} ms"
        for n in r["nodes"]
    )
    parts.append(f"<div class='small'>{nodes} · deciding node {_e(r['deciding_node'])}</div>")
    return "".join(parts)


def _outcome(action: str, reason: str | None) -> str:
    return _e(action + (f" · {reason}" if reason else ""))


def render_questions(data: dict, summary: dict) -> str:
    q = summary["questions"]
    cats = "".join(
        f"<tr><td>{_e(c)}</td><td>{v['match']}/{v['total']}</td></tr>"
        for c, v in q["by_category"].items()
    )
    head = (
        f"<p class='small muted'>{q['answered']} answered, {q['escalated']} escalated · "
        f"{q['let_through']} answered that should escalate · {q['false_escalations']} "
        f"escalated that should be answered · {q['llm_errors']} LLM errors. Rows that do not "
        "match come first; the expected labels are hand-written, so a mismatch is something "
        "to check, not always a system error.</p>"
        "<div class='table-wrap' style='max-width:360px'><table><tr><th>Category</th><th>As "
        f"expected</th></tr>{cats}</table></div>"
    )
    rows = []
    for r in ordered_rows(data["live"]["rows"]):
        expected = r["expected_action"] + (
            f" · {' / '.join(r['accepted_reasons'])}" if r["accepted_reasons"] else ""
        )
        mark = (
            "<span class='ok'>as expected</span>"
            if r["match"]
            else "<span class='bad'>check</span>"
        )
        rows.append(
            f"<tr><td><b>{_e(r['question_id'])}</b><br><span class='muted small'>"
            f"{_e(r['category'])}</span></td>"
            f"<td>{_e(r['question_text'])}<details><summary>answer, sources, agents</summary>"
            f"<div class='body'>{_question_body(r)}</div></details></td>"
            f"<td>{_e(expected)}</td><td>{_outcome(r['action'], r['escalation_reason'])}<br>{mark}"
            f"<div class='muted small'>{r['latency_ms'] / 1000:.1f} s · {r['llm_calls']} "
            "calls</div></td></tr>"
        )
    return head + (
        "<div class='table-wrap' style='margin-top:12px'><table><tr><th>Id</th><th>Question</th>"
        f"<th>Expected</th><th>Actual</th></tr>{''.join(rows)}</table></div>"
    )


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html>\n<html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_e(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body>"
        "</html>\n"
    )


def render_report(data: dict) -> str:
    summary = summarize(data)
    title = data.get("title") or data["lesson_id"]
    body = (
        f"<p class='small'><a href='../../index.html'>← all runs</a></p>"
        f"<h1>Dev report: {_e(title)}</h1>"
        f"<div class='muted'>Lesson <b>{_e(data['lesson_id'])}</b> · run {_e(data['run_id'])} · "
        f"backend <b>{_e(data['backend'])}</b> · {_e(data['created_at'])}</div>"
        "<div class='banner'>Development view: every number is computed by code from this "
        "run's prep output and test questions. Single run, exploratory.</div>"
        f"<h2>Overview</h2>{render_overview(data, summary)}"
        f"<h2>Scripts</h2>{render_scripts(data)}"
        f"<h2>Polls and wrong-option explanations</h2>{render_polls(data)}"
        f"<h2>Live test questions</h2>{render_questions(data, summary)}"
    )
    return _page(f"Dev report {data['lesson_id']}", body)


def render_index(summaries: list[dict]) -> str:
    rows = []
    for s in sorted(summaries, key=lambda s: (s["lesson_id"], s["run_id"]), reverse=True):
        st, q = s["statuses"], s["questions"]
        scripts_ok = st["scripts"]["ok"] + st["scripts"]["ok_after_retry"]
        rows.append(
            f"<tr><td><b>{_e(s['lesson_id'])}</b></td>"
            f"<td><a href='{_e(s['lesson_id'])}/{_e(s['run_id'])}/report.html'>"
            f"{_e(s['run_id'])}</a></td>"
            f"<td>{_e(s['backend'])}</td><td>{scripts_ok}/{s['slides']}</td>"
            f"<td>{s['active_polls']}</td><td>"
            f"{s['wrong_options_explained']}/{s['wrong_options']}</td>"
            f"<td>{q['match']}/{q['total']}</td>"
            f"<td>{(q['latency_ms_avg'] or 0) / 1000:.1f} s</td></tr>"
        )
    body = (
        "<h1>ClassPilot Live: dev runs</h1>"
        "<div class='muted'>One row per <code>cli dev</code> run, newest first.</div>"
        "<div class='table-wrap' style='margin-top:16px'><table><tr><th>Lesson</th><th>Run</th>"
        "<th>Backend</th><th>Scripts</th><th>Polls in use</th><th>Explained</th>"
        f"<th>Questions as expected</th><th>Latency avg</th></tr>{''.join(rows)}</table></div>"
    )
    return _page("ClassPilot dev runs", body)


def write_index(dev_dir: Path) -> Path:
    import json

    summaries = []
    for path in sorted(dev_dir.glob("*/*/results.json")):
        try:
            summaries.append(summarize(json.loads(path.read_text())))
        except (ValueError, KeyError):
            continue  # an unfinished or older run folder
    out = dev_dir / "index.html"
    out.write_text(render_index(summaries))
    return out
