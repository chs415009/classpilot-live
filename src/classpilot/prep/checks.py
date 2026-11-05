"""Checks on a generated manifest against the lesson's stored chunks (Stage 7).

Run after every generation (`prep generate`, `prep run`) and on its own (`prep check`).
The chunk ids come from the prep tables (LESSON_CHUNKS_V2 on Cortex), so a citation
that does not resolve there is caught even if the generator invented it after the
structure checks.
"""

from classpilot.contracts.manifest import Manifest
from classpilot.prep.tts import tts_issues
from classpilot.rules.prep import manifest_poll_problems


def manifest_check_problems(
    manifest: Manifest, report: dict, chunk_pages: dict[str, str], poll_count: int
) -> list[str]:
    """`report` is the generation report as stored (JSON); `chunk_pages` maps every chunk
    id of the lesson to its page id. An empty list means every check passed."""
    problems: list[str] = []
    items = {i["item"]: i for i in report.get("items", [])}

    # Every item has a status (the model requires one) and a report entry.
    for slide_id in manifest.slides:
        if f"script {slide_id}" not in items:
            problems.append(f"script {slide_id}: no report entry")
    for seg in manifest.segments:
        for qid in seg.questions:
            if f"poll {qid} {seg.segment_id}" not in items:
                problems.append(f"poll {qid}: no report entry")

    # Every citation resolves to a lesson chunk.
    cited: list[tuple[str, str]] = [
        (name, c) for name, i in items.items() for c in i.get("citations", [])
    ]
    cited += [(rid, c) for rid, rem in manifest.remediations.items() for c in rem.citations]
    for where, chunk_id in cited:
        if chunk_id not in chunk_pages:
            problems.append(f"{where}: citation {chunk_id!r} is not a chunk of the lesson")

    # Every show_slide is a slide of a cited chunk.
    for rid, rem in manifest.remediations.items():
        pages = {chunk_pages.get(c) for c in rem.citations}
        if rem.show_slide not in manifest.slides or rem.show_slide not in pages:
            problems.append(f"{rid}: show_slide {rem.show_slide!r} is not a slide of its citations")

    # Scripts and explanations pass the TTS lint.
    for slide_id, slide in manifest.slides.items():
        if issues := tts_issues(slide.script):
            problems.append(f"script {slide_id}: TTS lint ({', '.join(issues)})")
    for rid, rem in manifest.remediations.items():
        if issues := tts_issues(rem.text):
            problems.append(f"{rid}: TTS lint ({', '.join(issues)})")

    # No active_poll points to a dropped question; poll limits.
    for seg in manifest.segments:
        if seg.active_poll and seg.questions[seg.active_poll].status == "dropped":
            problems.append(f"{seg.segment_id}: active_poll {seg.active_poll} is dropped")
    return problems + manifest_poll_problems(manifest, poll_count)
