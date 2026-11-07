"""Load the fixture lessons from content/: chunks (mock retrieval) and the manifest.

lesson_chunks.json is the v1 lesson; it lives only here (mock retrieval, also with
BACKEND=cortex), not in Snowflake. other_lesson_chunks.json is a second lesson whose chunks
the lesson_id filter must keep out. Objective keywords are used by the mock only.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from classpilot.contracts.manifest import Manifest, load_manifest
from classpilot.settings import PROJECT_ROOT
from classpilot.text import content_words

DEFAULT_CONTENT_DIR = PROJECT_ROOT / "content"


LESSON_FILES = ["lesson_chunks.json", "other_lesson_chunks.json"]
MAX_KEYWORDS = 40  # per objective, for the mock Analyst only


@dataclass
class Content:
    lesson_id: str  # the fixture lesson that the manifest and objectives belong to
    objectives: list[dict]
    chunks: list[dict]  # chunks of every fixture lesson, each with its lesson_id
    manifest: Manifest | None = None  # None for eval question sets (no poll path)


def load_content(content_dir: Path = DEFAULT_CONTENT_DIR) -> Content:
    def read(name: str):
        return json.loads((content_dir / name).read_text())

    lessons = [read(name) for name in LESSON_FILES]
    chunks = [
        {**c, "lesson_id": lesson["lesson_id"]} for lesson in lessons for c in lesson["chunks"]
    ]
    manifest = load_manifest(content_dir / "manifest.json")
    main = lessons[0]
    if manifest.lesson_id != main["lesson_id"]:
        raise ValueError("content/manifest.json and lesson_chunks.json name different lessons")
    return Content(main["lesson_id"], main["objectives"], chunks, manifest)


def lesson_content(lesson_id: str, manifest: Manifest, chunks: list) -> Content:
    """Live content of a prepped lesson: its manifest, objectives from its segments, and
    its chunks (objects with `chunk_id`, `page_id`, `text`). Keywords feed the mock only."""
    rows = [{"chunk_id": c.chunk_id, "text": c.text, "lesson_id": lesson_id} for c in chunks]
    objectives = []
    for seg in manifest.segments:
        words = content_words(seg.objective)
        words += [w for c in chunks if c.page_id in seg.slides for w in content_words(c.text)]
        keywords = list(dict.fromkeys(words))[:MAX_KEYWORDS]
        objectives.append(
            {"objective_id": seg.segment_id, "title": seg.objective, "keywords": keywords}
        )
    return Content(lesson_id, objectives, rows, manifest)
