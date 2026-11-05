"""Load the fixture lesson from content/: chunks (mock retrieval) and the manifest."""

import json
from dataclasses import dataclass
from pathlib import Path

from classpilot.contracts.manifest import Manifest, load_manifest
from classpilot.settings import PROJECT_ROOT

DEFAULT_CONTENT_DIR = PROJECT_ROOT / "content"


@dataclass
class Content:
    objectives: list[dict]
    chunks: list[dict]
    manifest: Manifest
    protected_questions: list[dict]


def load_content(content_dir: Path = DEFAULT_CONTENT_DIR) -> Content:
    def read(name: str):
        return json.loads((content_dir / name).read_text())

    lesson = read("lesson_chunks.json")
    return Content(
        objectives=lesson["objectives"],
        chunks=lesson["chunks"],
        manifest=load_manifest(content_dir / "manifest.json"),
        protected_questions=read("protected_questions.json"),
    )
