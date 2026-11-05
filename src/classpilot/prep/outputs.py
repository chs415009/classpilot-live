"""Write a generation run to a lesson's output folder (shared by the CLI and the service).

<out_dir>/manifest.json, generation_report.json, review.md, and slides/<slide_id>.png.
The checks (`prep/checks.py`) run against the lesson's stored chunks before anything is
reported as done.
"""

import json
import shutil
from dataclasses import asdict
from pathlib import Path

from classpilot.prep.checks import manifest_check_problems
from classpilot.prep.generate import GenerationResult
from classpilot.prep.review import render_review
from classpilot.prep.tables import PrepTables


def write_generation(out_dir: Path, result: GenerationResult, backend: str, seconds: float) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(result.manifest.model_dump_json(indent=2))
    report = {
        "backend": backend,
        "seconds": seconds,
        **asdict(result.report),
        "summary": result.report.summary(),
    }
    (out_dir / "generation_report.json").write_text(json.dumps(report, indent=2))
    return report


def copy_slide_images(
    lesson_id: str, tables: PrepTables, convert_root: Path, out_dir: Path
) -> tuple[int, int]:
    """Slide PNGs from the local conversion into <out>/slides/<slide_id>.png."""
    copied = missing = 0
    (out_dir / "slides").mkdir(parents=True, exist_ok=True)
    for parsed in tables.lesson_files(lesson_id):
        if parsed.kind != "slides":
            continue
        for page in parsed.pages:
            png = convert_root / parsed.file_id[:16] / "pages" / f"p{page.page_index:02d}.png"
            if png.is_file():
                shutil.copyfile(png, out_dir / "slides" / f"{page.page_id}.png")
                copied += 1
            else:
                missing += 1
    return copied, missing


def check_and_review(
    out_dir: Path, lesson_id: str, tables: PrepTables, poll_count: int
) -> tuple[list[str], int]:
    """Run the checks on the stored manifest and write review.md.

    Returns (problems, number of lesson chunks). Raises ValueError if the manifest does
    not validate and FileNotFoundError if there is none.
    """
    from classpilot.contracts.manifest import load_manifest

    manifest = load_manifest(out_dir / "manifest.json")
    report = json.loads((out_dir / "generation_report.json").read_text())
    chunks = tables.lesson_chunks(lesson_id)
    pages = {c.chunk_id: c.page_id for c in chunks}
    problems = manifest_check_problems(manifest, report, pages, poll_count)
    review = render_review(manifest, report, {c.chunk_id: c.text for c in chunks})
    (out_dir / "review.md").write_text(review)
    return problems, len(pages)
