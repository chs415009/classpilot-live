"""Zip files the service hands to the other parts (Stage 11, interface_questions Q-18, Q-22).

lesson_bundle   everything the front end needs to run a class: manifest.json + slides/*.png
session_export  everything the pipeline needs after class: the session's trace records and
                decision-log lines, plus the manifest and generation report of each lesson

Both are plain files (JSON, JSONL, PNG) in a zip; how they are stored or loaded is up to
the receiving part. Nothing here calls an LLM or Snowflake.
"""

import io
import json
import zipfile
from pathlib import Path

from classpilot.contracts.trace import SCHEMA_VERSION


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            # PNGs are already compressed; text files shrink a lot
            method = zipfile.ZIP_STORED if name.endswith(".png") else zipfile.ZIP_DEFLATED
            zf.writestr(name, data, compress_type=method)
    return buf.getvalue()


def lesson_bundle(prep_dir: Path) -> bytes:
    """manifest.json and slides/<slide_id>.png of one prepped lesson (FileNotFoundError
    without a manifest)."""
    files = {"manifest.json": (prep_dir / "manifest.json").read_bytes()}
    slides = prep_dir / "slides"
    if slides.is_dir():
        for png in sorted(slides.glob("*.png")):
            files[f"slides/{png.name}"] = png.read_bytes()
    return _zip(files)


def session_lines(path: Path, session_id: str) -> list[str]:
    """The JSONL lines of one session (trace records or decision-log entries)."""
    if not path.is_file():
        return []
    out = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue  # a torn last line after a crash; skip it
            session = record.get("session_id") or (record.get("decision") or {}).get("session_id")
            if session == session_id:
                out.append(line)
    return out


def session_export(
    session_id: str,
    trace_path: Path,
    log_path: Path,
    prep_dir_for,
    exported_at: str,
) -> tuple[bytes, dict] | None:
    """The session's zip and its summary, or None if the session has no decision.

    `prep_dir_for(lesson_id)` gives the lesson's prep folder (manifest.json,
    generation_report.json).
    """
    log = session_lines(log_path, session_id)
    if not log:
        return None
    traces = session_lines(trace_path, session_id)
    entries = [json.loads(line) for line in log]
    lessons = sorted({e["lesson_id"] for e in entries})
    decisions = [e["decision"] for e in entries]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "exported_at": exported_at,
        "lessons": lessons,
        "decisions": len(decisions),
        "questions": sum(d["path"] == "question" for d in decisions),
        "polls": sum(d["path"] == "poll" for d in decisions),
        "trace_records": len(traces),
        "files": ["export.json", "traces.jsonl", "decision_log.jsonl"],
    }
    files = {
        "traces.jsonl": "".join(f"{line}\n" for line in traces).encode(),
        "decision_log.jsonl": "".join(f"{line}\n" for line in log).encode(),
    }
    for lesson_id in lessons:
        prep_dir = prep_dir_for(lesson_id)
        for name in ("manifest.json", "generation_report.json"):
            path = prep_dir / name
            if path.is_file():
                files[f"lessons/{lesson_id}/{name}"] = path.read_bytes()
                summary["files"].append(f"lessons/{lesson_id}/{name}")
    files = {"export.json": json.dumps(summary, indent=2).encode(), **files}
    return _zip(files), summary
