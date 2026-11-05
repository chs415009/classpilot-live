"""A Markdown review sheet of one generation run (Stage 7 human review).

Written next to the manifest as `outputs/prep/<lesson>/review.md` (gitignored: it holds
course content). It shows what the reviewer must read: the readings per item type,
the placement, every script, every poll with its misconceptions and explanations, the
Guardian decisions (all fails, and a few passes), and the text of every cited chunk.
"""

from classpilot.contracts.manifest import Manifest

PASSES_SHOWN = 3


def _one_line(text: str, limit: int = 0) -> str:
    text = " ".join(text.split())
    return text if not limit or len(text) <= limit else text[: limit - 3] + "..."


def _guardian_block(item: str, n: int, attempt: dict) -> list[str]:
    g = attempt.get("guardian") or {}
    lines = [
        f"**{item}**, attempt {n}: rule says `{attempt['outcome']}`; "
        f"Guardian verdict `{g.get('verdict')}`: {_one_line(str(g.get('reason', '')))}"
    ]
    for claim in g.get("claims") or []:
        if isinstance(claim, dict):
            lines.append(
                f"- claim: {_one_line(str(claim.get('claim')))} -> `{claim.get('chunk_id')}`"
            )
    for wrong in g.get("wrong_options") or []:
        if isinstance(wrong, dict):
            lines.append(
                f"- wrong option {wrong.get('option')} shown wrong by `{wrong.get('chunk_id')}`"
            )
    lines += [f"- problem: {_one_line(p)}" for p in attempt.get("problems", [])]
    return [*lines, ""]


def render_review(manifest: Manifest, report: dict, chunks: dict[str, str]) -> str:
    """`report` is the stored generation report; `chunks` maps chunk id -> text."""
    items = report.get("items", [])
    out = [
        f"# Generation review: {manifest.lesson_id}",
        "",
        f"Backend `{report.get('backend')}`, poll_count {report.get('poll_count')}, "
        f"{report.get('llm_calls')} LLM calls, {len(manifest.slides)} slides.",
        "",
        "## Readings per item type",
        "",
        "| Kind | Items | Statuses | Retries | LLM errors | Calls | Latency total s | Max item s |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for kind, row in (report.get("summary") or {}).items():
        statuses = ", ".join(f"{k} {v}" for k, v in sorted(row["statuses"].items()))
        out.append(
            f"| {kind} | {row['items']} | {statuses} | {row['retries']} | {row['llm_errors']} "
            f"| {row['calls']} | {row['latency_ms'] / 1000:.1f} | "
            f"{row['max_item_latency_ms'] / 1000:.1f} |"
        )

    by_name = {i["item"]: i for i in items}
    placement = by_name.get("placement", {})
    out += [
        "",
        "## Segments and placement",
        "",
        f"Segments: `{by_name.get('segments', {}).get('status')}`. "
        f"Placement: `{placement.get('status')}` {placement.get('detail', '')}",
        "",
    ]
    for seg in manifest.segments:
        poll = f"poll {seg.active_poll}" if seg.active_poll else "no poll"
        out.append(
            f"- **{seg.segment_id}** ({seg.slides[0]}..{seg.slides[-1]}, {poll}): {seg.objective}"
        )

    out += ["", "## Scripts", "", "| Slide | Status | Script |", "|---|---|---|"]
    for slide_id, slide in sorted(manifest.slides.items(), key=lambda kv: kv[1].order):
        detail = by_name.get(f"script {slide_id}", {}).get("detail")
        status = f"{slide.status} ({detail})" if detail else slide.status
        out.append(f"| {slide_id} | {status} | {_one_line(slide.script)} |")

    out += ["", "## Polls", ""]
    for seg in manifest.segments:
        for qid, q in seg.questions.items():
            report_item = by_name.get(f"poll {qid} {seg.segment_id}", {})
            out += [f"### {qid} ({seg.segment_id}): `{q.status}`", ""]
            if q.status == "dropped":
                out += [f"Dropped: {report_item.get('detail', '')}.", ""]
            out += [f"**{q.text or '(no valid poll)'}**", ""]
            for key, text in sorted(q.options.items()):
                mark = " (correct)" if key == q.correct_option else ""
                out.append(f"- {key}: {text}{mark}")
            out.append("")
            for option, mid in sorted(q.known_wrong.items()):
                mis = manifest.misconceptions[mid]
                rem = manifest.remediations[mis.remediation]
                out += [
                    f"**{option} → {mid}** {mis.label}: {mis.description}",
                    "",
                    f"- {mis.remediation} `{rem.status}` *{rem.title}*: {rem.text}",
                    f"- show_slide `{rem.show_slide}`; citations {', '.join(rem.citations)}",
                    "",
                ]

    out += ["## Guardian decisions", "", "All fails and errors:", ""]
    passes = []
    for i in items:
        for n, attempt in enumerate(i.get("attempts", []), start=1):
            if attempt["outcome"] == "pass" and attempt.get("guardian"):
                passes.append((i["item"], n, attempt))
            elif attempt["outcome"] != "pass":
                out += _guardian_block(i["item"], n, attempt)
    out += [f"First {PASSES_SHOWN} passes:", ""]
    for item, n, attempt in passes[:PASSES_SHOWN]:
        out += _guardian_block(item, n, attempt)

    cited = sorted(
        {c for i in items for c in i.get("citations", [])}
        | {c for r in manifest.remediations.values() for c in r.citations}
    )
    out += ["## Cited chunks", ""]
    out += [f"- `{c}`: {_one_line(chunks.get(c, '(missing)'), 400)}" for c in cited]
    return "\n".join(out) + "\n"
