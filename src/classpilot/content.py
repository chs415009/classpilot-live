"""Load the fixture lessons from content/: chunks (mock retrieval) and the manifest.

lesson_chunks.json is the v1 lesson (also loaded into the v1 LESSON_CHUNKS table for
the Stage 3 parity check). other_lesson_chunks.json is a second lesson whose chunks
the lesson_id filter must keep out. Objective keywords are used by the mock only.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from classpilot.contracts.manifest import Manifest, load_manifest
from classpilot.settings import PROJECT_ROOT

DEFAULT_CONTENT_DIR = PROJECT_ROOT / "content"


LESSON_FILES = ["lesson_chunks.json", "other_lesson_chunks.json"]


@dataclass
class Content:
    lesson_id: str  # the fixture lesson that the manifest and objectives belong to
    objectives: list[dict]
    chunks: list[dict]  # chunks of every fixture lesson, each with its lesson_id
    manifest: Manifest


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
